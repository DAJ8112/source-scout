# Source Scout

A personal web app that monitors official company careers pages for new or updated roles. It matches openings against your resume and preferences, then surfaces relevant jobs alongside your referral contacts.

## Connector verification

The backend requires Python 3.14. From `backend/`, run the fixture-backed suite with:

```sh
.venv/bin/pytest -q
```

Live source validation is manual and opt-in:

```sh
REFERRALS_LIVE_TESTS=1 .venv/bin/pytest -q tests/test_live_sources.py
```

The worker processes up to three sources concurrently by default. Override that bounded
cross-source capacity with `SCAN_CONCURRENCY`; per-host throttling and the one-unfinished-scan
constraint still apply:

```sh
SCAN_CONCURRENCY=5 .venv/bin/referrals-worker
```

See [LIVE_SOURCE_STATUS.md](LIVE_SOURCE_STATUS.md) for fixture readiness and known live access
restrictions.
