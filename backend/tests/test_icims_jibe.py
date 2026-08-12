import json

import httpx
import respx

from app.connectors.http import SafeHttpClient
from app.connectors.icims_jibe import IcimsJibeConnector

SOURCE = "https://careers.rivian.com/careers-home/jobs"
API = "https://careers.rivian.com/api/jobs"


@respx.mock
async def test_icims_validation_pagination_and_complete_api_details(fixture_text):
    first = json.loads(fixture_text("icims/listing-1.json"))
    second = json.loads(fixture_text("icims/listing-2.json"))
    respx.get("https://careers.rivian.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )

    def page_response(request):
        return httpx.Response(
            200,
            json=second if request.url.params.get("offset") == "2" else first,
        )

    respx.get(API).mock(side_effect=page_response)
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    connector = IcimsJibeConnector(http)
    config = (await connector.detect(SOURCE)).config
    validation = await connector.validate(SOURCE, config)
    assert validation.valid
    assert validation.job_count == 3
    assert {facet["facet_parameter"] for facet in validation.available_facets} == {
        "categories",
        "locations",
    }

    output = await connector.scan(SOURCE, {**config, "page_size": 2})
    assert output.pages_visited == 2
    assert [job.external_id for job in output.jobs] == ["RIV-101", "RIV-102", "RIV-103"]
    assert output.jobs[0].locations == ["Palo Alto, California, United States"]
    assert output.jobs[0].description_text == "Build reliable vehicle data products."
    assert output.jobs[1].canonical_url.endswith("/careers-home/jobs/30102")
    await http.close()


@respx.mock
async def test_icims_zero_and_malformed_payloads_are_not_valid():
    respx.get("https://careers.rivian.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )
    route = respx.get(API)
    route.mock(return_value=httpx.Response(200, json={"jobs": [], "totalCount": 0}))
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    connector = IcimsJibeConnector(http)
    result = await connector.validate(SOURCE, {})
    assert not result.valid
    assert result.diagnostics["code"] == "zero_results"

    route.mock(return_value=httpx.Response(200, json={"unexpected": []}))
    try:
        await connector.validate(SOURCE, {})
    except Exception as exc:
        assert getattr(exc, "code", None) == "malformed_response"
    else:
        raise AssertionError("Malformed iCIMS payload should fail validation")
    await http.close()
