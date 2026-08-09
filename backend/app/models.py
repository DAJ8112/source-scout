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

    __table_args__ = (
        UniqueConstraint("source_id", "identity_key", name="uq_job_source_identity"),
        Index("ix_job_source_lifecycle", "source_id", "lifecycle_status"),
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
