from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.connectors.errors import ConnectorError
from app.connectors.registry import ConnectorRegistry
from app.db import get_session
from app.models import CareersSource, Job, JobObservation, ReferralContact, ScanRun
from app.schemas import (
    CurrentJobRead,
    CurrentJobsPage,
    JobRead,
    JobsPage,
    ReferralContactCreate,
    ReferralContactPatch,
    ReferralContactRead,
    ScanCreate,
    ScanRead,
    SourceCreate,
    SourcePatch,
    SourceRead,
    ValidationResponse,
)
from app.services.scans import unfinished_scan_for_source

router = APIRouter(prefix="/api")


def source_or_404(session: Session, source_id: str) -> CareersSource:
    source = session.get(CareersSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.post("/sources", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: SourceCreate, request: Request, session: Session = Depends(get_session)
) -> CareersSource:
    url = str(payload.url)
    source = CareersSource(company=payload.company, url=url)
    try:
        connector, detection = await ConnectorRegistry(request.app.state.http).detect(url)
        source.detected_platform = detection.platform
        source.connector_type = detection.connector_type
        source.connector_config = detection.config
        source.detection = detection.model_dump(mode="json")
    except ConnectorError as exc:
        source.setup_status = "setup_required"
        source.health_status = "setup_required"
        source.detection = exc.as_dict()
    session.add(source)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="This careers URL already exists") from exc
    session.refresh(source)
    return source


@router.get("/sources", response_model=list[SourceRead])
def list_sources(session: Session = Depends(get_session)) -> list[CareersSource]:
    return list(
        session.scalars(
            select(CareersSource)
            .options(selectinload(CareersSource.contacts))
            .order_by(CareersSource.created_at)
        ).all()
    )


@router.get("/sources/{source_id}", response_model=SourceRead)
def get_source(source_id: str, session: Session = Depends(get_session)) -> CareersSource:
    return source_or_404(session, source_id)


def contact_or_404(
    session: Session, source_id: str, contact_id: str
) -> ReferralContact:
    contact = session.get(ReferralContact, contact_id)
    if not contact or contact.source_id != source_id:
        raise HTTPException(status_code=404, detail="Referral contact not found")
    return contact


@router.post(
    "/sources/{source_id}/contacts",
    response_model=ReferralContactRead,
    status_code=status.HTTP_201_CREATED,
)
def create_contact(
    source_id: str,
    payload: ReferralContactCreate,
    session: Session = Depends(get_session),
) -> ReferralContact:
    source_or_404(session, source_id)
    contact = ReferralContact(
        source_id=source_id,
        name=payload.name,
        contact_url=str(payload.contact_url) if payload.contact_url else None,
        notes=payload.notes,
    )
    session.add(contact)
    session.commit()
    session.refresh(contact)
    return contact


@router.patch(
    "/sources/{source_id}/contacts/{contact_id}", response_model=ReferralContactRead
)
def patch_contact(
    source_id: str,
    contact_id: str,
    payload: ReferralContactPatch,
    session: Session = Depends(get_session),
) -> ReferralContact:
    contact = contact_or_404(session, source_id, contact_id)
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes:
        contact.name = changes["name"]
    if "contact_url" in changes:
        contact.contact_url = str(changes["contact_url"]) if changes["contact_url"] else None
    if "notes" in changes:
        contact.notes = changes["notes"]
    session.commit()
    session.refresh(contact)
    return contact


@router.delete(
    "/sources/{source_id}/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_contact(
    source_id: str,
    contact_id: str,
    session: Session = Depends(get_session),
) -> Response:
    contact = contact_or_404(session, source_id, contact_id)
    session.delete(contact)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/sources/{source_id}", response_model=SourceRead)
async def patch_source(
    source_id: str,
    payload: SourcePatch,
    request: Request,
    session: Session = Depends(get_session),
) -> CareersSource:
    source = source_or_404(session, source_id)
    changes = payload.model_dump(exclude_unset=True)
    if "company" in changes:
        source.company = changes["company"].strip()
    if "connector_config" in changes:
        source.connector_config = changes["connector_config"]
        source.setup_status = "unvalidated"
        source.next_scan_at = datetime.now(UTC)
    if "monitoring_status" in changes:
        source.monitoring_status = changes["monitoring_status"]
        if source.monitoring_status == "active":
            source.next_scan_at = datetime.now(UTC)
    if "url" in changes:
        source.url = str(changes["url"])
        try:
            _, detection = await ConnectorRegistry(request.app.state.http).detect(source.url)
        except ConnectorError as exc:
            source.detected_platform = None
            source.connector_type = None
            source.connector_config = {}
            source.detection = exc.as_dict()
            source.setup_status = "setup_required"
        else:
            source.detected_platform = detection.platform
            source.connector_type = detection.connector_type
            source.connector_config = detection.config
            source.detection = detection.model_dump(mode="json")
            source.setup_status = "unvalidated"
            source.next_scan_at = datetime.now(UTC)
    session.commit()
    session.refresh(source)
    return source


