from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.connectors.errors import ConnectorError
from app.connectors.types import (
    DetectionResult,
    NormalizedJob,
    RawJobDetails,
    RawJobSummary,
    ScanOutput,
    ValidationResult,
)


class CareersConnector(ABC):
    platform: str
    connector_type: str

    @abstractmethod
    async def detect(self, url: str) -> DetectionResult: ...

    @abstractmethod
    async def validate(self, url: str, config: dict[str, Any]) -> ValidationResult: ...

    @abstractmethod
    async def list_jobs(
        self, url: str, config: dict[str, Any]
    ) -> tuple[list[RawJobSummary], int, list[dict]]: ...

    @abstractmethod
    async def get_job_details(
        self, summary: RawJobSummary, config: dict[str, Any]
    ) -> RawJobDetails: ...

    @abstractmethod
    def normalize(self, details: RawJobDetails) -> NormalizedJob: ...

    async def scan(self, url: str, config: dict[str, Any]) -> ScanOutput:
        summaries, pages, warnings = await self.list_jobs(url, config)
        warnings = list(warnings)
        jobs: list[NormalizedJob] = []
        complete = not any(
            warning.get("code") in {"page_limit_reached", "pagination_loop"}
            for warning in warnings
        )
        for summary in summaries:
            try:
                jobs.append(self.normalize(await self.get_job_details(summary, config)))
            except ConnectorError as exc:
                complete = False
                warnings.append(exc.as_dict())
        if summaries and not jobs:
            raise ConnectorError(
                "detail_extraction_failure",
                "No listing entries produced a usable job detail",
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
            pages_visited=pages,
            warnings=warnings,
            complete=complete,
        )
