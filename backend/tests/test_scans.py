from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.connectors.errors import ConnectorError
from app.connectors.types import NormalizedJob, ScanOutput
from app.models import Base, CareersSource, JobObservation, ScanRun
from app.services.scans import execute_scan, recover_interrupted_runs, unfinished_scan_for_source


def factory_for(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def source_and_scan(factory):
    with factory() as session:
        source = CareersSource(
            company="Example",
            url="https://careers.box.com/en/jobs/",
            detected_platform="happydance",
            connector_type="paginated_html_jsonld",
            connector_config={},
        )
        session.add(source)
        session.flush()
        scan = ScanRun(source_id=source.id, trigger="manual")
        session.add(scan)
        session.commit()
        return source.id, scan.id


async def test_scan_persists_immutable_normalized_observations_and_deduplicates(
    tmp_path, monkeypatch
):
    factory = factory_for(tmp_path)
    source_id, scan_id = source_and_scan(factory)
    job = NormalizedJob(
        external_id="123",
        canonical_url="https://careers.box.com/en/jobs/123/example",
        title="Example Engineer",
        locations=["Remote"],
        employment_type="FULL_TIME",
        posted_date=None,
        description_html="<p>Build.</p>",
        description_text="Build.",
        content_fingerprint="a" * 64,
        raw_metadata={"source": "happydance"},
    )

    class FakeConnector:
        async def scan(self, _url, _config):
            return ScanOutput(jobs=[job, job], pages_visited=3, warnings=[])

    monkeypatch.setattr("app.services.scans.ConnectorRegistry.get", lambda *_args: FakeConnector())
    app = SimpleNamespace(
        state=SimpleNamespace(session_factory=factory, http=None, scan_tasks={scan_id: object()})
    )
    await execute_scan(scan_id, app)
    with factory() as session:
        scan = session.get(ScanRun, scan_id)
        assert scan.status == "success"
        assert scan.jobs_found == 2
        assert scan.jobs_persisted == 1
        observations = session.scalars(select(JobObservation)).all()
        assert len(observations) == 1
        assert observations[0].source_id == source_id
        assert observations[0].description_text == "Build."


async def test_structured_scan_failure_updates_source_health(tmp_path, monkeypatch):
    factory = factory_for(tmp_path)
    source_id, scan_id = source_and_scan(factory)

    class FakeConnector:
        async def scan(self, _url, _config):
            raise ConnectorError(
                "access_blocked", "Blocked; no bypass attempted", diagnostics={"status": 403}
            )

    monkeypatch.setattr("app.services.scans.ConnectorRegistry.get", lambda *_args: FakeConnector())
    app = SimpleNamespace(
        state=SimpleNamespace(session_factory=factory, http=None, scan_tasks={scan_id: object()})
    )
    await execute_scan(scan_id, app)
    with factory() as session:
        scan = session.get(ScanRun, scan_id)
        source = session.get(CareersSource, source_id)
        assert scan.status == "failed"
        assert scan.error_code == "access_blocked"
        assert scan.error_diagnostics["diagnostics"]["status"] == 403
        assert source.setup_status == "setup_required"


def test_concurrent_scan_detection_and_interrupted_recovery(tmp_path):
    factory = factory_for(tmp_path)
    source_id, scan_id = source_and_scan(factory)
    with factory() as session:
        assert unfinished_scan_for_source(session, source_id).id == scan_id
        changed = recover_interrupted_runs(session)
        assert changed == 1
        recovered = session.get(ScanRun, scan_id)
        assert recovered.status == "interrupted"
        assert recovered.error_code == "process_interrupted"
        assert recovered.finished_at is not None
        assert unfinished_scan_for_source(session, source_id) is None
