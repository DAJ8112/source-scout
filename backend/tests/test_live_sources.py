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
    ("https://cvshealth.wd1.myworkdayjobs.com/CVS_Health_Careers", set()),
    ("https://jobs.veralto.com/global/en/search-results", set()),
    ("https://careers.box.com/en/jobs/", {"access_blocked"}),
    ("https://cccis.wd1.myworkdayjobs.com/broadbean_external", set()),
    ("https://careers.rivian.com/careers-home/jobs", set()),
    ("https://wd3.myworkdaysite.com/recruiting/mdlz/External", set()),
    ("https://globalfoundries.eightfold.ai/careers", {"access_blocked"}),
    ("https://jobs.kwiktrip.com/us/en/", set()),
    ("https://careers.honeywell.com/en/sites/Honeywell/jobs", set()),
    ("https://bloomberg.avature.net/careers/SearchJobs", {"access_blocked"}),
    (
        "https://careers.toyota.com/us/en/c/technology-data-analytics-jobs",
        set(),
    ),
    (
        "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs",
        set(),
    ),
    ("https://www.prgx.com/company/careers/", {"access_blocked"}),
]


@pytest.mark.parametrize(("url", "allowed_access_codes"), SOURCES)
async def test_live_source_validates_with_nonzero_traversal(url, allowed_access_codes):
    async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
        http = SafeHttpClient(client)
        try:
            connector, detection = await ConnectorRegistry(http).detect(url)
            result = await connector.validate(url, detection.config)
        except ConnectorError as exc:
            if exc.code not in allowed_access_codes:
                raise
            assert "bypass" in exc.message
            return
        assert result.valid, result.model_dump()
        assert (result.job_count or len(result.sample_jobs)) > 0
        if detection.platform in {
            "eightfold",
            "phenom",
            "phenom_kwiktrip",
            "phenom_toyota",
            "workday",
        }:
            sample = result.sample_jobs[0]
            details = await connector.get_job_details(
                RawJobSummary(external_id=None, url=sample["url"], title=sample.get("title")),
                {**detection.config, "source_url": url},
            )
            assert connector.normalize(details).content_fingerprint
