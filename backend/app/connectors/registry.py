from __future__ import annotations

from urllib.parse import urlsplit

from app.connectors.base import CareersConnector
from app.connectors.errors import ConnectorError
from app.connectors.html_jsonld import HtmlJsonLdConnector
from app.connectors.http import SafeHttpClient
from app.connectors.types import DetectionResult
from app.connectors.workday import WorkdayConnector

PHENOM_CONFIG = {
    "allowed_paths": ["/global/en"],
    "detail_path_regex": r"/global/en/job/[^/]+(?:/|$)",
    "job_link_selector": 'a[href*="/global/en/job/"]',
    "pagination_selector": 'a[rel="next"], a[aria-label*="Next" i], a.paginationItem[href]',
    "embedded_object_marker": "phApp.ddo =",
    "embedded_jobs_path": ["eagerLoadRefineSearch", "data", "jobs"],
    "embedded_route_id_field": "jobSeqNo",
    "embedded_external_id_field": "reqId",
    "embedded_title_field": "title",
    "embedded_detail_template": "/global/en/job/{id}/{slug}",
    "max_pages": 500,
}

HAPPYDANCE_CONFIG = {
    "allowed_paths": ["/en/jobs"],
    "detail_path_regex": r"/en/jobs/\d+(?:/|$)",
    "job_link_selector": 'a[href*="/en/jobs/"]',
    "pagination_selector": 'a[rel="next"], a[aria-label*="Next" i], nav a[href*="page="]',
    "max_pages": 500,
}


class ConnectorRegistry:
    def __init__(self, http: SafeHttpClient) -> None:
        self.http = http

    async def detect(self, url: str) -> tuple[CareersConnector, DetectionResult]:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        path = parts.path.rstrip("/")
        if ".myworkdayjobs.com" in host:
            connector: CareersConnector = WorkdayConnector(self.http)
        elif host == "jobs.veralto.com" and path.startswith("/global/en"):
            connector = HtmlJsonLdConnector(self.http, "phenom", PHENOM_CONFIG)
        elif host == "careers.box.com" and path.startswith("/en/jobs"):
            connector = HtmlJsonLdConnector(self.http, "happydance", HAPPYDANCE_CONFIG)
        else:
            raise ConnectorError(
                "unsupported_source",
                "No Milestone 1 connector matches this official careers URL",
                diagnostics={"host": host, "path": parts.path},
            )
        return connector, await connector.detect(url)

    def get(self, connector_type: str, platform: str | None = None) -> CareersConnector:
        if connector_type == "workday_cxs":
            return WorkdayConnector(self.http)
        if connector_type == "paginated_html_jsonld" and platform == "phenom":
            return HtmlJsonLdConnector(self.http, "phenom", PHENOM_CONFIG)
        if connector_type == "paginated_html_jsonld" and platform == "happydance":
            return HtmlJsonLdConnector(self.http, "happydance", HAPPYDANCE_CONFIG)
        raise ConnectorError("unsupported_connector", f"Unknown connector {connector_type!r}")


async def detect_source(url: str, http: SafeHttpClient) -> tuple[CareersConnector, DetectionResult]:
    return await ConnectorRegistry(http).detect(url)
