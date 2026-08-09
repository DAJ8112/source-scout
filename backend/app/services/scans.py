from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.connectors.errors import ConnectorError
from app.connectors.registry import ConnectorRegistry
from app.connectors.types import NormalizedJob
from app.models import CareersSource, Job, JobObservation, ScanRun

logger = logging.getLogger(__name__)


def job_identity_key(job: NormalizedJob) -> str:
    if job.external_id:
        return f"external:{job.external_id.strip()}"
    return f"url:{job.canonical_url}"


def apply_observation(job: Job, observed: NormalizedJob, observed_at: datetime) -> None:
    job.identity_key = job_identity_key(observed)
    job.external_id = observed.external_id
    job.canonical_url = observed.canonical_url
    job.title = observed.title
    job.locations = observed.locations
    job.employment_type = observed.employment_type
    job.posted_date = observed.posted_date
    job.description_html = observed.description_html
    job.description_text = observed.description_text
    job.content_fingerprint = observed.content_fingerprint
    job.raw_metadata = observed.raw_metadata
    job.lifecycle_status = "active"
    job.consecutive_successful_absences = 0
    job.last_observed_at = observed_at


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
            unique_jobs = {job_identity_key(job): job for job in output.jobs}
            scan.jobs_found = len(output.jobs)
            scan.pages_visited = output.pages_visited
            scan.warnings = output.warnings
            scan.progress = {"phase": "persisting", "current": 0, "total": len(unique_jobs)}
            session.commit()

            observed_at = datetime.now(UTC)
            first_successful_scan = (
                session.scalar(
                    select(ScanRun.id)
                    .where(
                        ScanRun.source_id == source.id,
                        ScanRun.id != scan.id,
                        ScanRun.status.in_(["success", "success_with_warnings"]),
                    )
                    .limit(1)
                )
                is None
            )
            current_jobs = list(session.scalars(select(Job).where(Job.source_id == source.id)))
            by_identity = {job.identity_key: job for job in current_jobs}
            by_url = {job.canonical_url: job for job in current_jobs}
            observed_job_ids: set[str] = set()

            for index, observed in enumerate(unique_jobs.values(), start=1):
                identity_key = job_identity_key(observed)
                job = by_identity.get(identity_key) or by_url.get(observed.canonical_url)
                if job is None:
                    job = Job(
                        source_id=source.id,
                        identity_key=identity_key,
                        external_id=observed.external_id,
                        canonical_url=observed.canonical_url,
                        title=observed.title,
                        locations=observed.locations,
                        employment_type=observed.employment_type,
                        posted_date=observed.posted_date,
                        description_html=observed.description_html,
                        description_text=observed.description_text,
                        content_fingerprint=observed.content_fingerprint,
                        raw_metadata=observed.raw_metadata,
                        lifecycle_status="active",
                        consecutive_successful_absences=0,
                        initial_import=first_successful_scan,
                        first_discovered_at=observed_at,
                        last_observed_at=observed_at,
                    )
                    session.add(job)
                    session.flush()
                    current_jobs.append(job)
                    scan.jobs_created += 1
                else:
                    if job.content_fingerprint != observed.content_fingerprint:
                        scan.jobs_updated += 1
                    apply_observation(job, observed, observed_at)

                by_identity[job.identity_key] = job
                by_url[job.canonical_url] = job
                observed_job_ids.add(job.id)
                session.add(
                    JobObservation(
                        scan_run_id=scan.id,
                        source_id=source.id,
                        job_id=job.id,
                        external_id=observed.external_id,
                        canonical_url=observed.canonical_url,
                        title=observed.title,
                        locations=observed.locations,
                        employment_type=observed.employment_type,
                        posted_date=observed.posted_date,
                        description_html=observed.description_html,
                        description_text=observed.description_text,
                        content_fingerprint=observed.content_fingerprint,
                        raw_metadata=observed.raw_metadata,
                        observed_at=observed_at,
                    )
                )
                if index % 50 == 0:
                    scan.progress = {
                        "phase": "persisting",
                        "current": index,
                        "total": len(unique_jobs),
                    }
                    session.flush()

            for job in current_jobs:
                if job.id in observed_job_ids or job.lifecycle_status == "closed":
                    continue
                job.consecutive_successful_absences += 1
                job.lifecycle_status = (
                    "closed" if job.consecutive_successful_absences >= 2 else "possibly_closed"
                )
                scan.jobs_missing += 1

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
