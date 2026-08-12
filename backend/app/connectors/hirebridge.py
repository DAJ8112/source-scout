from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

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


class HirebridgeConnector(CareersConnector):
    platform = "hirebridge"
    connector_type = "hirebridge_html"

    def __init__(self, http: SafeHttpClient) -> None:
        self.http = http

    @staticmethod
    def _embed_coordinates(embed_url: str) -> tuple[str, str]:
        parts = urlsplit(embed_url)
        client_id = (parse_qs(parts.query).get("cid") or [""])[0]
        if parts.scheme != "https" or parts.hostname != "recruit.hirebridge.com":
            raise ConnectorError(
                "unsafe_embed_host",
                "Hirebridge iframe must use the official recruit.hirebridge.com host",
                diagnostics={"embed_url": embed_url},
            )
        if not re.fullmatch(r"\d+", client_id):
            raise ConnectorError(
                "invalid_hirebridge_client",
                "Hirebridge iframe did not contain a numeric client ID",
                diagnostics={"embed_url": embed_url},
            )
        return parts.hostname, client_id

    async def _discover(self, url: str) -> dict[str, Any]:
        allowed, warning = await self.http.robots_allowed(url)
        if not allowed:
            raise ConnectorError(
                "robots_disallowed",
                "robots.txt disallows the PRGX careers page",
                diagnostics=warning or {"url": url},
            )
        response = await self.http.request("GET", url)
        soup = BeautifulSoup(response.text, "html.parser")
        iframe = soup.select_one('iframe[src*="hirebridge.com"]')
        if not iframe or not iframe.get("src"):
            raise ConnectorError(
                "hirebridge_embed_missing",
                "PRGX careers page did not contain a Hirebridge iframe",
                diagnostics={"url": url},
            )
        embed_url = canonicalize_url(str(iframe["src"]), url, keep_query=True)
        _, client_id = self._embed_coordinates(embed_url)
        return {
            "embed_url": embed_url,
            "client_id": client_id,
            "public_url": canonicalize_url(url),
            "max_pages": 100,
        }

    async def _config(self, url: str, config: dict[str, Any]) -> dict[str, Any]:
        if not config.get("embed_url"):
            return {**config, **(await self._discover(url))}
        embed_url = canonicalize_url(str(config["embed_url"]), keep_query=True)
        _, discovered_client = self._embed_coordinates(embed_url)
        client_id = str(config.get("client_id") or discovered_client)
        if client_id != discovered_client:
            raise ConnectorError(
                "invalid_hirebridge_client",
                "Configured Hirebridge client ID does not match the iframe URL",
                diagnostics={"configured": client_id, "discovered": discovered_client},
            )
        public_url = str(config.get("public_url") or url)
        if urlsplit(public_url).hostname != urlsplit(url).hostname:
            raise ConnectorError(
                "unsafe_public_url",
                "Configured Hirebridge public URL does not match the source host",
            )
        return {
            **config,
            "embed_url": embed_url,
            "client_id": client_id,
            "public_url": canonicalize_url(public_url),
            "max_pages": int(config.get("max_pages", 100)),
        }

    async def detect(self, url: str) -> DetectionResult:
        config = await self._discover(url)
        return DetectionResult(
            platform=self.platform,
            connector_type=self.connector_type,
            confidence=0.99,
            evidence=[
                "Official PRGX careers page",
                "Official Hirebridge iframe and client ID discovered",
            ],
            config=config,
        )

    @staticmethod
    def _allowed(candidate: str, client_id: str) -> bool:
        parts = urlsplit(candidate)
        query = parse_qs(parts.query)
        return (
            parts.scheme == "https"
            and parts.hostname == "recruit.hirebridge.com"
            and (query.get("cid") or [""])[0] == client_id
        )

    def _listing(
        self, html: str, page_url: str, config: dict[str, Any]
    ) -> tuple[list[RawJobSummary], list[str], int]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: dict[str, RawJobSummary] = {}
        next_pages: list[str] = []
        rejected = 0
        for anchor in soup.select("a[href]"):
            href = str(anchor.get("href") or "")
            candidate = canonicalize_url(href, page_url, keep_query=True)
            query = parse_qs(urlsplit(candidate).query)
            job_id = (query.get("jid") or [""])[0]
            if job_id:
                if not self._allowed(candidate, config["client_id"]):
                    rejected += 1
                    continue
                container = anchor.find_parent(["article", "li", "tr", "div"])
                location_node = container.select_one(
                    ".location, .job-location, [data-field='location']"
                ) if container else None
                type_node = container.select_one(
                    ".job-type, .employment-type, [data-field='employment-type']"
                ) if container else None
                jobs[job_id] = RawJobSummary(
                    external_id=job_id,
                    url=candidate,
                    title=anchor.get_text(" ", strip=True) or None,
                    metadata={
                        "location": location_node.get_text(" ", strip=True)
                        if location_node
                        else None,
                        "employment_type": type_node.get_text(" ", strip=True)
                        if type_node
                        else None,
                    },
                )
                continue
            if anchor.get("rel") == ["next"] or "next" in str(
                anchor.get("aria-label") or ""
            ).casefold():
                if self._allowed(candidate, config["client_id"]):
                    next_pages.append(candidate)
                else:
                    rejected += 1
        return list(jobs.values()), list(dict.fromkeys(next_pages)), rejected

    async def validate(self, url: str, config: dict[str, Any]) -> ValidationResult:
        cfg = await self._config(url, config)
        allowed, warning = await self.http.robots_allowed(cfg["embed_url"])
        if not allowed:
            return ValidationResult(
                valid=False, setup_status="setup_required", diagnostics=warning or {}
            )
        response = await self.http.request("GET", cfg["embed_url"])
        jobs, _, rejected = self._listing(response.text, cfg["embed_url"], cfg)
        warnings = [warning] if warning else []
        if rejected:
            warnings.append({"code": "unsafe_hirebridge_links_ignored", "count": rejected})
        if not jobs:
            return ValidationResult(
                valid=False,
                setup_status="setup_required",
                warnings=warnings,
                diagnostics={
                    "code": "zero_results",
                    "message": "Hirebridge returned no jobs for the discovered client ID",
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
        cfg = await self._config(url, config)
        queue = [cfg["embed_url"]]
        visited: set[str] = set()
        jobs: dict[str, RawJobSummary] = {}
        warnings: list[dict] = []
        while queue and len(visited) < cfg["max_pages"]:
            page = queue.pop(0)
            if page in visited:
                warnings.append({"code": "pagination_loop", "url": page})
                continue
            visited.add(page)
            response = await self.http.request("GET", page)
            found, next_pages, rejected = self._listing(response.text, page, cfg)
            jobs.update({item.external_id or item.url: item for item in found})
            if rejected:
                warnings.append(
                    {
                        "code": "unsafe_hirebridge_links_ignored",
                        "count": rejected,
                        "url": page,
                    }
                )
            queue.extend(item for item in next_pages if item not in visited and item not in queue)
        if queue:
            warnings.append({"code": "page_limit_reached", "limit": cfg["max_pages"]})
        return list(jobs.values()), len(visited), warnings

    async def get_job_details(
        self, summary: RawJobSummary, config: dict[str, Any]
    ) -> RawJobDetails:
        response = await self.http.request("GET", summary.url)
        soup = BeautifulSoup(response.text, "html.parser")
        title_node = soup.select_one("h1, .job-title, [data-field='title']")
        description = soup.select_one(
            "#JobDescription, #job-description, .job-description, [data-job-description]"
        )
        if not title_node or not description:
            raise ConnectorError(
                "malformed_detail",
                "Hirebridge detail was missing its title or description",
                diagnostics={"url": summary.url},
            )
        location_node = soup.select_one(".location, .job-location, [data-field='location']")
        type_node = soup.select_one(
            ".job-type, .employment-type, [data-field='employment-type']"
        )
        date_node = soup.select_one("time[datetime], [data-field='posted-date']")
        location = (
            location_node.get_text(" ", strip=True)
            if location_node
            else summary.metadata.get("location")
        )
        employment_type = (
            type_node.get_text(" ", strip=True)
            if type_node
            else summary.metadata.get("employment_type")
        )
        return RawJobDetails(
            external_id=summary.external_id,
            url=summary.url,
            title=title_node.get_text(" ", strip=True),
            locations=[location] if location else [],
            employment_type=employment_type,
            posted_date=parse_date(date_node.get("datetime") if date_node else None),
            description_html=str(description),
            metadata={"source": self.platform, "identifier": summary.external_id},
        )

    def normalize(self, details: RawJobDetails) -> NormalizedJob:
        return normalized_job(details)
