from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.connectors.types import ValidationResult


def clean_string_list(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = value.strip()
        key = item.casefold()
        if item and key not in seen:
            cleaned.append(item)
            seen.add(key)
    return cleaned


class SourceCreate(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    url: HttpUrl

    @field_validator("company")
    @classmethod
    def clean_company(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("company cannot be blank")
        return cleaned


class SourcePatch(BaseModel):
    company: str | None = Field(default=None, min_length=1, max_length=200)
    url: HttpUrl | None = None
    connector_config: dict[str, Any] | None = None

    @field_validator("company")
    @classmethod
    def clean_company(cls, value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError("company cannot be blank or null")
        return value.strip()

    @field_validator("url", "connector_config")
    @classmethod
    def reject_null_updates(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("field cannot be null")
        return value


class ReferralContactCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    contact_url: HttpUrl | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name cannot be blank")
        return cleaned

    @field_validator("notes")
    @classmethod
    def clean_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ReferralContactPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_url: HttpUrl | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError("name cannot be blank or null")
        return value.strip()

    @field_validator("notes")
    @classmethod
    def clean_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ReferralContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    name: str
    contact_url: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company: str
    url: str
    detected_platform: str | None
    connector_type: str | None
    connector_config: dict[str, Any]
    detection: dict[str, Any]
    setup_status: str
    health_status: str
    last_validation_at: datetime | None
    last_validation: dict[str, Any]
    contacts: list[ReferralContactRead]
    created_at: datetime
    updated_at: datetime


class ValidationResponse(BaseModel):
    source: SourceRead
    validation: ValidationResult


class ScanCreate(BaseModel):
    trigger: str = "manual"

    @field_validator("trigger")
    @classmethod
    def allowed_trigger(cls, value: str) -> str:
        if value not in {"initial", "manual"}:
            raise ValueError("trigger must be initial or manual")
        return value


class ScanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    trigger: str
    status: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    progress: dict[str, Any]
    jobs_found: int
    jobs_persisted: int
    jobs_created: int
    jobs_updated: int
    jobs_missing: int
    pages_visited: int
    warnings: list[Any]
    error_code: str | None
    error_diagnostics: dict[str, Any]


class SearchProfilePatch(BaseModel):
    resume_text: str | None = Field(default=None, max_length=100_000)
    target_roles: list[str] | None = Field(default=None, max_length=30)
    adjacent_roles: list[str] | None = Field(default=None, max_length=30)
    preferred_locations: list[str] | None = Field(default=None, max_length=30)
    remote_preference: Literal[
        "no_preference", "remote_only", "remote_or_hybrid", "on_site_ok"
    ] | None = None
    employment_types: list[str] | None = Field(default=None, max_length=20)
    required_terms: list[str] | None = Field(default=None, max_length=50)
    excluded_terms: list[str] | None = Field(default=None, max_length=50)
    preference_notes: str | None = Field(default=None, max_length=10_000)

    @field_validator(
        "resume_text",
        "target_roles",
        "adjacent_roles",
        "preferred_locations",
        "remote_preference",
        "employment_types",
        "required_terms",
        "excluded_terms",
        "preference_notes",
    )
    @classmethod
    def reject_null_profile_updates(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("profile fields cannot be null")
        return value

    @field_validator(
        "target_roles",
        "adjacent_roles",
        "preferred_locations",
        "employment_types",
        "required_terms",
        "excluded_terms",
    )
    @classmethod
    def clean_lists(cls, value: list[str] | None) -> list[str] | None:
        return clean_string_list(value) if value is not None else None


class SearchProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    resume_text: str
    resume_filename: str | None
    target_roles: list[str]
    adjacent_roles: list[str]
    preferred_locations: list[str]
    remote_preference: str
    employment_types: list[str]
    required_terms: list[str]
    excluded_terms: list[str]
    preference_notes: str
    version: int
    created_at: datetime
    updated_at: datetime


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scan_run_id: str
    source_id: str
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
    observed_at: datetime


class JobsPage(BaseModel):
    items: list[JobRead]
    page: int
    page_size: int
    total: int


class CurrentJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
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
    lifecycle_status: str
    consecutive_successful_absences: int
    initial_import: bool
    first_discovered_at: datetime
    last_observed_at: datetime
    created_at: datetime
    updated_at: datetime


class CurrentJobsPage(BaseModel):
    items: list[CurrentJobRead]
    page: int
    page_size: int
    total: int


class MatchResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    profile_id: str
    profile_version: int
    job_content_fingerprint: str
    matcher_version: str
    classification: str
    score: int
    role_score: int
    resume_score: int
    hard_constraint_pass: bool
    hard_constraint_reasons: list[str]
    evidence: list[str]
    gaps: list[str]
    provider: str
    provider_status: str
    model: str | None
    prompt_version: str
    request_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    error: str | None
    evaluated_at: datetime


class FeedItem(BaseModel):
    job: CurrentJobRead
    company: str
    contacts: list[ReferralContactRead]
    match: MatchResultRead | None


class FeedPage(BaseModel):
    items: list[FeedItem]
    total: int
    profile_ready: bool
    provider_configured: bool


class RematchResponse(BaseModel):
    evaluated: int
    cached: int
    ai_succeeded: int
    local_fallbacks: int
    failed: int
