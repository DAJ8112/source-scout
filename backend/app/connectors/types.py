from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class DetectionResult(BaseModel):
    platform: str
    connector_type: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[str]
    config: dict[str, Any] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    valid: bool
    setup_status: str
    job_count: int | None = None
    sample_jobs: list[dict[str, Any]] = Field(default_factory=list)
    available_facets: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


@dataclass
class RawJobSummary:
    external_id: str | None
    url: str
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawJobDetails:
    external_id: str | None
    url: str
    title: str
    locations: list[str] = field(default_factory=list)
    employment_type: str | None = None
    posted_date: date | None = None
    description_html: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedJob:
    external_id: str | None
    canonical_url: str
    title: str
    locations: list[str]
    employment_type: str | None
    posted_date: date | None
    description_html: str | None
    description_text: str | None
    content_fingerprint: str
    raw_metadata: dict[str, Any]


@dataclass
class ScanOutput:
    jobs: list[NormalizedJob]
    pages_visited: int
    warnings: list[dict[str, Any]] = field(default_factory=list)
