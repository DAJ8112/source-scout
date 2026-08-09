from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import get_session
from app.main import create_app
from app.models import Base, CareersSource, Job
from app.services.matching import HybridMatcher


def profile_api_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'profile-api.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def add_active_job(factory):
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
            description_text="Build Python data pipelines.",
            content_fingerprint="b" * 64,
            raw_metadata={},
            lifecycle_status="active",
            consecutive_successful_absences=0,
            initial_import=True,
            first_discovered_at=now,
            last_observed_at=now,
        )
        session.add(job)
        session.commit()


def test_profile_resume_rematch_and_feed(tmp_path, monkeypatch):
    factory = profile_api_factory(tmp_path)
    add_active_job(factory)

    def override_session():
        with factory() as session:
            yield session

    monkeypatch.setattr(
        "app.api.profile_routes.extract_pdf_text",
        lambda _data: "Built Python data pipelines with Airflow on AWS.",
    )
    app = create_app()
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        app.state.matcher = HybridMatcher(Settings(anthropic_api_key=None))
        profile = client.get("/api/profile").json()
        assert profile["version"] == 1
        updated = client.patch(
            "/api/profile",
            json={
                "target_roles": [" Data Engineer ", "data engineer"],
                "adjacent_roles": ["Data Platform Engineer"],
                "preferred_locations": ["Remote"],
                "remote_preference": "remote_only",
                "required_terms": ["Python"],
            },
        )
        assert updated.status_code == 200
        assert updated.json()["target_roles"] == ["Data Engineer"]
        assert updated.json()["version"] == 2

        uploaded = client.post(
            "/api/profile/resume",
            files={"file": ("resume.pdf", b"synthetic-pdf", "application/pdf")},
        )
        assert uploaded.status_code == 200
        assert uploaded.json()["resume_filename"] == "resume.pdf"
        assert uploaded.json()["version"] == 3
        assert client.patch("/api/profile", json={"target_roles": None}).status_code == 422

        rematched = client.post("/api/profile/rematch")
        assert rematched.status_code == 200
        assert rematched.json()["local_fallbacks"] == 1
        feed = client.get("/api/feed").json()
        assert feed["profile_ready"] is True
        assert feed["provider_configured"] is False
        assert feed["items"][0]["match"]["provider"] == "local"
        assert feed["items"][0]["company"] == "Example"


def test_resume_upload_validation(tmp_path):
    factory = profile_api_factory(tmp_path)

    def override_session():
        with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        response = client.post(
            "/api/profile/resume",
            files={"file": ("resume.txt", b"not a pdf", "text/plain")},
        )
        assert response.status_code == 415
