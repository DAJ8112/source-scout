# Referral Job Monitor — Connector Lab

The current foundation is a local FastAPI + React application that validates and
scans the three initial official careers sources, persists immutable scan
observations in SQLite, and exposes actionable connector diagnostics. Successful
scans also reconcile durable jobs: the first import is labeled separately, content
changes are detected, one successful absence marks a job possibly closed, and two
successful absences close it. Failed scans never advance job lifecycle state.

Profile and resume management, referral contacts, matching, the product feed,
authentication, scheduling, durable queues, and hosted deployment are the next MVP
layers and are not implemented yet.

## Prerequisites

- Python 3.14 and `uv`
- Node.js 22 LTS and `pnpm`

## Run locally

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

In another terminal:

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Open <http://localhost:5173>. Vite proxies `/api` to FastAPI on port 8000.

## Verify

```bash
cd backend && uv run pytest && uv run ruff check app tests
cd frontend && pnpm test -- --run && pnpm typecheck && pnpm build
```

Manual live-source smoke tests are deliberately excluded from CI:

```bash
cd backend
REFERRALS_LIVE_TESTS=1 uv run pytest -m live -q
```

Live tests assert successful nonzero traversal, never volatile exact counts.
Sites can change or restrict automated access; a blocked or drifted source is
reported as `setup_required` with diagnostics rather than bypassed.
