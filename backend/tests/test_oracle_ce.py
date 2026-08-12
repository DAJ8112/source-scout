import json

import httpx
import pytest
import respx

from app.connectors.errors import ConnectorError
from app.connectors.http import SafeHttpClient
from app.connectors.oracle_ce import OracleCeConnector
from app.connectors.types import RawJobSummary

SOURCE = "https://careers.honeywell.com/en/sites/Honeywell/jobs"
API_BASE = "https://tenant.fa.ocs.oraclecloud.com"
LISTING_API = f"{API_BASE}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
DETAIL_API = f"{API_BASE}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"


def allow_robots():
    respx.get("https://careers.honeywell.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )
    respx.get(f"{API_BASE}/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )


@respx.mock
async def test_oracle_vanity_discovery_api_pagination_facets_and_detail(fixture_text):
    allow_robots()
    respx.get(SOURCE).mock(
        return_value=httpx.Response(200, text=fixture_text("oracle/vanity.html"))
    )
    first = json.loads(fixture_text("oracle/listing-1.json"))
    second = json.loads(fixture_text("oracle/listing-2.json"))

    def listing_response(request):
        finder = request.url.params.get("finder", "")
        return httpx.Response(200, json=second if "offset=2" in finder else first)

    respx.get(LISTING_API).mock(side_effect=listing_response)
    respx.get(DETAIL_API).mock(
        return_value=httpx.Response(200, json=json.loads(fixture_text("oracle/detail.json")))
    )
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    connector = OracleCeConnector(http)
    detected = await connector.detect(SOURCE)
    assert detected.config["api_base_url"] == API_BASE
    assert detected.config["site_number"] == "CX_1"

    validation = await connector.validate(SOURCE, detected.config)
    assert validation.valid
    assert validation.job_count == 3
    assert validation.available_facets[0]["facetName"] == "LOCATIONS"
    summaries, pages, _ = await connector.list_jobs(
        SOURCE, {**detected.config, "page_size": 2}
    )
    assert pages == 2
    assert [item.external_id for item in summaries] == ["146423", "146424", "146425"]
    normalized = connector.normalize(await connector.get_job_details(summaries[0], {}))
    assert normalized.canonical_url == (
        "https://careers.honeywell.com/en/sites/Honeywell/job/146423"
    )
    assert normalized.posted_date.isoformat() == "2026-08-01"
    assert normalized.locations == [
        "Atlanta, Georgia, United States",
        "Phoenix, Arizona, United States",
    ]
    assert "Qualifications" in (normalized.description_text or "")
    await http.close()


@respx.mock
async def test_oracle_direct_host_config_keeps_public_vanity_url(fixture_text):
    source = (
        "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs"
    )
    config = {
        "api_base_url": API_BASE,
        "site_number": "CX_1001",
        "public_url": source,
        "page_size": 5,
    }
    respx.get(f"{API_BASE}/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )
    respx.get(LISTING_API).mock(
        return_value=httpx.Response(
            200, json=json.loads(fixture_text("oracle/listing-1.json"))
        )
    )
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    result = await OracleCeConnector(http).validate(source, config)
    assert result.valid
    assert result.sample_jobs[0]["url"].startswith(
        "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/"
    )
    await http.close()


@respx.mock
async def test_oracle_malformed_payload_and_unsafe_api_host(fixture_text):
    respx.get(f"{API_BASE}/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )
    respx.get(LISTING_API).mock(return_value=httpx.Response(200, json={"items": [{}]}))
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    connector = OracleCeConnector(http)
    with pytest.raises(ConnectorError) as malformed:
        await connector.validate(
            SOURCE,
            {"api_base_url": API_BASE, "site_number": "CX_1", "public_url": SOURCE},
        )
    assert malformed.value.code == "malformed_response"

    respx.get(DETAIL_API).mock(return_value=httpx.Response(200, json={"items": []}))
    summary = RawJobSummary(
        external_id="146423",
        url="https://careers.honeywell.com/en/sites/Honeywell/job/146423",
        title="Lead Data Engineer",
        metadata={
            "oracle_config": {
                "api_base_url": API_BASE,
                "site_number": "CX_1",
                "public_url": SOURCE,
            }
        },
    )
    with pytest.raises(ConnectorError) as malformed_detail:
        await connector.get_job_details(summary, {})
    assert malformed_detail.value.code == "malformed_detail"

    with pytest.raises(ConnectorError) as unsafe:
        await connector.validate(
            SOURCE,
            {
                "api_base_url": "https://attacker.example/api",
                "site_number": "CX_1",
                "public_url": SOURCE,
            },
        )
    assert unsafe.value.code == "unsafe_oracle_configuration"
    await http.close()
