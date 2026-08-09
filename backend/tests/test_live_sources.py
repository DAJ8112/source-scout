import os

import httpx
import pytest

from app.connectors.errors import ConnectorError
from app.connectors.http import SafeHttpClient
from app.connectors.registry import ConnectorRegistry
from app.connectors.types import RawJobSummary

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("REFERRALS_LIVE_TESTS") != "1", reason="manual live smoke only"),
]

SOURCES = [
    ("https://cvshealth.wd1.myworkdayjobs.com/CVS_Health_Careers", None),
    ("https://jobs.veralto.com/global/en/search-results", None),
    ("https://careers.box.com/en/jobs/", "access_blocked"),
]


@pytest.mark.parametrize(("url", "expected_setup_code"), SOURCES)
async def test_live_source_validates_with_nonzero_traversal(url, expected_setup_code):
    async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
        http = SafeHttpClient(client)
        connector, detection = await ConnectorRegistry(http).detect(url)
        if expected_setup_code:
            with pytest.raises(ConnectorError) as caught:
                await connector.validate(url, detection.config)
            assert caught.value.code == expected_setup_code
            assert "bypass" in caught.value.message
            return
        result = await connector.validate(url, detection.config)
        assert result.valid, result.model_dump()
        assert (result.job_count or len(result.sample_jobs)) > 0
        if detection.platform in {"phenom", "workday"}:
            sample = result.sample_jobs[0]
            details = await connector.get_job_details(
                RawJobSummary(external_id=None, url=sample["url"], title=sample.get("title")),
                {**detection.config, "source_url": url},
            )
            assert connector.normalize(details).content_fingerprint
