import httpx
import pytest
import respx

from app.connectors.avature import AvatureConnector
from app.connectors.errors import ConnectorError
from app.connectors.http import SafeHttpClient
from app.connectors.types import RawJobSummary

SOURCE = "https://bloomberg.avature.net/careers/SearchJobs"


@respx.mock
async def test_avature_fixture_listing_pagination_and_details(fixture_text):
    respx.get("https://bloomberg.avature.net/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )

    def listing_response(request):
        fixture = (
            "avature/listing-2.html"
            if request.url.params.get("page") == "2"
            else "avature/listing-1.html"
        )
        return httpx.Response(200, text=fixture_text(fixture))

    respx.get(url__regex=r"^https://bloomberg\.avature\.net/careers/SearchJobs(?:\?.*)?$").mock(
        side_effect=listing_response
    )
    for job_id, title in (
        ("7001", "Data Engineer"),
        ("7002", "Software Engineer"),
        ("7003", "ML Engineer"),
    ):
        respx.get(url__regex=rf"^https://bloomberg\.avature\.net/careers/JobDetail/.*/{job_id}$").mock(
            return_value=httpx.Response(
                200,
                text=fixture_text("avature/detail.html").replace("Data Engineer", title),
            )
        )
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    connector = AvatureConnector(http)
    validation = await connector.validate(SOURCE, {})
    assert validation.valid
    output = await connector.scan(SOURCE, {"max_pages": 5})
    assert output.pages_visited == 2
    assert [job.external_id for job in output.jobs] == ["7001", "7002", "7003"]
    assert output.jobs[0].description_text == "Build financial data platforms."
    await http.close()


@respx.mock
async def test_avature_406_is_access_blocked_setup_signal():
    respx.get("https://bloomberg.avature.net/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )
    respx.get(SOURCE).mock(return_value=httpx.Response(406))
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    with pytest.raises(ConnectorError) as blocked:
        await AvatureConnector(http).validate(SOURCE, {})
    assert blocked.value.code == "access_blocked"
    assert blocked.value.diagnostics["status"] == 406
    await http.close()


@respx.mock
async def test_avature_malformed_detail_is_structured():
    detail = "https://bloomberg.avature.net/careers/JobDetail/Role/7001"
    respx.get(detail).mock(return_value=httpx.Response(200, text="<html></html>"))
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    detection = await AvatureConnector(http).detect(SOURCE)

    with pytest.raises(ConnectorError) as malformed:
        await AvatureConnector(http).get_job_details(
            RawJobSummary(external_id="7001", url=detail, title="Role"), {}
        )
    assert detection.connector_type == "avature_html"
    assert malformed.value.code == "malformed_detail"
    await http.close()
