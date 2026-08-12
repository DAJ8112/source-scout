import httpx
import pytest
import respx

from app.connectors.errors import ConnectorError
from app.connectors.hirebridge import HirebridgeConnector
from app.connectors.http import SafeHttpClient

SOURCE = "https://www.prgx.com/company/careers/"
EMBED = "https://recruit.hirebridge.com/v3/CareerCenter/v2?cid=7765"


def allow_robots():
    respx.get("https://www.prgx.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )
    respx.get("https://recruit.hirebridge.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )


@respx.mock
async def test_hirebridge_discovery_listing_security_and_details(fixture_text):
    allow_robots()
    respx.get(SOURCE).mock(
        return_value=httpx.Response(200, text=fixture_text("hirebridge/outer.html"))
    )
    respx.get(EMBED).mock(
        return_value=httpx.Response(200, text=fixture_text("hirebridge/listing-1.html"))
    )
    respx.get("https://recruit.hirebridge.com/v3/CareerCenter/v2?cid=7765&page=2").mock(
        return_value=httpx.Response(200, text=fixture_text("hirebridge/listing-2.html"))
    )
    for job_id, title in (("6001", "Senior Data Engineer"), ("6002", "Software Engineer")):
        respx.get(
            f"https://recruit.hirebridge.com/v3/Jobs/Details.aspx?cid=7765&jid={job_id}"
        ).mock(
            return_value=httpx.Response(
                200,
                text=fixture_text("hirebridge/detail.html").replace(
                    "Senior Data Engineer", title
                ),
            )
        )
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    connector = HirebridgeConnector(http)
    detection = await connector.detect(SOURCE)
    assert detection.config["client_id"] == "7765"
    validation = await connector.validate(SOURCE, detection.config)
    assert validation.valid
    assert validation.sample_jobs[0]["title"] == "Senior Data Engineer"

    output = await connector.scan(SOURCE, detection.config)
    assert output.pages_visited == 2
    assert [job.external_id for job in output.jobs] == ["6001", "6002"]
    assert output.jobs[0].canonical_url.endswith("?cid=7765&jid=6001")
    assert output.jobs[0].canonical_url != output.jobs[1].canonical_url
    assert output.jobs[0].locations == ["Atlanta, GA"]
    assert output.jobs[0].employment_type == "Full Time"
    assert any(
        warning["code"] == "unsafe_hirebridge_links_ignored"
        for warning in output.warnings
    )
    await http.close()


@respx.mock
async def test_hirebridge_rejects_changed_client_and_unsafe_iframe(fixture_text):
    allow_robots()
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    connector = HirebridgeConnector(http)
    with pytest.raises(ConnectorError) as changed:
        await connector.validate(
            SOURCE,
            {
                "embed_url": EMBED,
                "client_id": "9999",
                "public_url": SOURCE,
            },
        )
    assert changed.value.code == "invalid_hirebridge_client"

    respx.get(SOURCE).mock(
        return_value=httpx.Response(
            200,
            text='<iframe src="https://evilhirebridge.com/embed?cid=7765"></iframe>',
        )
    )
    with pytest.raises(ConnectorError) as unsafe:
        await connector.detect(SOURCE)
    assert unsafe.value.code == "unsafe_embed_host"
    await http.close()


@respx.mock
async def test_hirebridge_robots_denial_stops_embedded_traversal():
    respx.get("https://recruit.hirebridge.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /v3")
    )
    http = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    result = await HirebridgeConnector(http).validate(
        SOURCE,
        {"embed_url": EMBED, "client_id": "7765", "public_url": SOURCE},
    )
    assert not result.valid
    assert result.diagnostics["code"] == "robots_disallowed"
    await http.close()
