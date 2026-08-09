from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.connectors.errors import ConnectorError
from app.connectors.registry import ConnectorRegistry
from app.models import CareersSource, JobObservation, ScanRun

logger = logging.getLogger(__name__)


def recover_interrupted_runs(session: Session) -> int:
    now = datetime.now(UTC)
    result = session.execute(
        update(ScanRun)
        .where(ScanRun.status.in_(["queued", "running"]))
        .values(
            status="interrupted",
            finished_at=now,
            error_code="process_interrupted",
            error_diagnostics={
                "message": "The application stopped before this in-process scan finished; run it again."
            },
        )
    )
    session.commit()
    return result.rowcount or 0


async def execute_scan(scan_id: str, app) -> None:
    factory: sessionmaker[Session] = app.state.session_factory
    with factory() as session:
        scan = session.get(ScanRun, scan_id)
        if not scan or scan.status != "queued":
            return
        source = session.get(CareersSource, scan.source_id)
        if not source:
            scan.status = "failed"
            scan.error_code = "source_missing"
            scan.finished_at = datetime.now(UTC)
            session.commit()
            return
        scan.status = "running"
        scan.started_at = datetime.now(UTC)
        scan.progress = {"phase": "traversing", "message": "Fetching official source"}
        session.commit()
        try:
            connector = ConnectorRegistry(app.state.http).get(
                source.connector_type or "", source.detected_platform
            )
            output = await connector.scan(source.url, source.connector_config)
            unique_jobs = {job.canonical_url: job for job in output.jobs}
            scan.jobs_found = len(output.jobs)
            scan.pages_visited = output.pages_visited
            scan.warnings = output.warnings
            scan.progress = {"phase": "persisting", "current": 0, "total": len(unique_jobs)}
            session.commit()
            for index, job in enumerate(unique_jobs.values(), start=1):
                session.add(
                    JobObservation(
                        scan_run_id=scan.id,
                        source_id=source.id,
                        external_id=job.external_id,
                        canonical_url=job.canonical_url,
                        title=job.title,
                        locations=job.locations,
                        employment_type=job.employment_type,
                        posted_date=job.posted_date,
                        description_html=job.description_html,
                        description_text=job.description_text,
                        content_fingerprint=job.content_fingerprint,
                        raw_metadata=job.raw_metadata,
                    )
                )
                if index % 50 == 0:
                    scan.progress = {
                        "phase": "persisting",
                        "current": index,
                        "total": len(unique_jobs),
                    }
                    session.commit()
            scan.jobs_persisted = len(unique_jobs)
            scan.status = "success_with_warnings" if output.warnings else "success"
            scan.progress = {
                "phase": "complete",
                "current": len(unique_jobs),
                "total": len(unique_jobs),
            }
            scan.finished_at = datetime.now(UTC)
            source.health_status = "healthy"
            source.setup_status = "ready"
            session.commit()
        except ConnectorError as exc:
            session.rollback()
            scan = session.get(ScanRun, scan_id)
            source = session.get(CareersSource, scan.source_id) if scan else None
            if not scan:
                return
            scan.status = "failed"
            scan.finished_at = datetime.now(UTC)
            scan.error_code = exc.code
            scan.error_diagnostics = exc.as_dict()
            scan.progress = {"phase": "failed", "message": exc.message}
            if source:
                if exc.code in {
                    "access_blocked",
                    "detail_extraction_failure",
                    "facet_drift",
                    "invalid_configuration",
                    "robots_disallowed",
                    "unsupported_connector",
                    "zero_results",
                }:
                    source.setup_status = "setup_required"
                    source.health_status = "setup_required"
                else:
                    source.health_status = "temporarily_failing"
            session.commit()
        except Exception as exc:  # defensive boundary for background tasks
            logger.exception("Unhandled scan failure", extra={"scan_id": scan_id})
            session.rollback()
            scan = session.get(ScanRun, scan_id)
            if scan:
                scan.status = "failed"
                scan.finished_at = datetime.now(UTC)
                scan.error_code = "internal_error"
                scan.error_diagnostics = {
                    "code": "internal_error",
                    "message": "Unexpected internal scan failure",
                    "exception": type(exc).__name__,
                }
                session.commit()
    app.state.scan_tasks.pop(scan_id, None)


def unfinished_scan_for_source(session: Session, source_id: str) -> ScanRun | None:
    return session.scalar(
        select(ScanRun)
        .where(ScanRun.source_id == source_id, ScanRun.status.in_(["queued", "running"]))
        .limit(1)
    )
