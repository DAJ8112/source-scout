# Referral Job Monitor — Core MVP

This local FastAPI + React application validates and scans the initial official
careers sources, persists immutable scan observations in SQLite, and exposes
actionable connector diagnostics. Successful scans reconcile durable jobs: the
first import is labeled separately, content changes are detected, one successful
absence marks a job possibly closed, and two successful absences close it. Failed
scans never advance job lifecycle state.

The web app also stores referral contacts, extracts editable text from a resume PDF,
captures job preferences, and ranks active jobs with hybrid matching. Explicit local
constraints run first; eligible jobs are evaluated by Claude using structured output.
Results are cached by profile version and job content. If Claude is unavailable or
not configured, the app falls back to deterministic local scoring.

Job actions, authentication, scheduling, durable queues, and hosted deployment are
future layers.

## Prerequisites

- Python 3.14 and `uv`
- Node.js 22 LTS and `pnpm`

## Run locally

Copy the environment example and add your Anthropic API key to enable Claude
matching. Without it, the app remains usable with local fallback matching.

```bash
cp .env.example .env
```

Export the variables before starting the backend, or load `.env` with your preferred
shell tooling. The default model is pinned and can be changed with
`ANTHROPIC_MODEL`.

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

The uploaded PDF is read in memory and discarded after text extraction. Claude is
sent job text, preferences, and selected relevant resume lines. The PDF and referral
contacts are never sent to the model provider.

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
