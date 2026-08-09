from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.connectors.types import ScanOutput
from app.models import Base, CareersSource, ScanRun
from app.services.scans import enqueue_due_scans, recover_interrupted_runs
from app.worker import run_worker_once


def worker_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'worker.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def add_source(
    factory,
    *,
    company: str,
    due: datetime,
    monitoring_status: str = "active",
    setup_status: str = "ready",
):
    with factory() as session:
        source = CareersSource(
            company=company,
            url=f"https://{company.casefold()}.example.com/careers",
            detected_platform="test",
            connector_type="test_connector",
            connector_config={},
            setup_status=setup_status,
            monitoring_status=monitoring_status,
            next_scan_at=due,
        )
        session.add(source)
        session.commit()
        return source.id


def test_scheduler_enqueues_only_due_active_sources_and_is_idempotent(tmp_path):
    factory = worker_factory(tmp_path)
    now = datetime.now(UTC)
    due_id = add_source(factory, company="Due", due=now - timedelta(minutes=1))
    add_source(factory, company="Future", due=now + timedelta(hours=1))
    add_source(
        factory,
        company="Paused",
        due=now - timedelta(minutes=1),
        monitoring_status="paused",
    )
    add_source(
        factory,
        company="Setup",
        due=now - timedelta(minutes=1),
        setup_status="setup_required",
    )

    with factory() as session:
        created = enqueue_due_scans(session, now)
        assert len(created) == 1
        scan = session.get(ScanRun, created[0])
        assert scan.source_id == due_id
        assert scan.trigger == "initial"
        assert enqueue_due_scans(session, now) == []

        scan.status = "success"
        source = session.get(CareersSource, due_id)
        source.last_successful_scan_at = now
        session.commit()
        scheduled = enqueue_due_scans(session, now)
        assert len(scheduled) == 1
        assert session.get(ScanRun, scheduled[0]).trigger == "scheduled"


async def test_worker_executes_durable_queue_and_advances_schedule(tmp_path, monkeypatch):
    factory = worker_factory(tmp_path)
    now = datetime.now(UTC)
    source_id = add_source(factory, company="Worker", due=now - timedelta(minutes=1))

    class FakeConnector:
        async def scan(self, _url, _config):
            return ScanOutput(jobs=[], pages_visited=1)

    monkeypatch.setattr("app.services.scans.ConnectorRegistry.get", lambda *_args: FakeConnector())
    runtime = SimpleNamespace(
        state=SimpleNamespace(session_factory=factory, http=None, matcher=None, scan_tasks={})
    )
    assert await run_worker_once(runtime, now) is True

    with factory() as session:
        scan = session.scalar(select(ScanRun))
        source = session.get(CareersSource, source_id)
        assert scan.status == "success"
        assert scan.trigger == "initial"
        assert source.last_scan_attempt_at is not None
        assert source.last_successful_scan_at is not None
        assert source.next_scan_at > source.last_successful_scan_at
    assert await run_worker_once(runtime, now) is False


def test_worker_recovery_preserves_queued_work_and_requeues_running_source(tmp_path):
    factory = worker_factory(tmp_path)
    now = datetime.now(UTC)
    queued_source = add_source(factory, company="Queued", due=now)
    running_source = add_source(factory, company="Running", due=now + timedelta(hours=1))
    fresh_source = add_source(factory, company="Fresh", due=now + timedelta(hours=1))
    with factory() as session:
        queued = ScanRun(source_id=queued_source, trigger="scheduled", status="queued")
        running = ScanRun(source_id=running_source, trigger="scheduled", status="running")
        fresh = ScanRun(
            source_id=fresh_source,
            trigger="scheduled",
            status="running",
            started_at=now,
        )
        session.add_all([queued, running, fresh])
        session.commit()
        running_id = running.id
        queued_id = queued.id
        fresh_id = fresh.id

    with factory() as session:
        assert recover_interrupted_runs(session, now) == 1
        assert session.get(ScanRun, queued_id).status == "queued"
        assert session.get(ScanRun, running_id).status == "interrupted"
        assert session.get(ScanRun, fresh_id).status == "running"
        source = session.get(CareersSource, running_source)
        assert source.next_scan_at == source.last_scan_attempt_at
