from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

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


class AvatureConnector(CareersConnector):
    platform = "avature"
    connector_type = "avature_html"

    def __init__(self, http: SafeHttpClient) -> None:
        self.http = http

    async def detect(self, url: str) -> DetectionResult:
        return DetectionResult(
            platform=self.platform,
            connector_type=self.connector_type,
            confidence=0.99,
            evidence=["Official Bloomberg Avature careers hostname and SearchJobs path"],
            config={"listing_url": canonicalize_url(url, keep_query=True), "max_pages": 100},
        )

    @staticmethod
    def _same_host(candidate: str, source: str) -> bool:
        parts = urlsplit(candidate)
        return parts.scheme == "https" and parts.hostname == urlsplit(source).hostname

    def _listing(
        self, html: str, page_url: str, source_url: str
    ) -> tuple[list[RawJobSummary], list[str], int]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: dict[str, RawJobSummary] = {}
        next_pages: list[str] = []
        rejected = 0
        for anchor in soup.select("a[href]"):
            candidate = canonicalize_url(str(anchor.get("href")), page_url, keep_query=True)
            path = urlsplit(candidate).path
            detail = re.search(r"/JobDetail/(?:[^/]+/)*(?P<id>\d+)(?:/|$)", path, re.I)
            if detail:
                if not self._same_host(candidate, source_url):
                    rejected += 1
                    continue
                jobs[detail.group("id")] = RawJobSummary(
                    external_id=detail.group("id"),
                    url=canonicalize_url(candidate),
                    title=anchor.get_text(" ", strip=True) or None,
                )
                continue
            is_next = anchor.get("rel") == ["next"] or "next" in str(
                anchor.get("aria-label") or ""
            ).casefold()
            if is_next or "SearchJobs" in path and urlsplit(candidate).query:
                if self._same_host(candidate, source_url) and "/careers/SearchJobs" in path:
                    next_pages.append(candidate)
                else:
                    rejected += 1
        return list(jobs.values()), list(dict.fromkeys(next_pages)), rejected

    async def validate(self, url: str, config: dict[str, Any]) -> ValidationResult:
        listing_url = config.get("listing_url") or url
        allowed, warning = await self.http.robots_allowed(listing_url)
        if not allowed:
            return ValidationResult(
                valid=False, setup_status="setup_required", diagnostics=warning or {}
            )
        response = await self.http.request("GET", listing_url)
        jobs, _, rejected = self._listing(response.text, listing_url, url)
        warnings = [warning] if warning else []
        if rejected:
            warnings.append({"code": "unsafe_avature_links_ignored", "count": rejected})
        if not jobs:
            return ValidationResult(
                valid=False,
                setup_status="setup_required",
                warnings=warnings,
                diagnostics={
                    "code": "zero_results",
                    "message": "Avature listing returned no usable Bloomberg jobs",
                },
            )
        return ValidationResult(
            valid=True,
            setup_status="ready",
            job_count=None,
            sample_jobs=[{"title": item.title, "url": item.url} for item in jobs[:5]],
            warnings=warnings,
        )

    async def list_jobs(
        self, url: str, config: dict[str, Any]
    ) -> tuple[list[RawJobSummary], int, list[dict]]:
        listing_url = config.get("listing_url") or url
        max_pages = int(config.get("max_pages", 100))
        queue = [canonicalize_url(listing_url, keep_query=True)]
        visited: set[str] = set()
        jobs: dict[str, RawJobSummary] = {}
        warnings: list[dict] = []
        while queue and len(visited) < max_pages:
            page = queue.pop(0)
            if page in visited:
                warnings.append({"code": "pagination_loop", "url": page})
                continue
            visited.add(page)
            response = await self.http.request("GET", page)
            found, next_pages, rejected = self._listing(response.text, page, url)
            jobs.update({item.external_id or item.url: item for item in found})
            if rejected:
                warnings.append(
                    {"code": "unsafe_avature_links_ignored", "count": rejected, "url": page}
                )
            queue.extend(item for item in next_pages if item not in visited and item not in queue)
        if queue:
            warnings.append({"code": "page_limit_reached", "limit": max_pages})
        return list(jobs.values()), len(visited), warnings

    async def get_job_details(
        self, summary: RawJobSummary, config: dict[str, Any]
    ) -> RawJobDetails:
        response = await self.http.request("GET", summary.url)
        soup = BeautifulSoup(response.text, "html.parser")
        title_node = soup.select_one("h1, .job-title, [data-field='title']")
        description = soup.select_one(
            ".job-description, #job-description, [data-field='description']"
        ) or soup.select_one("main")
        if not title_node or not description:
            raise ConnectorError(
                "malformed_detail",
                "Avature detail was missing its title or description",
                diagnostics={"url": summary.url},
            )
        location_nodes = soup.select(
            ".job-location, [data-field='location'], [class*='location']"
        )
        type_node = soup.select_one(".employment-type, [data-field='employment-type']")
        date_node = soup.select_one("time[datetime], [data-field='posted-date']")
        return RawJobDetails(
            external_id=summary.external_id,
            url=summary.url,
            title=title_node.get_text(" ", strip=True),
            locations=[node.get_text(" ", strip=True) for node in location_nodes],
            employment_type=type_node.get_text(" ", strip=True) if type_node else None,
            posted_date=parse_date(date_node.get("datetime") if date_node else None),
            description_html=str(description),
            metadata={"source": self.platform, "identifier": summary.external_id},
        )

    def normalize(self, details: RawJobDetails) -> NormalizedJob:
        return normalized_job(details)
