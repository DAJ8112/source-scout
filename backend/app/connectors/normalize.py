import hashlib
import json
import re
from datetime import date, datetime
from html import unescape
from typing import Any

from bs4 import BeautifulSoup

from app.connectors.safety import canonicalize_url
from app.connectors.types import NormalizedJob, RawJobDetails


def clean_text(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"\s+", " ", unescape(value)).strip() or None


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    return clean_text(BeautifulSoup(value, "html.parser").get_text(" "))


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def normalized_job(details: RawJobDetails) -> NormalizedJob:
    title = clean_text(details.title) or "Untitled role"
    locations = sorted({item for raw in details.locations if (item := clean_text(raw))})
    description_text = html_to_text(details.description_html)
    canonical_url = canonicalize_url(details.url, keep_query=True)
    identity = {
        "title": title,
        "locations": locations,
        "employment_type": clean_text(details.employment_type),
        "posted_date": details.posted_date.isoformat() if details.posted_date else None,
        "description_text": description_text,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    metadata = {
        key: value
        for key, value in details.metadata.items()
        if key in {"source", "identifier", "department", "workplace_type", "date_modified"}
        and isinstance(value, (str, int, float, bool, list, dict, type(None)))
    }
    return NormalizedJob(
        external_id=clean_text(details.external_id),
        canonical_url=canonical_url,
        title=title,
        locations=locations,
        employment_type=clean_text(details.employment_type),
        posted_date=details.posted_date,
        description_html=details.description_html,
        description_text=description_text,
        content_fingerprint=fingerprint,
        raw_metadata=metadata,
    )
