from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import respx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import engine as app_engine
from app.db import get_session
from app.main import create_app
from app.models import Base, CareersSource, Job, ScanRun


def test_source_crud_and_concurrent_scan_rejection(tmp_path):
    Base.metadata.create_all(app_engine)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session() -> Generator[Session]:
        with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        app.state.session_factory = factory
        created = client.post(
            "/api/sources",
            json={
                "company": "CVS Health",
                "url": "https://cvshealth.wd1.myworkdayjobs.com/CVS_Health_Careers",
            },
        )
        assert created.status_code == 201
        source = created.json()
        assert source["detected_platform"] == "workday"
        assert len(source["connector_config"]["selected_facets"]) == 4
        assert client.get("/api/sources").json()[0]["id"] == source["id"]
        patched = client.patch(f"/api/sources/{source['id']}", json={"company": "CVS"})
        assert patched.json()["company"] == "CVS"
        paused = client.patch(
            f"/api/sources/{source['id']}", json={"monitoring_status": "paused"}
        )
        assert paused.json()["monitoring_status"] == "paused"
        resumed = client.patch(
            f"/api/sources/{source['id']}", json={"monitoring_status": "active"}
        )
        assert resumed.json()["monitoring_status"] == "active"
        assert client.patch(f"/api/sources/{source['id']}", json={"company": None}).status_code == 422
        with factory() as session:
            session.add(ScanRun(source_id=source["id"], trigger="manual", status="running"))
            session.commit()
        conflict = client.post(f"/api/sources/{source['id']}/scans", json={"trigger": "manual"})
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "scan_already_running"


def test_jobs_pagination_returns_404_for_unknown_scan(tmp_path):
    Base.metadata.create_all(app_engine)
    engine = create_engine(f"sqlite:///{tmp_path / 'api2.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override_session():
        with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        assert client.get("/api/scans/not-found/jobs").status_code == 404


@respx.mock
def test_bloomberg_406_is_visible_as_setup_required(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'api-bloomberg.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        with factory() as session:
            yield session

    source_url = "https://bloomberg.avature.net/careers/SearchJobs"
    respx.get("https://bloomberg.avature.net/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )
    respx.get(source_url).mock(return_value=httpx.Response(406))
    app = create_app()
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        created = client.post(
            "/api/sources", json={"company": "Bloomberg", "url": source_url}
        )
        assert created.status_code == 201
        source = created.json()
        assert source["connector_type"] == "avature_html"
        result = client.post(f"/api/sources/{source['id']}/validate").json()
        assert result["source"]["setup_status"] == "setup_required"
        assert result["validation"]["diagnostics"]["code"] == "access_blocked"


def test_manual_scan_is_dispatched_immediately_and_remains_durable(
    tmp_path, monkeypatch
):
    engine = create_engine(f"sqlite:///{tmp_path / 'api-scan.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        source = CareersSource(
            company="Example",
            url="https://example.com/careers",
            detected_platform="test",
            connector_type="test_connector",
            setup_status="ready",
        )
        session.add(source)
        session.commit()
        source_id = source.id

    def override_session():
        with factory() as session:
            yield session

    execute_scan = AsyncMock()
    monkeypatch.setattr("app.api.routes.execute_scan", execute_scan)
    app = create_app()
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        app.state.session_factory = factory
        response = client.post(
            f"/api/sources/{source_id}/scans", json={"trigger": "manual"}
        )

    assert response.status_code == 202
    scan_id = response.json()["id"]
    execute_scan.assert_awaited_once_with(scan_id, app)
    with factory() as session:
        assert session.get(ScanRun, scan_id).status == "queued"


def test_current_jobs_can_be_filtered_and_read(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'api3.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(UTC)
    with factory() as session:
        source = CareersSource(company="Example", url="https://example.com/careers")
        session.add(source)
        session.flush()
        job = Job(
            source_id=source.id,
            identity_key="external:R1",
            external_id="R1",
            canonical_url="https://example.com/jobs/R1",
            title="Data Engineer",
            locations=["Remote"],
            employment_type="FULL_TIME",
            posted_date=None,
            description_html=None,
            description_text="Build pipelines",
            content_fingerprint="a" * 64,
            raw_metadata={},
            lifecycle_status="active",
            consecutive_successful_absences=0,
            initial_import=True,
            first_discovered_at=now,
            last_observed_at=now,
        )
        session.add(job)
        session.commit()

    def override_session():
        with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        response = client.get(f"/api/jobs?source_id={source.id}&lifecycle_status=active")
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["title"] == "Data Engineer"
        assert client.get(f"/api/jobs/{job.id}").json()["initial_import"] is True
        assert client.get("/api/jobs?lifecycle_status=invalid").status_code == 422


def test_referral_contact_crud_is_scoped_to_source(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'api4.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        source = CareersSource(company="Example", url="https://example.com/careers")
        other = CareersSource(company="Other", url="https://other.example.com/careers")
        session.add_all([source, other])
        session.commit()

    def override_session():
        with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        created = client.post(
            f"/api/sources/{source.id}/contacts",
            json={
                "name": "  Taylor  ",
                "contact_url": "https://www.linkedin.com/in/taylor",
                "notes": "  Former teammate  ",
            },
        )
        assert created.status_code == 201
        contact = created.json()
        assert contact["name"] == "Taylor"
        assert contact["notes"] == "Former teammate"
        assert client.get(f"/api/sources/{source.id}").json()["contacts"][0]["id"] == contact["id"]

        wrong_source = client.patch(
            f"/api/sources/{other.id}/contacts/{contact['id']}", json={"name": "Nope"}
        )
        assert wrong_source.status_code == 404
        assert (
            client.patch(
                f"/api/sources/{source.id}/contacts/{contact['id']}", json={"name": None}
            ).status_code
            == 422
        )
        patched = client.patch(
            f"/api/sources/{source.id}/contacts/{contact['id']}",
            json={"contact_url": None, "notes": None},
        )
        assert patched.json()["contact_url"] is None
        assert patched.json()["notes"] is None
        assert (
            client.delete(f"/api/sources/{source.id}/contacts/{contact['id']}").status_code
            == 204
        )
        assert client.get(f"/api/sources/{source.id}").json()["contacts"] == []
