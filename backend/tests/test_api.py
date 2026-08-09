from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import engine as app_engine
from app.db import get_session
from app.main import create_app
from app.models import Base, ScanRun


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
