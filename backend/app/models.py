from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return str(uuid4())


def now_utc() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class CareersSource(Base):
    __tablename__ = "careers_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text, unique=True)
    detected_platform: Mapped[str | None] = mapped_column(String(50))
    connector_type: Mapped[str | None] = mapped_column(String(50))
    connector_config: Mapped[dict] = mapped_column(JSON, default=dict)
    detection: Mapped[dict] = mapped_column(JSON, default=dict)
    setup_status: Mapped[str] = mapped_column(String(30), default="unvalidated")
    health_status: Mapped[str] = mapped_column(String(30), default="unknown")
    last_validation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_validation: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    scans: Mapped[list[ScanRun]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )
    jobs: Mapped[list[Job]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )
    contacts: Mapped[list[ReferralContact]] = relationship(
        back_populates="source", cascade="all, delete-orphan", order_by="ReferralContact.name"
    )


class ReferralContact(Base):
    __tablename__ = "referral_contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("careers_sources.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    contact_url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    source: Mapped[CareersSource] = relationship(back_populates="contacts")

    __table_args__ = (Index("ix_contact_source", "source_id"),)


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("careers_sources.id", ondelete="CASCADE"))
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(30), default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    jobs_found: Mapped[int] = mapped_column(Integer, default=0)
    jobs_persisted: Mapped[int] = mapped_column(Integer, default=0)
    jobs_created: Mapped[int] = mapped_column(Integer, default=0)
    jobs_updated: Mapped[int] = mapped_column(Integer, default=0)
    jobs_missing: Mapped[int] = mapped_column(Integer, default=0)
    pages_visited: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_diagnostics: Mapped[dict] = mapped_column(JSON, default=dict)

    source: Mapped[CareersSource] = relationship(back_populates="scans")
    jobs: Mapped[list[JobObservation]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_scan_source_status", "source_id", "status"),)


class SearchProfile(Base):
    __tablename__ = "search_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resume_text: Mapped[str] = mapped_column(Text, default="")
    resume_filename: Mapped[str | None] = mapped_column(String(300))
    target_roles: Mapped[list] = mapped_column(JSON, default=list)
    adjacent_roles: Mapped[list] = mapped_column(JSON, default=list)
    preferred_locations: Mapped[list] = mapped_column(JSON, default=list)
    remote_preference: Mapped[str] = mapped_column(String(30), default="no_preference")
    employment_types: Mapped[list] = mapped_column(JSON, default=list)
    required_terms: Mapped[list] = mapped_column(JSON, default=list)
    excluded_terms: Mapped[list] = mapped_column(JSON, default=list)
    preference_notes: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    match_results: Mapped[list[MatchResult]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("careers_sources.id", ondelete="CASCADE"))
    identity_key: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(300))
    canonical_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    locations: Mapped[list] = mapped_column(JSON, default=list)
    employment_type: Mapped[str | None] = mapped_column(String(200))
    posted_date: Mapped[date | None] = mapped_column(Date)
    description_html: Mapped[str | None] = mapped_column(Text)
    description_text: Mapped[str | None] = mapped_column(Text)
    content_fingerprint: Mapped[str] = mapped_column(String(64))
    raw_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    lifecycle_status: Mapped[str] = mapped_column(String(30), default="active")
    consecutive_successful_absences: Mapped[int] = mapped_column(Integer, default=0)
    initial_import: Mapped[bool] = mapped_column(default=False)
    first_discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    source: Mapped[CareersSource] = relationship(back_populates="jobs")
    observations: Mapped[list[JobObservation]] = relationship(back_populates="job")
    match_results: Mapped[list[MatchResult]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("source_id", "identity_key", name="uq_job_source_identity"),
        Index("ix_job_source_lifecycle", "source_id", "lifecycle_status"),
    )


class MatchResult(Base):
    __tablename__ = "match_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    profile_id: Mapped[str] = mapped_column(ForeignKey("search_profiles.id", ondelete="CASCADE"))
    profile_version: Mapped[int] = mapped_column(Integer)
    job_content_fingerprint: Mapped[str] = mapped_column(String(64))
    matcher_version: Mapped[str] = mapped_column(String(50))
    classification: Mapped[str] = mapped_column(String(20))
    score: Mapped[int] = mapped_column(Integer)
    role_score: Mapped[int] = mapped_column(Integer)
    resume_score: Mapped[int] = mapped_column(Integer)
    hard_constraint_pass: Mapped[bool] = mapped_column(default=True)
    hard_constraint_reasons: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    gaps: Mapped[list] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(30))
    provider_status: Mapped[str] = mapped_column(String(30))
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    request_id: Mapped[str | None] = mapped_column(String(200))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    job: Mapped[Job] = relationship(back_populates="match_results")
    profile: Mapped[SearchProfile] = relationship(back_populates="match_results")

    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "profile_id",
            "profile_version",
            "job_content_fingerprint",
            "matcher_version",
            name="uq_match_cache_key",
        ),
        Index("ix_match_profile_class", "profile_id", "profile_version", "classification"),
        Index("ix_match_job", "job_id"),
    )


class JobObservation(Base):
    __tablename__ = "job_observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scan_run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id", ondelete="CASCADE"))
    source_id: Mapped[str] = mapped_column(ForeignKey("careers_sources.id", ondelete="CASCADE"))
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    external_id: Mapped[str | None] = mapped_column(String(300))
    canonical_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    locations: Mapped[list] = mapped_column(JSON, default=list)
    employment_type: Mapped[str | None] = mapped_column(String(200))
    posted_date: Mapped[date | None] = mapped_column(Date)
    description_html: Mapped[str | None] = mapped_column(Text)
    description_text: Mapped[str | None] = mapped_column(Text)
    content_fingerprint: Mapped[str] = mapped_column(String(64))
    raw_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    scan: Mapped[ScanRun] = relationship(back_populates="jobs")
    job: Mapped[Job | None] = relationship(back_populates="observations")

    __table_args__ = (
        UniqueConstraint("scan_run_id", "canonical_url", name="uq_observation_scan_url"),
        Index("ix_observation_scan", "scan_run_id"),
        Index("ix_observation_job", "job_id"),
        Index("ix_observation_source_external", "source_id", "external_id"),
    )
