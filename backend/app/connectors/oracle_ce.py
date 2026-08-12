from __future__ import annotations

import re
from html import escape
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

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


def _oracle_host(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host.endswith(".oraclecloud.com")


def _render_location(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, dict):
        return None
    nested = value.get("Address") or value.get("address")
    if isinstance(nested, dict):
        value = {**value, **nested}
    fields = (
        "LocationName",
        "Name",
        "AddressLine1",
        "TownOrCity",
        "City",
        "Region2",
        "State",
        "PostalCode",
        "Country",
    )
    parts: list[str] = []
    for key in fields:
        item = value.get(key)
        if item and str(item) not in parts:
            parts.append(str(item))
    return ", ".join(parts) or None


def _description_html(body: dict[str, Any]) -> str | None:
    sections = []
    for heading, key in (
        (None, "ExternalDescriptionStr"),
        ("Responsibilities", "ExternalResponsibilitiesStr"),
        ("Qualifications", "ExternalQualificationsStr"),
    ):
        value = body.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        section = (
            value
            if re.search(r"<\s*[a-zA-Z][^>]*>", value)
            else f"<p>{escape(value)}</p>"
        )
        sections.append(f"<h2>{heading}</h2>{section}" if heading else section)
    return "".join(sections) or None


class OracleCeConnector(CareersConnector):
    platform = "oracle_ce"
    connector_type = "oracle_ce_rest"

    def __init__(self, http: SafeHttpClient) -> None:
        self.http = http

    async def _discover(self, url: str) -> dict[str, Any]:
        allowed, warning = await self.http.robots_allowed(url)
        if not allowed:
            raise ConnectorError(
                "robots_disallowed",
                "robots.txt disallows the Oracle Candidate Experience page",
                diagnostics=warning or {"url": url},
            )
        response = await self.http.request("GET", url)
        base = BeautifulSoup(response.text, "html.parser").select_one(
            "base[data-apibaseurl][data-sitenumber]"
        )
        if not base:
            raise ConnectorError(
                "oracle_configuration_missing",
                "Oracle Candidate Experience page did not expose API coordinates",
                diagnostics={"url": url},
            )
        api_base = canonicalize_url(str(base.get("data-apibaseurl")))
        site_number = str(base.get("data-sitenumber") or "").strip()
        if not _oracle_host(api_base) or not site_number:
            raise ConnectorError(
                "unsafe_oracle_configuration",
                "Oracle API coordinates were missing or outside oraclecloud.com",
                diagnostics={"api_base_url": api_base, "site_number": site_number},
            )
        return {
            "api_base_url": api_base.rstrip("/"),
            "site_number": site_number,
            "public_url": canonicalize_url(url, keep_query=True),
            "page_size": 100,
        }

    async def _config(self, url: str, config: dict[str, Any]) -> dict[str, Any]:
        if config.get("api_base_url") and config.get("site_number"):
            api_base = canonicalize_url(str(config["api_base_url"]))
            site_number = str(config["site_number"])
            public_url = str(config.get("public_url") or url)
            if not _oracle_host(api_base) or not re.fullmatch(r"[A-Za-z0-9_]+", site_number):
                raise ConnectorError(
                    "unsafe_oracle_configuration",
                    "Configured Oracle API host or site number is unsafe",
                    diagnostics={"api_base_url": api_base, "site_number": site_number},
                )
            if urlsplit(public_url).hostname != urlsplit(url).hostname:
                raise ConnectorError(
                    "unsafe_oracle_configuration",
                    "Configured Oracle public URL does not match the source host",
                    diagnostics={"public_url": public_url},
                )
            return {
                **config,
                "api_base_url": api_base.rstrip("/"),
                "site_number": site_number,
                "public_url": canonicalize_url(public_url, keep_query=True),
            }
        return {**config, **(await self._discover(url))}

    async def detect(self, url: str) -> DetectionResult:
        config = await self._discover(url)
        return DetectionResult(
            platform=self.platform,
            connector_type=self.connector_type,
            confidence=0.99,
            evidence=[
                "Oracle Candidate Experience page",
                "data-apibaseurl and data-sitenumber coordinates discovered",
            ],
            config=config,
        )

    @staticmethod
    def _endpoint(config: dict[str, Any], resource: str) -> str:
        return f"{config['api_base_url']}/hcmRestApi/resources/latest/{resource}"

    async def _listing_page(
        self, config: dict[str, Any], *, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
        response = await self.http.request(
            "GET",
            self._endpoint(config, "recruitingCEJobRequisitions"),
            params={
                "finder": (
                    f"findReqs;siteNumber={config['site_number']},limit={limit},offset={offset}"
                ),
                "onlyData": "true",
                "expand": "requisitionList",
            },
        )
        try:
            body = response.json()
        except ValueError as exc:
            raise ConnectorError(
                "malformed_response", "Oracle CE listing returned non-JSON content"
            ) from exc
        items = body.get("items") if isinstance(body, dict) else None
        container = items[0] if isinstance(items, list) and items else None
        jobs = container.get("requisitionList") if isinstance(container, dict) else None
        if not isinstance(jobs, list):
            raise ConnectorError(
                "malformed_response",
                "Oracle CE response did not contain requisitionList",
                diagnostics={"keys": list(body) if isinstance(body, dict) else []},
            )
        total = int(container.get("TotalJobsCount") or len(jobs))
        facets = container.get("facets") or container.get("Facets") or []
        return jobs, total, facets if isinstance(facets, list) else []

    @staticmethod
    def _public_detail(public_url: str, job_id: str) -> str:
        parts = urlsplit(public_url)
        path = parts.path.rstrip("/")
        if path.endswith("/jobs"):
            path = path[:-5]
        return canonicalize_url(
            urlunsplit((parts.scheme, parts.netloc, f"{path}/job/{job_id}", "", ""))
        )

    @classmethod
    def _summary(cls, item: Any, config: dict[str, Any]) -> RawJobSummary | None:
        if not isinstance(item, dict):
            return None
        identifier = item.get("Id") or item.get("id")
        title = item.get("Title") or item.get("title")
        if not identifier or not title:
            return None
        public_url = config.get("public_url") or ""
        return RawJobSummary(
            external_id=str(identifier),
            url=cls._public_detail(public_url, str(identifier)),
            title=str(title),
            metadata={"listing": item, "oracle_config": config},
        )

    async def validate(self, url: str, config: dict[str, Any]) -> ValidationResult:
        cfg = await self._config(url, config)
        endpoint = self._endpoint(cfg, "recruitingCEJobRequisitions")
        allowed, warning = await self.http.robots_allowed(endpoint)
        if not allowed:
            return ValidationResult(
                valid=False, setup_status="setup_required", diagnostics=warning or {}
            )
        jobs, total, facets = await self._listing_page(cfg, limit=5, offset=0)
        summaries = [
            summary for item in jobs if (summary := self._summary(item, cfg)) is not None
        ]
        warnings = [warning] if warning else []
        if total <= 0 or not summaries:
            return ValidationResult(
                valid=False,
                setup_status="setup_required",
                job_count=total,
                warnings=warnings,
                diagnostics={
                    "code": "zero_results",
                    "message": "Oracle CE returned no usable requisitions",
                },
            )
        return ValidationResult(
            valid=True,
            setup_status="ready",
            job_count=total,
            sample_jobs=[{"title": item.title, "url": item.url} for item in summaries[:5]],
            available_facets=facets,
            warnings=warnings,
        )

    async def list_jobs(
        self, url: str, config: dict[str, Any]
    ) -> tuple[list[RawJobSummary], int, list[dict]]:
        cfg = await self._config(url, config)
        page_size = int(cfg.get("page_size", 100))
        offset = 0
        pages = 0
        jobs: dict[str, RawJobSummary] = {}
        signatures: set[tuple[str, ...]] = set()
        while True:
            raw_jobs, total, _ = await self._listing_page(cfg, limit=page_size, offset=offset)
            pages += 1
            page = [
                summary
                for item in raw_jobs
                if (summary := self._summary(item, cfg)) is not None
            ]
            signature = tuple(item.external_id or "" for item in page)
            if page and signature in signatures:
                raise ConnectorError(
                    "pagination_loop",
                    "Oracle CE returned a repeated requisition page",
                    diagnostics={"offset": offset},
                )
            signatures.add(signature)
            jobs.update({item.external_id or item.url: item for item in page})
            if not raw_jobs or offset + len(raw_jobs) >= total:
                break
            offset += len(raw_jobs)
        return list(jobs.values()), pages, []

    async def get_job_details(
        self, summary: RawJobSummary, config: dict[str, Any]
    ) -> RawJobDetails:
        cfg = summary.metadata.get("oracle_config") or config
        response = await self.http.request(
            "GET",
            self._endpoint(cfg, "recruitingCEJobRequisitionDetails"),
            params={
                "finder": f"ById;Id={summary.external_id},siteNumber={cfg['site_number']}",
                "onlyData": "true",
                "expand": "secondaryLocations,workLocation",
            },
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ConnectorError(
                "malformed_detail", "Oracle CE detail returned non-JSON content"
            ) from exc
        items = payload.get("items") if isinstance(payload, dict) else None
        body = items[0] if isinstance(items, list) and items else None
        if not isinstance(body, dict):
            raise ConnectorError(
                "malformed_detail", "Oracle CE detail response did not contain an item"
            )
        listing = summary.metadata.get("listing") or {}
        location_values: list[Any] = [body.get("PrimaryLocation"), listing.get("PrimaryLocation")]
        for key in ("secondaryLocations", "workLocation"):
            value = body.get(key)
            if isinstance(value, dict) and isinstance(value.get("items"), list):
                value = value["items"]
            location_values.extend(value if isinstance(value, list) else [value])
        locations = [
            rendered for value in location_values if (rendered := _render_location(value))
        ]
        return RawJobDetails(
            external_id=str(body.get("Id") or summary.external_id),
            url=summary.url,
            title=body.get("Title") or summary.title or "Untitled role",
            locations=locations,
            employment_type=body.get("JobSchedule") or listing.get("JobSchedule"),
            posted_date=parse_date(
                body.get("ExternalPostedStartDate") or listing.get("PostedDate")
            ),
            description_html=_description_html(body),
            metadata={
                "source": self.platform,
                "identifier": summary.external_id,
                "department": body.get("JobFamily"),
            },
        )

    def normalize(self, details: RawJobDetails) -> NormalizedJob:
        return normalized_job(details)
