import httpx
import pytest
import respx

from app.connectors.errors import ConnectorError
from app.connectors.html_jsonld import HtmlJsonLdConnector, extract_jobposting
from app.connectors.http import SafeHttpClient
from app.connectors.registry import HAPPYDANCE_CONFIG, PHENOM_CONFIG


@respx.mock
async def test_phenom_pagination_off_host_loop_and_normalization(fixture_text):
    source = "https://jobs.veralto.com/global/en/search-results"
    respx.get("https://jobs.veralto.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )

    def listing_response(request):
        fixture = (
            "phenom/listing-2.html"
            if request.url.params.get("page") == "2"
            else "phenom/listing-1.html"
        )
        return httpx.Response(200, text=fixture_text(fixture))

    respx.get(url__startswith=source).mock(side_effect=listing_response)
    respx.get("https://jobs.veralto.com/global/en/job/R100/Platform-Engineer").mock(
        return_value=httpx.Response(200, text=fixture_text("phenom/detail.html"))
    )
    respx.get("https://jobs.veralto.com/global/en/job/R101/Data-Analyst").mock(
        return_value=httpx.Response(
            200,
            text=fixture_text("phenom/detail.html")
            .replace("R100", "R101")
            .replace("Platform Engineer", "Data Analyst"),
        )
    )
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    output = await HtmlJsonLdConnector(http, "phenom", PHENOM_CONFIG).scan(source, {})
    assert len(output.jobs) == 2
    assert output.pages_visited == 4
    assert any(item["code"] == "off_host_links_ignored" for item in output.warnings)
    assert any(item["code"] == "pagination_loop" for item in output.warnings)
    assert output.jobs[0].canonical_url.startswith("https://jobs.veralto.com/global/en/job/")
    assert "utm_" not in output.jobs[0].canonical_url
    await http.close()


@respx.mock
async def test_happydance_graph_jsonld(fixture_text):
    source = "https://careers.box.com/en/jobs/"
    detail = "https://careers.box.com/en/jobs/1234567/software-engineer"
    respx.get("https://careers.box.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )
    respx.get(source).mock(
        return_value=httpx.Response(200, text=fixture_text("happydance/listing.html"))
    )
    respx.get(detail).mock(
        return_value=httpx.Response(200, text=fixture_text("happydance/detail.html"))
    )
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    output = await HtmlJsonLdConnector(http, "happydance", HAPPYDANCE_CONFIG).scan(source, {})
    assert output.jobs[0].external_id == "1234567"
    assert output.jobs[0].locations == ["Redwood City, CA, US"]
    await http.close()


@pytest.mark.parametrize(
    ("html", "code"),
    [
        ("<html></html>", "missing_jsonld"),
        ('<script type="application/ld+json">{bad</script>', "malformed_jsonld"),
    ],
)
def test_missing_and_malformed_jsonld_are_structured(html, code):
    with pytest.raises(ConnectorError) as caught:
        extract_jobposting(html, "https://example.com/job/1")
    assert caught.value.code == code
    assert caught.value.diagnostics["url"].endswith("/1")


def test_phenom_embedded_server_listing_is_configured():
    html = """<script>phApp.ddo = {"eagerLoadRefineSearch":{"data":{"jobs":[
      {"jobSeqNo":"TENANTR55EXTERNALENGLOBAL","reqId":"R55","title":"R&D Engineer"}
    ]}}}; phApp.next = {};</script>"""
    connector = HtmlJsonLdConnector(None, "phenom", PHENOM_CONFIG)  # type: ignore[arg-type]
    jobs, rejected = connector._extract_summaries(
        html,
        "https://jobs.veralto.com/global/en/search-results",
        {**PHENOM_CONFIG, "source_url": "https://jobs.veralto.com/global/en/search-results"},
    )
    assert rejected == 0
    assert jobs[0].external_id == "R55"
    assert (
        jobs[0].url
        == "https://jobs.veralto.com/global/en/job/TENANTR55EXTERNALENGLOBAL/R-D-Engineer"
    )


@respx.mock
async def test_explicit_robots_disallow_stops_traversal(fixture_text):
    source = "https://careers.box.com/en/jobs/"
    respx.get("https://careers.box.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /en/jobs")
    )
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    result = await HtmlJsonLdConnector(http, "happydance", HAPPYDANCE_CONFIG).validate(source, {})
    assert not result.valid
    assert result.diagnostics["code"] == "robots_disallowed"
    await http.close()
