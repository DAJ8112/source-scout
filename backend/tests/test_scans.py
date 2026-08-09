from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.connectors.errors import ConnectorError
from app.connectors.types import NormalizedJob, ScanOutput
from app.models import Base, CareersSource, Job, JobObservation, ScanRun
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


def queued_scan(factory, source_id):
    with factory() as session:
        scan = ScanRun(source_id=source_id, trigger="manual")
        session.add(scan)
        session.commit()
        return scan.id


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


async def test_successful_scans_reconcile_job_lifecycle_and_failed_scans_do_not(
    tmp_path, monkeypatch
):
    factory = factory_for(tmp_path)
    source_id, first_scan_id = source_and_scan(factory)

    def normalized(fingerprint: str) -> NormalizedJob:
        return NormalizedJob(
            external_id="123",
            canonical_url="https://careers.box.com/en/jobs/123/example",
            title="Example Engineer",
            locations=["Remote"],
            employment_type="FULL_TIME",
            posted_date=None,
            description_html=f"<p>{fingerprint}</p>",
            description_text=fingerprint,
            content_fingerprint=fingerprint * 64,
            raw_metadata={},
        )

    outputs = [
        ScanOutput(jobs=[normalized("a")], pages_visited=1),
        ScanOutput(jobs=[normalized("b")], pages_visited=1),
        ScanOutput(jobs=[], pages_visited=1),
        ScanOutput(jobs=[], pages_visited=1),
        ScanOutput(jobs=[normalized("b")], pages_visited=1),
    ]

    class FakeConnector:
        async def scan(self, _url, _config):
            return outputs.pop(0)

    monkeypatch.setattr("app.services.scans.ConnectorRegistry.get", lambda *_args: FakeConnector())
    app = SimpleNamespace(state=SimpleNamespace(session_factory=factory, http=None, scan_tasks={}))

    for index in range(5):
        scan_id = first_scan_id if index == 0 else queued_scan(factory, source_id)
        app.state.scan_tasks[scan_id] = object()
        await execute_scan(scan_id, app)

        with factory() as session:
            job = session.scalar(select(Job))
            scan = session.get(ScanRun, scan_id)
            assert job is not None
            if index == 0:
                assert job.initial_import is True
                assert scan.jobs_created == 1
            elif index == 1:
                assert job.content_fingerprint == "b" * 64
                assert scan.jobs_updated == 1
            elif index == 2:
                assert job.lifecycle_status == "possibly_closed"
                assert job.consecutive_successful_absences == 1
                assert scan.jobs_missing == 1
            elif index == 3:
                assert job.lifecycle_status == "closed"
                assert job.consecutive_successful_absences == 2
            else:
                assert job.lifecycle_status == "active"
                assert job.consecutive_successful_absences == 0

    failed_scan_id = queued_scan(factory, source_id)

    class FailedConnector:
        async def scan(self, _url, _config):
            raise ConnectorError("timeout", "Temporary failure", retryable=True)

    monkeypatch.setattr("app.services.scans.ConnectorRegistry.get", lambda *_args: FailedConnector())
    app.state.scan_tasks[failed_scan_id] = object()
    await execute_scan(failed_scan_id, app)
    with factory() as session:
        job = session.scalar(select(Job))
        assert job.lifecycle_status == "active"
        assert job.consecutive_successful_absences == 0
        assert session.get(ScanRun, failed_scan_id).status == "failed"


async def test_jobs_discovered_after_initial_scan_are_not_initial_imports(tmp_path, monkeypatch):
    factory = factory_for(tmp_path)
    source_id, first_scan_id = source_and_scan(factory)

    def normalized(external_id: str) -> NormalizedJob:
        return NormalizedJob(
            external_id=external_id,
            canonical_url=f"https://careers.box.com/en/jobs/{external_id}/example",
            title=f"Engineer {external_id}",
            locations=[],
            employment_type=None,
            posted_date=None,
            description_html=None,
            description_text=None,
            content_fingerprint=external_id.zfill(64),
            raw_metadata={},
        )

    outputs = [
        ScanOutput(jobs=[normalized("1")], pages_visited=1),
        ScanOutput(jobs=[normalized("1"), normalized("2")], pages_visited=1),
    ]

    class FakeConnector:
        async def scan(self, _url, _config):
            return outputs.pop(0)

    monkeypatch.setattr("app.services.scans.ConnectorRegistry.get", lambda *_args: FakeConnector())
    app = SimpleNamespace(state=SimpleNamespace(session_factory=factory, http=None, scan_tasks={}))
    for scan_id in [first_scan_id, queued_scan(factory, source_id)]:
        app.state.scan_tasks[scan_id] = object()
        await execute_scan(scan_id, app)

    with factory() as session:
        jobs = {job.external_id: job for job in session.scalars(select(Job)).all()}
        assert len(jobs) == 2
        assert jobs["1"].initial_import is True
        assert jobs["2"].initial_import is False
