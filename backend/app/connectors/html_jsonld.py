from __future__ import annotations

import json
import re
import unicodedata
from html import unescape
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from app.connectors.base import CareersConnector
from app.connectors.errors import ConnectorError
from app.connectors.http import SafeHttpClient
from app.connectors.normalize import normalized_job, parse_date
from app.connectors.safety import canonicalize_url, traversal_allowed
from app.connectors.types import (
    DetectionResult,
    NormalizedJob,
    RawJobDetails,
    RawJobSummary,
    ScanOutput,
    ValidationResult,
)


def _jobposting_nodes(value: Any) -> list[dict]:
    found: list[dict] = []
    if isinstance(value, dict):
        kind = value.get("@type")
        if kind == "JobPosting" or isinstance(kind, list) and "JobPosting" in kind:
            found.append(value)
        for nested in value.values():
            found.extend(_jobposting_nodes(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_jobposting_nodes(nested))
    return found


def extract_jobposting(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    malformed = 0
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except json.JSONDecodeError, TypeError:
            malformed += 1
            continue
        nodes = _jobposting_nodes(data)
        if nodes:
            return nodes[0]
    code = "malformed_jsonld" if malformed else "missing_jsonld"
    raise ConnectorError(
        code,
        "Job detail did not contain a usable JobPosting JSON-LD object",
        diagnostics={"url": url, "malformed_blocks": malformed},
    )


def extract_embedded_object(html: str, marker: str) -> dict | None:
    """Decode a JSON object assigned inside server-rendered listing HTML."""
    marker_index = html.find(marker)
    if marker_index < 0:
        return None
    object_index = html.find("{", marker_index + len(marker))
    if object_index < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(html[object_index:])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-") or "job"


def _locations(value: Any) -> list[str]:
    results: list[str] = []
    values = value if isinstance(value, list) else [value]
    for entry in values:
        if not isinstance(entry, dict):
            continue
        address = entry.get("address", entry)
        if isinstance(address, str):
            results.append(address)
        elif isinstance(address, dict):
            parts = [
                address.get(key)
                for key in (
                    "streetAddress",
                    "addressLocality",
                    "addressRegion",
                    "postalCode",
                    "addressCountry",
                )
            ]
            rendered = ", ".join(str(item) for item in parts if item)
            if rendered:
                results.append(rendered)
    return results


def _nested(value: Any, path: list[str]) -> Any:
    current = value
    for key in path:
        current = current.get(key) if isinstance(current, dict) else None
    return current


def _replace_query(url: str, values: dict[str, str]) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(values)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _description_html(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    decoded = unescape(value)
    return decoded if re.search(r"<\s*[a-zA-Z][^>]*>", decoded) else value


class HtmlJsonLdConnector(CareersConnector):
    connector_type = "paginated_html_jsonld"

    def __init__(self, http: SafeHttpClient, platform: str, defaults: dict[str, Any]) -> None:
        self.http = http
        self.platform = platform
        self.defaults = defaults

    async def detect(self, url: str) -> DetectionResult:
        evidence = [f"Hostname matches configured {self.platform} source pattern"]
        return DetectionResult(
            platform=self.platform,
            connector_type=self.connector_type,
            confidence=0.98,
            evidence=evidence,
            config=self.defaults,
        )

    def _config(self, config: dict[str, Any]) -> dict[str, Any]:
        return {**self.defaults, **config}

    async def validate(self, url: str, config: dict[str, Any]) -> ValidationResult:
        cfg = {**self._config(config), "source_url": url}
        listing_url = canonicalize_url(cfg.get("listing_url") or url, url, keep_query=True)
        allowed, warning = await self.http.robots_allowed(listing_url)
        if not allowed:
            return ValidationResult(
                valid=False, setup_status="setup_required", diagnostics=warning or {}
            )
        response = await self.http.request("GET", listing_url)
        summaries, off_host = self._extract_summaries(response.text, listing_url, cfg)
        warnings = [warning] if warning else []
        if off_host:
            warnings.append(
                {
                    "code": "off_host_links_ignored",
                    "message": "Off-host job-like links were not traversed",
                    "count": off_host,
                }
            )
        if not summaries:
            return ValidationResult(
                valid=False,
                setup_status="setup_required",
                warnings=warnings,
                diagnostics={
                    "code": "zero_results",
                    "message": "No same-host job detail links matched the configured listing pattern",
                },
            )
        return ValidationResult(
            valid=True,
            setup_status="ready",
            job_count=self._embedded_total(response.text, cfg),
            sample_jobs=[{"title": item.title, "url": item.url} for item in summaries[:5]],
            warnings=warnings,
        )

    def _extract_summaries(
        self, html: str, page_url: str, config: dict
    ) -> tuple[list[RawJobSummary], int]:
        soup = BeautifulSoup(html, "html.parser")
        pattern = re.compile(config["detail_path_regex"])
        source_url = config.get("source_url", page_url)
        allowed_paths = config["allowed_paths"]
        result: list[RawJobSummary] = []
        off_host = 0
        for anchor in soup.select(config.get("job_link_selector", "a[href]")):
            href = anchor.get("href")
            if not href:
                continue
            candidate = canonicalize_url(href, page_url)
            detail_match = pattern.search(urlsplit(candidate).path)
            if not detail_match:
                continue
            if not traversal_allowed(candidate, source_url, allowed_paths):
                off_host += 1
                continue
            title = anchor.get_text(" ", strip=True) or None
            external_id = detail_match.groupdict().get("id")
            result.append(RawJobSummary(external_id=external_id, url=candidate, title=title))
        marker = config.get("embedded_object_marker")
        if marker:
            embedded = extract_embedded_object(html, marker)
            current = _nested(embedded, config.get("embedded_jobs_path", []))
            if isinstance(current, list):
                for item in current:
                    if not isinstance(item, dict):
                        continue
                    route_id = item.get(config.get("embedded_route_id_field", "jobSeqNo"))
                    title = item.get(config.get("embedded_title_field", "title"))
                    if not route_id or not title:
                        continue
                    path = config["embedded_detail_template"].format(
                        id=route_id, slug=_slug(str(title))
                    )
                    candidate = canonicalize_url(path, page_url)
                    if not traversal_allowed(candidate, source_url, allowed_paths):
                        continue
                    result.append(
                        RawJobSummary(
                            external_id=item.get(config.get("embedded_external_id_field", "reqId")),
                            url=candidate,
                            title=str(title),
                            metadata={"listing": item},
                        )
                    )
        deduped = {item.url: item for item in result}
        return list(deduped.values()), off_host

    def _embedded_total(self, html: str, config: dict[str, Any]) -> int | None:
        pagination = config.get("embedded_pagination")
        marker = config.get("embedded_object_marker")
        if not pagination or not marker:
            return None
        embedded = extract_embedded_object(html, marker)
        total = _nested(embedded, pagination.get("total_path", []))
        try:
            return int(total)
        except TypeError, ValueError:
            return None

    def _generated_next_pages(
        self,
        html: str,
        page_url: str,
        config: dict[str, Any],
        summaries: list[RawJobSummary],
    ) -> list[str]:
        embedded_pagination = config.get("embedded_pagination")
        if embedded_pagination and config.get("embedded_object_marker"):
            embedded = extract_embedded_object(html, config["embedded_object_marker"])
            total = _nested(embedded, embedded_pagination.get("total_path", []))
            page_size = _nested(embedded, embedded_pagination.get("page_size_path", []))
            try:
                total_value = int(total)
                page_size_value = int(page_size)
            except TypeError, ValueError:
                return []
            parameter = embedded_pagination.get("parameter", "from")
            current = dict(parse_qsl(urlsplit(page_url).query)).get(parameter, "0")
            try:
                next_offset = int(current) + page_size_value
            except ValueError:
                return []
            if page_size_value > 0 and next_offset < total_value:
                values = {
                    parameter: str(next_offset),
                    **embedded_pagination.get("static_query", {}),
                }
                return [canonicalize_url(_replace_query(page_url, values), keep_query=True)]

        offset_pagination = config.get("offset_pagination")
        if offset_pagination:
            page_size = int(offset_pagination["page_size"])
            if len(summaries) < page_size:
                return []
            parameter = offset_pagination.get("parameter", "start")
            current = dict(parse_qsl(urlsplit(page_url).query)).get(parameter, "0")
            try:
                next_offset = int(current) + page_size
            except ValueError:
                return []
            return [
                canonicalize_url(
                    _replace_query(page_url, {parameter: str(next_offset)}), keep_query=True
                )
            ]
        return []

    def _next_pages(self, html: str, page_url: str, config: dict) -> tuple[list[str], int]:
        soup = BeautifulSoup(html, "html.parser")
        selectors = config.get("pagination_selector", 'a[rel="next"], a[aria-label*="Next" i]')
        candidates = []
        rejected = 0
        for anchor in soup.select(selectors):
            if not anchor.get("href"):
                continue
            candidate = canonicalize_url(anchor["href"], page_url, keep_query=True)
            if traversal_allowed(candidate, config["source_url"], config["allowed_paths"]):
                candidates.append(candidate)
            else:
                rejected += 1
        return list(dict.fromkeys(candidates)), rejected

    async def list_jobs(
        self, url: str, config: dict[str, Any]
    ) -> tuple[list[RawJobSummary], int, list[dict]]:
        cfg = {**self._config(config), "source_url": url}
        listing_url = canonicalize_url(cfg.get("listing_url") or url, url, keep_query=True)
        queue = [listing_url]
        visited: set[str] = set()
        jobs: dict[str, RawJobSummary] = {}
        warnings: list[dict] = []
        while queue:
            page = queue.pop(0)
            if page in visited:
                warnings.append(
                    {
                        "code": "pagination_loop",
                        "message": "Repeated pagination link ignored",
                        "url": page,
                    }
                )
                continue
            if len(visited) >= int(cfg.get("max_pages", 500)):
                raise ConnectorError(
                    "page_limit", "Listing traversal exceeded configured page limit"
                )
            allowed, robots_warning = await self.http.robots_allowed(page)
            if robots_warning and robots_warning not in warnings:
                warnings.append(robots_warning)
            if not allowed:
                raise ConnectorError(
                    "robots_disallowed",
                    "robots.txt disallows a listing page",
                    diagnostics={"url": page},
                )
            response = await self.http.request("GET", page)
            visited.add(page)
            summaries, off_host = self._extract_summaries(response.text, page, cfg)
            if off_host:
                warnings.append({"code": "off_host_links_ignored", "count": off_host, "url": page})
            jobs.update({item.url: item for item in summaries})
            next_pages, rejected = self._next_pages(response.text, page, cfg)
            next_pages.extend(self._generated_next_pages(response.text, page, cfg, summaries))
            next_pages = list(dict.fromkeys(next_pages))
            if rejected:
                warnings.append(
                    {"code": "unsafe_pagination_ignored", "count": rejected, "url": page}
                )
            for next_page in next_pages:
                if next_page in visited:
                    warnings.append(
                        {
                            "code": "pagination_loop",
                            "message": "Repeated pagination link ignored",
                            "url": next_page,
                        }
                    )
                elif next_page not in queue:
                    queue.append(next_page)
        if not jobs:
            raise ConnectorError("zero_results", "Listing traversal produced zero jobs")
        return list(jobs.values()), len(visited), warnings

    async def get_job_details(
        self, summary: RawJobSummary, config: dict[str, Any]
    ) -> RawJobDetails:
        allowed, warning = await self.http.robots_allowed(summary.url)
        if not allowed:
            raise ConnectorError(
                "robots_disallowed",
                "robots.txt disallows a job detail",
                diagnostics={"url": summary.url},
            )
        response = await self.http.request("GET", summary.url)
        data = extract_jobposting(response.text, summary.url)
        identifier = data.get("identifier")
        if isinstance(identifier, dict):
            identifier = identifier.get("value") or identifier.get("name")
        canonical = data.get("url") or summary.url
        if not traversal_allowed(
            canonicalize_url(canonical, summary.url), config["source_url"], config["allowed_paths"]
        ):
            canonical = summary.url
        employment = data.get("employmentType")
        if isinstance(employment, list):
            employment = ", ".join(str(item) for item in employment)
        return RawJobDetails(
            external_id=str(identifier or summary.external_id) if identifier or summary.external_id else None,
            url=canonicalize_url(canonical, summary.url),
            title=data.get("title") or summary.title or "Untitled role",
            locations=_locations(data.get("jobLocation")),
            employment_type=employment,
            posted_date=parse_date(data.get("datePosted")),
            description_html=_description_html(data.get("description")),
            metadata={
                "source": self.platform,
                "identifier": identifier,
                "date_modified": data.get("dateModified"),
            },
        )

    def normalize(self, details: RawJobDetails) -> NormalizedJob:
        return normalized_job(details)

    async def scan(self, url: str, config: dict[str, Any]) -> ScanOutput:
        cfg = {**self._config(config), "source_url": url}
        summaries, pages, warnings = await self.list_jobs(url, cfg)
        jobs: list[NormalizedJob] = []
        complete = not any(
            warning.get("code") in {"page_limit_reached", "pagination_loop"}
            for warning in warnings
        )
        for summary in summaries:
            try:
                jobs.append(self.normalize(await self.get_job_details(summary, cfg)))
            except ConnectorError as exc:
                complete = False
                warnings.append(exc.as_dict())
        if not jobs:
            raise ConnectorError(
                "detail_extraction_failure",
                "No listing entries produced a valid JobPosting detail",
                diagnostics={"listing_jobs": len(summaries), "warnings": warnings[-10:]},
            )
        if not complete:
            warnings.append(
                {
                    "code": "incomplete_scan",
                    "message": "Traversal was incomplete; absence transitions must be skipped",
                }
            )
        return ScanOutput(
            jobs=jobs,
            pages_visited=pages + len(summaries),
            warnings=warnings,
            complete=complete,
        )
