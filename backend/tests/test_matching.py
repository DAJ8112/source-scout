from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.models import Base, CareersSource, Job, MatchResult, SearchProfile
from app.services.matching import HybridMatcher, local_evaluation, match_jobs


def matching_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'matching.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def add_profile_and_job(factory):
    with factory() as session:
        source = CareersSource(company="Example", url="https://example.com/careers")
        profile = SearchProfile(
            resume_text="Built Python and Airflow data pipelines on AWS.",
            target_roles=["Data Engineer"],
            adjacent_roles=["Data Platform Engineer"],
            preferred_locations=["Remote"],
            remote_preference="remote_only",
            employment_types=["FULL_TIME"],
            required_terms=["Python"],
            excluded_terms=[],
            preference_notes="Prefer platform ownership.",
        )
        session.add_all([source, profile])
        session.flush()
        job = Job(
            source_id=source.id,
            identity_key="external:R1",
            external_id="R1",
            canonical_url="https://example.com/jobs/R1",
            title="Senior Data Engineer",
            locations=["Remote"],
            employment_type="FULL_TIME",
            posted_date=None,
            description_html=None,
            description_text="Build Python data pipelines with Airflow and AWS.",
            content_fingerprint="a" * 64,
            raw_metadata={},
            lifecycle_status="active",
            consecutive_successful_absences=0,
            initial_import=True,
            first_discovered_at=source.created_at,
            last_observed_at=source.created_at,
        )
        session.add(job)
        session.commit()
        return profile.id, job.id


async def test_match_jobs_uses_local_fallback_and_cache_without_api_key(tmp_path):
    factory = matching_factory(tmp_path)
    profile_id, job_id = add_profile_and_job(factory)
    matcher = HybridMatcher(Settings(anthropic_api_key=None))
    with factory() as session:
        first = await match_jobs(session, matcher)
        session.commit()
        assert first.evaluated == 1
        assert first.local_fallbacks == 1
        result = session.scalar(select(MatchResult))
        assert result.job_id == job_id
        assert result.profile_id == profile_id
        assert result.provider == "local"
        assert result.provider_status == "fallback"
        assert result.classification in {"strong", "possible"}

        second = await match_jobs(session, matcher)
        assert second.cached == 1
        assert second.evaluated == 0


async def test_hybrid_matcher_uses_anthropic_structured_output(tmp_path):
    factory = matching_factory(tmp_path)
    profile_id, job_id = add_profile_and_job(factory)
    with factory() as session:
        profile = session.get(SearchProfile, profile_id)
        job = session.get(Job, job_id)
        calls = []

        class FakeMessages:
            async def create(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(
                    content=[SimpleNamespace(
                        type="text",
                        text=(
                            '{"overall_score":88,"role_score":94,"resume_score":82,'
                            '"evidence":["Python and Airflow align"],"gaps":["Seniority unclear"]}'
                        ),
                    )],
                    usage=SimpleNamespace(input_tokens=120, output_tokens=40),
                    _request_id="req_test",
                )

        matcher = HybridMatcher(Settings(anthropic_api_key=None))
        matcher.client = SimpleNamespace(messages=FakeMessages())
        result = await matcher.evaluate(job, profile)
        assert result.provider == "anthropic"
        assert result.classification == "strong"
        assert result.request_id == "req_test"
        assert calls[0]["output_config"]["format"]["type"] == "json_schema"
        assert "selected_resume_evidence" in calls[0]["messages"][0]["content"]


def test_explicit_remote_constraint_cannot_be_overridden(tmp_path):
    factory = matching_factory(tmp_path)
    profile_id, job_id = add_profile_and_job(factory)
    with factory() as session:
        profile = session.get(SearchProfile, profile_id)
        job = session.get(Job, job_id)
        job.locations = ["New York"]
        job.description_text = "This position is on-site five days per week."
        result = local_evaluation(job, profile)
        assert result.hard_constraint_pass is False
        assert result.classification == "irrelevant"
        assert result.score == 0