@router.post("/sources/{source_id}/validate", response_model=ValidationResponse)
async def validate_source(
    source_id: str, request: Request, session: Session = Depends(get_session)
) -> ValidationResponse:
    source = source_or_404(session, source_id)
    if not source.connector_type:
        raise HTTPException(status_code=422, detail=source.detection or "Source has no connector")
    try:
        connector = ConnectorRegistry(request.app.state.http).get(
            source.connector_type, source.detected_platform
        )
        validation = await connector.validate(source.url, source.connector_config)
    except ConnectorError as exc:
        validation_data = {
            "valid": False,
            "setup_status": "setup_required",
            "diagnostics": exc.as_dict(),
            "warnings": [],
        }
        source.setup_status = "setup_required"
        source.health_status = "setup_required" if not exc.retryable else "temporarily_failing"
    else:
        validation_data = validation.model_dump(mode="json")
        source.setup_status = validation.setup_status
        source.health_status = "healthy" if validation.valid else "setup_required"
        if validation.valid and source.last_successful_scan_at is None:
            source.next_scan_at = datetime.now(UTC)
    source.last_validation_at = datetime.now(UTC)
    source.last_validation = validation_data
    session.commit()
    session.refresh(source)
    return ValidationResponse(source=SourceRead.model_validate(source), validation=validation_data)


@router.post(
    "/sources/{source_id}/scans",
    response_model=ScanRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_scan(
    source_id: str,
    payload: ScanCreate,
    response: Response,
    session: Session = Depends(get_session),
) -> ScanRun:
    source = source_or_404(session, source_id)
    if not source.connector_type:
        raise HTTPException(
            status_code=422, detail="Source requires connector setup before scanning"
        )
    existing = unfinished_scan_for_source(session, source_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"code": "scan_already_running", "scan_id": existing.id},
        )
    scan = ScanRun(source_id=source_id, trigger=payload.trigger, progress={"phase": "queued"})
    session.add(scan)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing = unfinished_scan_for_source(session, source_id)
        raise HTTPException(
            status_code=409,
            detail={
                "code": "scan_already_running",
                "scan_id": existing.id if existing else None,
            },
        ) from exc
    session.refresh(scan)
    response.headers["Location"] = f"/api/scans/{scan.id}"
    return scan


@router.get("/scans/{scan_id}", response_model=ScanRead)
def get_scan(scan_id: str, session: Session = Depends(get_session)) -> ScanRun:
    scan = session.get(ScanRun, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan


@router.get("/scans/{scan_id}/jobs", response_model=JobsPage)
def get_scan_jobs(
    scan_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    session: Session = Depends(get_session),
) -> JobsPage:
    if not session.get(ScanRun, scan_id):
        raise HTTPException(status_code=404, detail="Scan not found")
    total = (
        session.scalar(
            select(func.count())
            .select_from(JobObservation)
            .where(JobObservation.scan_run_id == scan_id)
        )
        or 0
    )
    jobs = session.scalars(
        select(JobObservation)
        .where(JobObservation.scan_run_id == scan_id)
        .order_by(JobObservation.title, JobObservation.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return JobsPage(
        items=[JobRead.model_validate(job) for job in jobs],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/jobs", response_model=CurrentJobsPage)
def list_jobs(
    source_id: str | None = None,
    lifecycle_status: Literal["active", "possibly_closed", "closed"] | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    session: Session = Depends(get_session),
) -> CurrentJobsPage:
    filters = []
    if source_id:
        filters.append(Job.source_id == source_id)
    if lifecycle_status:
        filters.append(Job.lifecycle_status == lifecycle_status)
    total = session.scalar(select(func.count()).select_from(Job).where(*filters)) or 0
    jobs = session.scalars(
        select(Job)
        .where(*filters)
        .order_by(Job.first_discovered_at.desc(), Job.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return CurrentJobsPage(
        items=[CurrentJobRead.model_validate(job) for job in jobs],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/jobs/{job_id}", response_model=CurrentJobRead)
def get_job(job_id: str, session: Session = Depends(get_session)) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
