from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.db import get_session
from app.models import CareersSource, Job, JobUserState, MatchResult
from app.schemas import (
    CurrentJobRead,
    FeedItem,
    FeedPage,
    JobUserStatePatch,
    JobUserStateRead,
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


@router.patch("/jobs/{job_id}/state", response_model=JobUserStateRead)
def patch_job_state(
    job_id: str,
    payload: JobUserStatePatch,
    session: Session = Depends(get_session),
):
    if not session.get(Job, job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    user_state = session.scalar(select(JobUserState).where(JobUserState.job_id == job_id))
    if not user_state:
        user_state = JobUserState(job_id=job_id)
        session.add(user_state)
    now = datetime.now(UTC)
    if "seen" in payload.model_fields_set:
        user_state.seen_at = now if payload.seen else None
    if "dismissed" in payload.model_fields_set:
        user_state.dismissed_at = now if payload.dismissed else None
    session.commit()
    session.refresh(user_state)
    return user_state


@router.get("/feed", response_model=FeedPage)
def get_feed(
    request: Request,
    classification: Literal["strong", "possible", "irrelevant", "unmatched"] | None = None,
    include_dismissed: bool = False,
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
    states = (
        list(
            session.scalars(
                select(JobUserState).where(JobUserState.job_id.in_(fingerprint_by_job))
            )
        )
        if fingerprint_by_job
        else []
    )
    state_by_job = {state.job_id: state for state in states}
    unseen_strong = 0
    unseen_possible = 0
    dismissed_total = 0
    items = []
    for job in jobs:
        match = match_by_job.get(job.id)
        user_state = state_by_job.get(job.id)
        item_class = match.classification if match else "unmatched"
        dismissed = bool(user_state and user_state.dismissed_at)
        if dismissed:
            dismissed_total += 1
        elif not user_state or not user_state.seen_at:
            if item_class == "strong":
                unseen_strong += 1
            elif item_class == "possible":
                unseen_possible += 1
        if dismissed and not include_dismissed:
            continue
        if classification and item_class != classification:
            continue
        items.append(
            FeedItem(
                job=CurrentJobRead.model_validate(job),
                company=job.source.company,
                contacts=job.source.contacts,
                match=MatchResultRead.model_validate(match) if match else None,
                state=JobUserStateRead.model_validate(user_state) if user_state else None,
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
        unseen_strong=unseen_strong,
        unseen_possible=unseen_possible,
        dismissed_total=dismissed_total,
    )
