from __future__ import annotations

import re
from html import escape
from typing import Any
from urllib.parse import urlsplit

from app.connectors.base import CareersConnector
from app.connectors.errors import ConnectorError
from app.connectors.http import SafeHttpClient
from app.connectors.normalize import normalized_job, parse_date
from app.connectors.safety import canonicalize_url
from app.connectors.types import (
    DetectionResult,
    NormalizedJob,
    RawJobDetails,
    RawJobSummary,
    ValidationResult,
)


def _description(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value if re.search(r"<\s*[a-zA-Z][^>]*>", value) else f"<p>{escape(value)}</p>"


class IcimsJibeConnector(CareersConnector):
    platform = "icims_jibe"
    connector_type = "icims_jibe_api"

    def __init__(self, http: SafeHttpClient) -> None:
        self.http = http

    @staticmethod
    def api_url(url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}/api/jobs"

    async def detect(self, url: str) -> DetectionResult:
        return DetectionResult(
            platform=self.platform,
            connector_type=self.connector_type,
            confidence=0.99,
            evidence=["Official Rivian careers hostname", "Jibe public /api/jobs endpoint"],
            config={"api_url": self.api_url(url), "page_size": 100},
        )

    async def _page(self, api_url: str, *, limit: int, offset: int) -> dict[str, Any]:
        response = await self.http.request(
            "GET", api_url, params={"limit": limit, "offset": offset}
        )
        try:
            body = response.json()
        except ValueError as exc:
            raise ConnectorError(
                "malformed_response",
                "iCIMS/Jibe returned non-JSON content",
                diagnostics={"url": api_url},
            ) from exc
        if not isinstance(body, dict) or not isinstance(body.get("jobs"), list):
            raise ConnectorError(
                "malformed_response",
                "iCIMS/Jibe response did not contain a jobs list",
                diagnostics={"keys": list(body) if isinstance(body, dict) else []},
            )
        return body

    @staticmethod
    def _summary(item: Any, source_url: str) -> RawJobSummary | None:
        data = item.get("data") if isinstance(item, dict) else None
        if not isinstance(data, dict):
            return None
        external_id = data.get("req_id") or data.get("id")
        canonical = (data.get("meta_data") or {}).get("canonical_url")
        if not external_id or not canonical:
            return None
        canonical_url = canonicalize_url(str(canonical), source_url)
        if urlsplit(canonical_url).hostname != urlsplit(source_url).hostname:
            return None
        return RawJobSummary(
            external_id=str(external_id),
            url=canonical_url,
            title=data.get("title"),
            metadata={"data": data},
        )

    @staticmethod
    def _facets(body: dict[str, Any]) -> list[dict[str, Any]]:
        filters = body.get("filter")
        if not isinstance(filters, dict):
            return []
        return [
            {"facet_parameter": str(key), "values": value}
            for key, value in filters.items()
            if isinstance(value, list)
        ]

    async def validate(self, url: str, config: dict[str, Any]) -> ValidationResult:
        api_url = config.get("api_url") or self.api_url(url)
        allowed, warning = await self.http.robots_allowed(api_url)
        if not allowed:
            return ValidationResult(
                valid=False, setup_status="setup_required", diagnostics=warning or {}
            )
        body = await self._page(api_url, limit=5, offset=0)
        summaries = [
            summary
            for item in body["jobs"]
            if (summary := self._summary(item, url)) is not None
        ]
        total = int(body.get("totalCount") or body.get("count") or 0)
        warnings = [warning] if warning else []
        if total <= 0 or not summaries:
            return ValidationResult(
                valid=False,
                setup_status="setup_required",
                job_count=total,
                warnings=warnings,
                diagnostics={
                    "code": "zero_results",
                    "message": "The iCIMS/Jibe API returned no usable jobs",
                },
            )
        return ValidationResult(
            valid=True,
            setup_status="ready",
            job_count=total,
            sample_jobs=[{"title": item.title, "url": item.url} for item in summaries[:5]],
            available_facets=self._facets(body),
            warnings=warnings,
        )

    async def list_jobs(
        self, url: str, config: dict[str, Any]
    ) -> tuple[list[RawJobSummary], int, list[dict]]:
        api_url = config.get("api_url") or self.api_url(url)
        page_size = int(config.get("page_size", 100))
        offset = 0
        pages = 0
        jobs: dict[str, RawJobSummary] = {}
        signatures: set[tuple[str, ...]] = set()
        while True:
            body = await self._page(api_url, limit=page_size, offset=offset)
            pages += 1
            page = [
                summary
                for item in body["jobs"]
                if (summary := self._summary(item, url)) is not None
            ]
            signature = tuple(item.external_id or item.url for item in page)
            if signature in signatures and page:
                raise ConnectorError(
                    "pagination_loop",
                    "iCIMS/Jibe returned a repeated API page",
                    diagnostics={"offset": offset},
                )
            signatures.add(signature)
            jobs.update({item.external_id or item.url: item for item in page})
            total = int(body.get("totalCount") or body.get("count") or len(jobs))
            if not page or offset + len(body["jobs"]) >= total:
                break
            offset += len(body["jobs"])
        return list(jobs.values()), pages, []

    async def get_job_details(
        self, summary: RawJobSummary, config: dict[str, Any]
    ) -> RawJobDetails:
        data = summary.metadata.get("data")
        if not isinstance(data, dict):
            raise ConnectorError(
                "malformed_detail", "iCIMS/Jibe summary did not retain complete job data"
            )
        location = data.get("full_location")
        locations = [str(location)] if location else []
        return RawJobDetails(
            external_id=summary.external_id,
            url=summary.url,
            title=data.get("title") or summary.title or "Untitled role",
            locations=locations,
            employment_type=data.get("employment_type"),
            posted_date=parse_date(data.get("posted_date")),
            description_html=_description(data.get("description")),
            metadata={
                "source": self.platform,
                "identifier": summary.external_id,
                "department": data.get("category"),
                "date_modified": data.get("update_date"),
            },
        )

    def normalize(self, details: RawJobDetails) -> NormalizedJob:
        return normalized_job(details)
