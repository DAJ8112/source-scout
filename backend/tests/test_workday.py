import json

import httpx
import pytest
import respx

from app.connectors.errors import ConnectorError
from app.connectors.http import SafeHttpClient
from app.connectors.workday import CVS_FACETS, WorkdayConnector

SOURCE = "https://cvshealth.wd1.myworkdayjobs.com/CVS_Health_Careers"
API = "https://cvshealth.wd1.myworkdayjobs.com/wday/cxs/cvshealth/CVS_Health_Careers/jobs"


@respx.mock
async def test_workday_validation_payload_facets_and_normalization(fixture_text):
    listing = json.loads(fixture_text("workday/listing.json"))
    respx.get("https://cvshealth.wd1.myworkdayjobs.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )
    requests = []

    def listing_response(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=listing)

    respx.post(API).mock(side_effect=listing_response)
    detail_url = "https://cvshealth.wd1.myworkdayjobs.com/wday/cxs/cvshealth/CVS_Health_Careers/job/Remote/Senior-Data-Engineer_R001"
    respx.get(detail_url).mock(
        return_value=httpx.Response(200, json=json.loads(fixture_text("workday/detail.json")))
    )
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    connector = WorkdayConnector(http)
    config = {"tenant": "cvshealth", "site": "CVS_Health_Careers", "selected_facets": CVS_FACETS}
    result = await connector.validate(SOURCE, config)
    assert result.valid is True
    assert result.job_count == 2
    assert {facet["facet_parameter"] for facet in result.available_facets} == {
        "timeType",
        "workerSubType",
        "jobFamilyGroup",
    }
    payload = connector.payload(config)
    assert payload["searchText"] == ""
    assert payload["appliedFacets"]["jobFamilyGroup"] == [CVS_FACETS[2]["id"], CVS_FACETS[3]["id"]]
    summary = (await connector.list_jobs(SOURCE, config))[0][0]
    normalized = connector.normalize(
        await connector.get_job_details(summary, {**config, "source_url": SOURCE})
    )
    assert normalized.external_id == "R001"
    assert normalized.title == "Senior Data Engineer"
    assert normalized.locations == ["Chicago, IL", "Remote - USA"]
    assert len(normalized.content_fingerprint) == 64
    assert requests[0]["appliedFacets"] == {}
    await http.close()


@respx.mock
async def test_workday_facet_drift_enters_setup_required(fixture_text):
    listing = json.loads(fixture_text("workday/listing.json"))
    listing["facets"][0]["values"][0]["id"] = "new-id"
    respx.get("https://cvshealth.wd1.myworkdayjobs.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )
    respx.post(API).mock(return_value=httpx.Response(200, json=listing))
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    result = await WorkdayConnector(http).validate(SOURCE, {"selected_facets": CVS_FACETS})
    assert result.valid is False
    assert result.setup_status == "setup_required"
    assert result.diagnostics["code"] == "facet_drift"
    assert result.diagnostics["drift"][0]["current_id"] == "new-id"
    await http.close()


@respx.mock
async def test_workday_detects_pagination_loop(fixture_text):
    listing = json.loads(fixture_text("workday/listing.json"))
    listing["total"] = 100
    respx.get("https://cvshealth.wd1.myworkdayjobs.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )
    respx.post(API).mock(return_value=httpx.Response(200, json=listing))
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    with pytest.raises(ConnectorError) as caught:
        await WorkdayConnector(http).list_jobs(SOURCE, {"selected_facets": CVS_FACETS})
    assert caught.value.code == "pagination_loop"
    await http.close()


@respx.mock
async def test_workday_zero_results_is_not_success(fixture_text):
    listing = json.loads(fixture_text("workday/listing.json"))
    listing.update(total=0, jobPostings=[])
    respx.get("https://cvshealth.wd1.myworkdayjobs.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )
    respx.post(API).mock(return_value=httpx.Response(200, json=listing))
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    result = await WorkdayConnector(http).validate(SOURCE, {"selected_facets": CVS_FACETS})
    assert not result.valid
    assert result.diagnostics["code"] == "zero_results"
    await http.close()
