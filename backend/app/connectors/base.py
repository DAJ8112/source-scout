from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

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
        jobs = [self.normalize(await self.get_job_details(item, config)) for item in summaries]
        return ScanOutput(jobs=jobs, pages_visited=pages, warnings=warnings)
