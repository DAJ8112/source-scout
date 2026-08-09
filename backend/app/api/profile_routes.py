from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.db import get_session
from app.models import CareersSource, Job, MatchResult
from app.schemas import (
    CurrentJobRead,
    FeedItem,
    FeedPage,
    MatchResultRead,
    RematchResponse,
    SearchProfilePatch,
    SearchProfileRead,
)
from app.services.matching import MATCHER_VERSION, match_jobs, profile_ready
from app.services.profiles import extract_pdf_text, get_or_create_profile, update_profile

router = APIRouter(prefix="/api")


@router.get("/profile", response_model=SearchProfileRead)
def get_profile(session: Session = Depends(get_session)):
    return get_or_create_profile(session)


@router.patch("/profile", response_model=SearchProfileRead)
def patch_profile(
    payload: SearchProfilePatch,
    session: Session = Depends(get_session),
):
    profile = get_or_create_profile(session)
    update_profile(session, profile, payload.model_dump(exclude_unset=True))
    return profile


@router.post("/profile/resume", response_model=SearchProfileRead)
async def upload_resume(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    filename = Path(file.filename or "resume.pdf").name[:300]
    if file.content_type != "application/pdf" and not filename.casefold().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Resume must be a PDF")
    try:
        data = await file.read(settings.max_resume_upload_bytes + 1)
    finally:
        await file.close()
    if len(data) > settings.max_resume_upload_bytes:
        raise HTTPException(status_code=413, detail="Resume PDF exceeds the 10 MB limit")
    try:
        resume_text = await asyncio.to_thread(extract_pdf_text, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    profile = get_or_create_profile(session)
    update_profile(
        session,
        profile,
        {"resume_text": resume_text, "resume_filename": filename},
    )
    return profile


@router.post(
    "/profile/rematch",
    response_model=RematchResponse,
    status_code=status.HTTP_200_OK,
)
async def rematch_profile(request: Request, session: Session = Depends(get_session)):
    profile = get_or_create_profile(session)
    if not profile_ready(profile):
        raise HTTPException(
            status_code=422,
            detail="Add resume text and at least one target role before matching",
        )
    summary = await match_jobs(session, request.app.state.matcher)
    session.commit()
    return RematchResponse(**summary.__dict__)


@router.get("/feed", response_model=FeedPage)
def get_feed(
    request: Request,
    classification: Literal["strong", "possible", "irrelevant", "unmatched"] | None = None,
    session: Session = Depends(get_session),
) -> FeedPage:
    profile = get_or_create_profile(session)
    jobs = list(
        session.scalars(
            select(Job)
            .where(Job.lifecycle_status == "active")
            .options(selectinload(Job.source).selectinload(CareersSource.contacts))
        )
    )
    matches = list(
        session.scalars(
            select(MatchResult).where(
                MatchResult.profile_id == profile.id,
                MatchResult.profile_version == profile.version,
                MatchResult.matcher_version == MATCHER_VERSION,
            )
        )
    )
    fingerprint_by_job = {job.id: job.content_fingerprint for job in jobs}
    match_by_job = {
        match.job_id: match
        for match in matches
        if fingerprint_by_job.get(match.job_id) == match.job_content_fingerprint
    }
    items = []
    for job in jobs:
        match = match_by_job.get(job.id)
        item_class = match.classification if match else "unmatched"
        if classification and item_class != classification:
            continue
        items.append(
            FeedItem(
                job=CurrentJobRead.model_validate(job),
                company=job.source.company,
                contacts=job.source.contacts,
                match=MatchResultRead.model_validate(match) if match else None,
            )
        )
    priority = {"strong": 0, "possible": 1, "irrelevant": 2, "unmatched": 3}
    items.sort(
        key=lambda item: (
            priority[item.match.classification if item.match else "unmatched"],
            -(item.match.score if item.match else -1),
            -item.job.first_discovered_at.timestamp(),
        )
    )
    matcher = request.app.state.matcher
    return FeedPage(
        items=items,
        total=len(items),
        profile_ready=profile_ready(profile),
        provider_configured=matcher.client is not None,
    )
