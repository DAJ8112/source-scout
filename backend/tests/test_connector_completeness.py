from app.connectors.base import CareersConnector
from app.connectors.errors import ConnectorError
from app.connectors.normalize import normalized_job
from app.connectors.types import RawJobDetails, RawJobSummary


class PartialConnector(CareersConnector):
    platform = "test"
    connector_type = "test"

    async def detect(self, url):
        raise NotImplementedError

    async def validate(self, url, config):
        raise NotImplementedError

    async def list_jobs(self, url, config):
        return (
            [
                RawJobSummary(external_id="1", url=f"{url}/1", title="One"),
                RawJobSummary(external_id="2", url=f"{url}/2", title="Two"),
            ],
            1,
            [],
        )

    async def get_job_details(self, summary, config):
        if summary.external_id == "2":
            raise ConnectorError("malformed_detail", "Second detail was malformed")
        return RawJobDetails(
            external_id=summary.external_id,
            url=summary.url,
            title=summary.title or "Untitled role",
            description_html="<p>Usable detail.</p>",
        )

    def normalize(self, details):
        return normalized_job(details)


async def test_base_connector_marks_partial_detail_traversal_incomplete():
    output = await PartialConnector().scan("https://example.com/jobs", {})
    assert len(output.jobs) == 1
    assert output.complete is False
    assert any(warning["code"] == "malformed_detail" for warning in output.warnings)
    assert any(warning["code"] == "incomplete_scan" for warning in output.warnings)
