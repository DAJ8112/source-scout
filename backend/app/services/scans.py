from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.connectors.errors import ConnectorError
from app.connectors.registry import ConnectorRegistry
from app.connectors.types import NormalizedJob
from app.models import CareersSource, Job, JobObservation, ScanRun
from app.services.matching import match_jobs

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


def recover_interrupted_runs(session: Session, now: datetime | None = None) -> int:
    recovered_at = now or datetime.now(UTC)
    stale_before = recovered_at - timedelta(seconds=settings.scan_stale_after_seconds)
    running = list(
        session.scalars(
            select(ScanRun).where(
                ScanRun.status == "running",
                (ScanRun.started_at.is_(None)) | (ScanRun.started_at <= stale_before),
            )
        )
    )
    for scan in running:
        scan.status = "interrupted"
        scan.finished_at = recovered_at
        scan.error_code = "process_interrupted"
        scan.error_diagnostics = {
            "message": "The scan worker stopped before this scan finished; it has been requeued."
        }
        source = session.get(CareersSource, scan.source_id)
        if source:
            source.last_scan_attempt_at = recovered_at
            source.next_scan_at = recovered_at
    session.commit()
    return len(running)


def unfinished_scan_for_source(session: Session, source_id: str) -> ScanRun | None:
    return session.scalar(
        select(ScanRun)
        .where(ScanRun.source_id == source_id, ScanRun.status.in_(["queued", "running"]))
        .limit(1)
    )


def enqueue_due_scans(session: Session, now: datetime | None = None) -> list[str]:
    due_at = now or datetime.now(UTC)
    sources = list(
        session.scalars(
            select(CareersSource)
            .where(
                CareersSource.monitoring_status == "active",
                CareersSource.connector_type.is_not(None),
                CareersSource.setup_status != "setup_required",
                CareersSource.next_scan_at <= due_at,
            )
            .order_by(CareersSource.next_scan_at, CareersSource.created_at)
        )
    )
    created: list[str] = []
    for source in sources:
        if unfinished_scan_for_source(session, source.id):
            continue
        scan = ScanRun(
            source_id=source.id,
            trigger="initial" if source.last_successful_scan_at is None else "scheduled",
            progress={"phase": "queued"},
        )
        try:
            with session.begin_nested():
                session.add(scan)
                session.flush()
        except IntegrityError:
            continue
        created.append(scan.id)
    session.commit()
    return created


def next_queued_scan_id(session: Session) -> str | None:
    ids = next_queued_scan_ids(session, 1)
    return ids[0] if ids else None


def next_queued_scan_ids(session: Session, limit: int) -> list[str]:
    if limit < 1:
        return []
    return list(
        session.scalars(
            select(ScanRun.id)
            .where(ScanRun.status == "queued")
            .order_by(ScanRun.created_at, ScanRun.id)
            .limit(limit)
        )
    )


def record_source_attempt(
    source: CareersSource,
    finished_at: datetime,
    *,
    successful: bool,
) -> None:
    source.last_scan_attempt_at = finished_at
    if successful:
        source.last_successful_scan_at = finished_at
    interval = settings.scan_interval_seconds
    next_boundary = ((int(finished_at.timestamp()) // interval) + 1) * interval
    source.next_scan_at = datetime.fromtimestamp(next_boundary, UTC)


async def execute_scan(scan_id: str, app) -> None:
    factory: sessionmaker[Session] = app.state.session_factory
    with factory() as session:
        claim = session.execute(
            update(ScanRun)
            .where(ScanRun.id == scan_id, ScanRun.status == "queued")
            .values(
                status="running",
                started_at=datetime.now(UTC),
                progress={"phase": "traversing", "message": "Fetching official source"},
            )
        )
        session.commit()
        if claim.rowcount != 1:
            return
        scan = session.get(ScanRun, scan_id)
        if not scan:
            return
        source = session.get(CareersSource, scan.source_id)
        if not source:
            scan.status = "failed"
            scan.error_code = "source_missing"
            scan.finished_at = datetime.now(UTC)
            session.commit()
            return
        try:
            connector = ConnectorRegistry(app.state.http).get(
                source.connector_type or "", source.detected_platform
            )
            output = await connector.scan(source.url, source.connector_config)
            unique_jobs = {job_identity_key(job): job for job in output.jobs}
            scan.jobs_found = len(output.jobs)
            scan.pages_visited = output.pages_visited
            scan.warnings = list(output.warnings)
            if not output.complete and not any(
                warning.get("code") == "incomplete_scan" for warning in scan.warnings
            ):
                scan.warnings = [
                    *scan.warnings,
                    {
                        "code": "incomplete_scan",
                        "message": (
                            "Traversal was incomplete; observed jobs were saved but absence "
                            "transitions were skipped"
                        ),
                    },
                ]
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

            if output.complete:
                for job in current_jobs:
                    if job.id in observed_job_ids or job.lifecycle_status == "closed":
                        continue
                    job.consecutive_successful_absences += 1
                    job.lifecycle_status = (
                        "closed"
                        if job.consecutive_successful_absences >= 2
                        else "possibly_closed"
                    )
                    scan.jobs_missing += 1

            matcher = getattr(app.state, "matcher", None)
            if matcher:
                scan.progress = {
                    "phase": "matching",
                    "current": 0,
                    "total": len(observed_job_ids),
                }
                match_summary = await match_jobs(
                    session,
                    matcher,
                    job_ids=observed_job_ids,
                )
                if match_summary.failed:
                    scan.warnings = [
                        *scan.warnings,
                        {
                            "code": "matching_failures",
                            "message": f"{match_summary.failed} job(s) could not be matched",
                        },
                    ]

            scan.jobs_persisted = len(unique_jobs)
            if not output.complete:
                scan.status = "partial"
            elif scan.warnings:
                scan.status = "success_with_warnings"
            else:
                scan.status = "success"
            scan.progress = {
                "phase": "partial" if not output.complete else "complete",
                "current": len(unique_jobs),
                "total": len(unique_jobs),
            }
            scan.finished_at = datetime.now(UTC)
            if output.complete:
                source.health_status = "healthy"
                source.setup_status = "ready"
            else:
                source.health_status = "temporarily_failing"
            record_source_attempt(source, scan.finished_at, successful=output.complete)
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
                record_source_attempt(source, scan.finished_at, successful=False)
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
                source = session.get(CareersSource, scan.source_id)
                if source:
                    source.health_status = "temporarily_failing"
                    record_source_attempt(source, scan.finished_at, successful=False)
                session.commit()
    scan_tasks = getattr(app.state, "scan_tasks", None)
    if scan_tasks is not None:
        scan_tasks.pop(scan_id, None)
