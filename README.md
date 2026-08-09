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
not configured, the app falls back to deterministic local scoring. Jobs can be marked
viewed or dismissed, and dismissals remain reversible.

Scheduled monitoring uses the relational database as a durable queue. A separate worker
claims due scans, runs them independently of the web process, and advances each active
source's next scan by six hours. Manual scans start immediately from the web process and
remain recoverable by the scheduled worker if that process is interrupted.

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

In another terminal, run the durable scheduler and scan worker:

```bash
cd backend
uv run referrals-worker
```

Run one worker process per database for this MVP. Queued work survives web or worker
restarts; a scan left running for more than an hour is marked interrupted and requeued.

In a third terminal:

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

## Free hosted deployment

The deployment files package the built React UI and FastAPI API into one Render Free
web service. Persistent state lives in Neon Postgres, while GitHub Actions wakes a
run-to-completion worker every six hours. Anthropic remains optional; leave its key
unset to use deterministic local matching without API charges.

1. Create a Neon project in AWS Ohio and copy its direct connection string. Keep
   connection pooling disabled because the same URL is used for Alembic migrations.
2. Add that connection string as a GitHub repository secret named `DATABASE_URL`.
3. Merge the deployment checkpoint into the repository's default branch. GitHub runs
   scheduled workflows only from the default branch.
4. In Render, create a Blueprint from this repository's `render.yaml` and provide the
   same `DATABASE_URL` plus a strong `APP_PASSWORD` when prompted. The hosted username
   is `referrals` unless `APP_USERNAME` is changed in Render.
5. After Render reports a healthy deploy, manually run the **Scheduled job scans**
   workflow once to verify database access from GitHub Actions.

The Render service can take about a minute to wake after being idle. Its local
filesystem is intentionally unused for persistent data. The Docker start command
runs Alembic migrations before starting the web server, and the scheduled workflow
runs them again safely before processing due work.

The hosted UI and API require HTTP Basic authentication. Render terminates HTTPS before
forwarding traffic to the app, so credentials are encrypted in transit. `/health` is
the only unauthenticated endpoint. Local development remains open unless
`REFERRALS_AUTH_REQUIRED=true` is set.
