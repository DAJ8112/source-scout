import httpx
import pytest

from app.connectors.errors import ConnectorError
from app.connectors.http import SafeHttpClient
from app.connectors.registry import ConnectorRegistry


@pytest.mark.parametrize(
    ("url", "platform", "connector"),
    [
        ("https://cvshealth.wd1.myworkdayjobs.com/CVS_Health_Careers", "workday", "workday_cxs"),
        ("https://jobs.veralto.com/global/en/search-results", "phenom", "paginated_html_jsonld"),
        ("https://careers.box.com/en/jobs/", "happydance", "paginated_html_jsonld"),
        (
            "https://jobs.kwiktrip.com/us/en/",
            "phenom_kwiktrip",
            "paginated_html_jsonld",
        ),
        (
            "https://careers.toyota.com/us/en/c/technology-data-analytics-jobs",
            "phenom_toyota",
            "paginated_html_jsonld",
        ),
        (
            "https://globalfoundries.eightfold.ai/careers",
            "eightfold",
            "paginated_html_jsonld",
        ),
        (
            "https://wd3.myworkdaysite.com/recruiting/mdlz/External",
            "workday",
            "workday_cxs",
        ),
    ],
)
async def test_detection_contract(url, platform, connector):
    client = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    _, result = await ConnectorRegistry(client).detect(url)
    assert result.platform == platform
    assert result.connector_type == connector
    assert result.confidence >= 0.9
    assert result.evidence
    await client.close()


async def test_detection_rejects_unsupported_source():
    client = SafeHttpClient(httpx.AsyncClient(), interval_seconds=0)
    with pytest.raises(ConnectorError, match="No Milestone 1 connector") as caught:
        await ConnectorRegistry(client).detect("https://example.com/careers")
    assert caught.value.code == "unsupported_source"
    await client.close()
