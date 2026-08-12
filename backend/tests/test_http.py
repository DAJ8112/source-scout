import httpx
import pytest
import respx

from app.connectors.errors import ConnectorError
from app.connectors.http import SafeHttpClient


@respx.mock
async def test_honors_retry_after_and_retries_429():
    sleeps = []

    async def record_sleep(seconds):
        sleeps.append(seconds)

    route = respx.get("https://example.com/jobs").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, text="ok"),
        ]
    )
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0, sleep=record_sleep)
    response = await http.request("GET", "https://example.com/jobs")
    assert response.text == "ok"
    assert route.call_count == 2
    assert sleeps == [2]
    await http.close()


@respx.mock
async def test_timeout_has_at_most_three_retries():
    route = respx.get("https://example.com/jobs").mock(side_effect=httpx.ReadTimeout("slow"))

    async def no_sleep(_seconds):
        pass

    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0, sleep=no_sleep)
    with pytest.raises(ConnectorError) as caught:
        await http.request("GET", "https://example.com/jobs")
    assert caught.value.code == "network_failure"
    assert route.call_count == 4
    await http.close()


@respx.mock
async def test_robots_unavailable_records_warning_and_continues():
    respx.get("https://example.com/robots.txt").mock(return_value=httpx.Response(404))
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    allowed, warning = await http.robots_allowed("https://example.com/jobs")
    assert allowed
    assert warning["code"] == "robots_unavailable"
    await http.close()


@respx.mock
async def test_406_is_access_blocked_without_retry_or_bypass():
    route = respx.get("https://example.com/jobs").mock(return_value=httpx.Response(406))
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    with pytest.raises(ConnectorError) as caught:
        await http.request("GET", "https://example.com/jobs")
    assert caught.value.code == "access_blocked"
    assert caught.value.diagnostics["status"] == 406
    assert route.call_count == 1
    await http.close()
