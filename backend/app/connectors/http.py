from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.config import settings
from app.connectors.errors import ConnectorError

TRANSIENT_STATUSES = {408, 425, 429, 500, 502, 503, 504}


class SafeHttpClient:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        interval_seconds: float | None = None,
        max_retries: int | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.client = client or httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            headers={
                "User-Agent": settings.user_agent,
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.1",
            },
            follow_redirects=True,
        )
        self.interval = (
            settings.host_interval_seconds if interval_seconds is None else interval_seconds
        )
        self.max_retries = settings.max_transient_retries if max_retries is None else max_retries
        self.sleep = sleep
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, tuple[RobotFileParser | None, dict | None]] = {}

    async def close(self) -> None:
        await self.client.aclose()

    async def _rate_limit(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            elapsed = time.monotonic() - self._last_request.get(host, 0)
            if elapsed < self.interval:
                await self.sleep(self.interval - elapsed)
            self._last_request[host] = time.monotonic()

    @staticmethod
    def _retry_after(response: httpx.Response, attempt: int) -> float:
        raw = response.headers.get("Retry-After")
        if raw:
            try:
                return max(0.0, float(raw))
            except ValueError:
                try:
                    parsed = parsedate_to_datetime(raw)
                    return max(0.0, (parsed - datetime.now(UTC)).total_seconds())
                except TypeError, ValueError:
                    pass
        return min(2**attempt, 8)

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        host = urlsplit(url).netloc.lower()
        attempts = 0
        while True:
            await self._rate_limit(host)
            try:
                response = await self.client.request(method, url, **kwargs)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempts >= self.max_retries:
                    raise ConnectorError(
                        "network_failure",
                        f"Request failed after {attempts + 1} attempts",
                        retryable=True,
                        diagnostics={"url": url, "exception": type(exc).__name__},
                    ) from exc
                await self.sleep(min(2**attempts, 8))
                attempts += 1
                continue
            if response.status_code in TRANSIENT_STATUSES:
                if attempts >= self.max_retries:
                    raise ConnectorError(
                        "transient_http_failure",
                        f"HTTP {response.status_code} after {attempts + 1} attempts",
                        retryable=True,
                        diagnostics={"url": str(response.url), "status": response.status_code},
                    )
                await self.sleep(self._retry_after(response, attempts))
                attempts += 1
                continue
            if response.status_code in {401, 403, 406}:
                raise ConnectorError(
                    "access_blocked",
                    f"Official source returned HTTP {response.status_code}; no bypass was attempted",
                    diagnostics={"url": str(response.url), "status": response.status_code},
                )
            if response.status_code >= 400:
                raise ConnectorError(
                    "http_failure",
                    f"Official source returned HTTP {response.status_code}",
                    diagnostics={"url": str(response.url), "status": response.status_code},
                )
            body_start = response.text[:2000].lower()
            if "captcha" in body_start or "verify you are human" in body_start:
                raise ConnectorError(
                    "access_blocked",
                    "Official source presented a CAPTCHA or access challenge; no bypass was attempted",
                    diagnostics={"url": str(response.url)},
                )
            return response

    async def robots_allowed(self, url: str) -> tuple[bool, dict | None]:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            robots_url = f"{origin}/robots.txt"
            try:
                response = await self.request("GET", robots_url)
            except ConnectorError as exc:
                warning = {
                    "code": "robots_unavailable",
                    "message": "robots.txt was unavailable; continuing conservatively",
                    "diagnostics": exc.diagnostics,
                }
                self._robots[origin] = (None, warning)
            else:
                parser = RobotFileParser()
                parser.set_url(robots_url)
                parser.parse(response.text.splitlines())
                self._robots[origin] = (parser, None)
        parser, warning = self._robots[origin]
        if parser and not parser.can_fetch(settings.user_agent, url):
            return False, {
                "code": "robots_disallowed",
                "message": "robots.txt explicitly disallows this path",
                "diagnostics": {"url": url},
            }
        return True, warning
