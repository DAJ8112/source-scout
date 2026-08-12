from __future__ import annotations

from datetime import date
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
    ScanOutput,
    ValidationResult,
)

CVS_FACETS = [
    {
        "facet_parameter": "timeType",
        "label": "Full time",
        "id": "1aea6da227e21005504339b6b1770001",
    },
    {
        "facet_parameter": "workerSubType",
        "label": "Regular",
        "id": "183bb31d97231001005066125c530001",
    },
    {
        "facet_parameter": "jobFamilyGroup",
        "label": "Technology",
        "id": "e65dbadf6a50100168ed86fe4cf50001",
    },
    {
        "facet_parameter": "jobFamilyGroup",
        "label": "Data and Analytics",
        "id": "e65dbadf6a50100168ed7f2a693c0001",
    },
]


class WorkdayConnector(CareersConnector):
    platform = "workday"
    connector_type = "workday_cxs"

    def __init__(self, http: SafeHttpClient) -> None:
        self.http = http

    @staticmethod
    def coordinates(url: str) -> tuple[str, str, str]:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        path_parts = [part for part in parts.path.split("/") if part]
        if ".myworkdayjobs.com" in host:
            tenant = host.split(".")[0]
            site = path_parts[0] if path_parts else ""
        elif ".myworkdaysite.com" in host:
            if len(path_parts) < 3 or path_parts[0].casefold() != "recruiting":
                raise ConnectorError(
                    "invalid_workday_url",
                    "Workday recruiting URL must include /recruiting/{tenant}/{site}",
                )
            tenant, site = path_parts[1:3]
        else:
            raise ConnectorError("invalid_workday_url", "URL is not a Workday careers site")
        if not site:
            raise ConnectorError("invalid_workday_url", "Workday URL is missing the site name")
        origin = f"{parts.scheme}://{parts.netloc}"
        return tenant, site, origin

    @classmethod
    def api_url(cls, url: str) -> str:
        tenant, site, origin = cls.coordinates(url)
        return f"{origin}/wday/cxs/{tenant}/{site}/jobs"

    async def detect(self, url: str) -> DetectionResult:
        tenant, site, _ = self.coordinates(url)
        config: dict[str, Any] = {"tenant": tenant, "site": site, "selected_facets": []}
        if tenant == "cvshealth" and site == "CVS_Health_Careers":
            config["selected_facets"] = CVS_FACETS
        return DetectionResult(
            platform=self.platform,
            connector_type=self.connector_type,
            confidence=0.99,
            evidence=[
                "Hostname is an official myworkdayjobs.com tenant",
                "CXS coordinates derived from URL",
            ],
            config=config,
        )

    @staticmethod
    def payload(config: dict[str, Any], *, offset: int = 0, limit: int = 20) -> dict:
        applied: dict[str, list[str]] = {}
        for facet in config.get("selected_facets", []):
            applied.setdefault(facet["facet_parameter"], []).append(facet["id"])
        return {"appliedFacets": applied, "limit": limit, "offset": offset, "searchText": ""}

    async def _post(self, url: str, payload: dict) -> dict:
        response = await self.http.request("POST", self.api_url(url), json=payload)
        try:
            body = response.json()
        except ValueError as exc:
            raise ConnectorError(
                "malformed_response",
                "Workday CXS returned non-JSON content",
                diagnostics={"url": self.api_url(url)},
            ) from exc
        if not isinstance(body, dict) or "jobPostings" not in body:
            raise ConnectorError(
                "malformed_response",
                "Workday CXS response did not contain jobPostings",
                diagnostics={"keys": list(body) if isinstance(body, dict) else []},
            )
        return body

    @staticmethod
    def _facets(body: dict) -> list[dict[str, Any]]:
        result = []
        for group in body.get("facets", []):
            parameter = group.get("facetParameter") or group.get("id")
            values = [
                {
                    "id": value.get("id"),
                    "label": value.get("descriptor") or value.get("label"),
                    "count": value.get("count"),
                }
                for value in group.get("values", [])
            ]
            result.append(
                {
                    "facet_parameter": parameter,
                    "label": group.get("descriptor") or group.get("label"),
                    "values": values,
                }
            )
        return result

    @staticmethod
    def _facet_drift(selected: list[dict], available: list[dict]) -> list[dict]:
        by_parameter = {group["facet_parameter"]: group.get("values", []) for group in available}
        drift = []
        for expected in selected:
            values = by_parameter.get(expected["facet_parameter"], [])
            match = next((item for item in values if item.get("label") == expected["label"]), None)
            if not match:
                drift.append({**expected, "reason": "label_missing"})
            elif match.get("id") != expected["id"]:
                drift.append({**expected, "reason": "id_changed", "current_id": match.get("id")})
        return drift

    async def validate(self, url: str, config: dict[str, Any]) -> ValidationResult:
        allowed, robots_warning = await self.http.robots_allowed(self.api_url(url))
        if not allowed:
            return ValidationResult(
                valid=False, setup_status="setup_required", diagnostics=robots_warning or {}
            )
        unfiltered = await self._post(
            url, {"appliedFacets": {}, "limit": 5, "offset": 0, "searchText": ""}
        )
        available = self._facets(unfiltered)
        drift = self._facet_drift(config.get("selected_facets", []), available)
        warnings = [robots_warning] if robots_warning else []
        if drift:
            return ValidationResult(
                valid=False,
                setup_status="setup_required",
                available_facets=available,
                warnings=warnings,
                diagnostics={
                    "code": "facet_drift",
                    "message": "Saved Workday facet IDs no longer match their labels; review facet selection",
                    "drift": drift,
                },
            )
        filtered = await self._post(url, self.payload(config, limit=5))
        samples = [
            {"title": item.get("title"), "url": canonicalize_url(item.get("externalPath", ""), url)}
            for item in filtered.get("jobPostings", [])[:5]
        ]
        total = int(filtered.get("total", len(samples)))
        if total == 0:
            warnings.append(
                {"code": "zero_results", "message": "Validated facet selection returned zero jobs"}
            )
        return ValidationResult(
            valid=total > 0,
            setup_status="ready" if total > 0 else "setup_required",
            job_count=total,
            sample_jobs=samples,
            available_facets=available,
            warnings=warnings,
            diagnostics={} if total > 0 else {"code": "zero_results"},
        )

    async def list_jobs(
        self, url: str, config: dict[str, Any]
    ) -> tuple[list[RawJobSummary], int, list[dict]]:
        validation = await self.validate(url, config)
        if not validation.valid:
            raise ConnectorError(
                validation.diagnostics.get("code", "invalid_configuration"),
                validation.diagnostics.get("message", "Workday source requires setup"),
                diagnostics=validation.diagnostics,
            )
        offset, limit, pages = 0, 20, 0
        seen_pages: set[tuple[str | None, ...]] = set()
        summaries: list[RawJobSummary] = []
        while True:
            body = await self._post(url, self.payload(config, offset=offset, limit=limit))
            pages += 1
            postings = body.get("jobPostings", [])
            signature = tuple(item.get("externalPath") for item in postings)
            if signature in seen_pages and postings:
                raise ConnectorError(
                    "pagination_loop",
                    "Workday returned a previously visited result page",
                    diagnostics={"offset": offset},
                )
            seen_pages.add(signature)
            for item in postings:
                path = item.get("externalPath")
                if not path:
                    continue
                summaries.append(
                    RawJobSummary(
                        external_id=item.get("bulletFields", [None])[0]
                        if item.get("bulletFields")
                        else None,
                        url=canonicalize_url(path, url),
                        title=item.get("title"),
                        metadata={"listing": item},
                    )
                )
            offset += len(postings)
            total = int(body.get("total", offset))
            if not postings or offset >= total:
                break
        return summaries, pages, validation.warnings

    async def get_job_details(
        self, summary: RawJobSummary, config: dict[str, Any]
    ) -> RawJobDetails:
        source_url = config.get("source_url")
        if not source_url:
            parts = urlsplit(summary.url)
            site = config["site"]
            source_url = f"{parts.scheme}://{parts.netloc}/{site}"
        api_root = self.api_url(source_url).removesuffix("/jobs")
        external_path = urlsplit(summary.url).path
        response = await self.http.request("GET", f"{api_root}{external_path}")
        try:
            info = response.json().get("jobPostingInfo", {})
        except ValueError as exc:
            raise ConnectorError(
                "malformed_response", "Workday detail response was not JSON"
            ) from exc
        if not info.get("title"):
            raise ConnectorError(
                "missing_job_detail",
                "Workday detail response lacks a title",
                diagnostics={"url": summary.url},
            )
        locations = info.get("additionalLocations") or []
        if info.get("location"):
            locations.insert(0, info["location"])
        posted: date | None = parse_date(info.get("startDate") or info.get("postedOn"))
        return RawJobDetails(
            external_id=info.get("jobReqId") or summary.external_id,
            url=info.get("externalUrl") or summary.url,
            title=info["title"],
            locations=locations,
            employment_type=info.get("timeType"),
            posted_date=posted,
            description_html=info.get("jobDescription"),
            metadata={"source": "workday_cxs", "identifier": info.get("jobReqId")},
        )

    def normalize(self, details: RawJobDetails) -> NormalizedJob:
        return normalized_job(details)

    async def scan(self, url: str, config: dict[str, Any]) -> ScanOutput:
        config = {**config, "source_url": url}
        return await super().scan(url, config)
