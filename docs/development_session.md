# Development Session

How to start work each session and run the tests.

## Start the environment

v2 always runs the **compiled** frontend — there is deliberately no hot dev server, and Django runs
under uvicorn without `--reload` (no debugger). In VS Code:

**Terminal → Run Task → "Start E2E Environment"**

This starts each service in its own terminal panel. The tunnel process waits
for Django and the compiled frontend to answer locally before exposing the
public domain; worker and beat startup remains independent.

| Service | What it runs | Where |
|---------|--------------|-------|
| Frontend Preview (build) | `npm run preview:e2e` (`vite build && vite preview`) | :4173 (proxies `/api`, `/media` → :8000) |
| Django (uvicorn) | `python -m uvicorn config.asgi:application --port 8000` | :8000 |
| Celery Worker | `uv run celery -A config worker` | — |
| Celery Beat | `uv run celery -A config beat` (in-code schedule) | — |
| Ngrok Tunnels | readiness gate, then `ngrok start dev --config ngrok.yml` | public domain → :4173 |

Open the app at `http://localhost:4173` (or your ngrok domain). Stop the environment by killing the
task terminals (or **Terminal → Terminate Task**). Make sure no other session is already binding
:4173/:8000.

> The same compiled-build environment is used for everyday development, not only for Playwright —
> "E2E" in the task name is historical.

## Backend tests

```bash
uv run pytest
```

Settings come from `config.settings_test` (configured in `pyproject.toml`); the test database is
created automatically. Coverage is ratcheted in `pyproject.toml` — never lower it.

## E2E tests (Playwright)

Playwright runs against the compiled production build. One-off: create the E2E credentials file
(gitignored):

```bash
cd frontend
cp .env.test.example .env.test    # set E2E_TEST_USERNAME / E2E_TEST_PASSWORD
```

Then:

```bash
npm run test:e2e
```

By default Playwright builds and serves the preview itself. If the "Start E2E Environment" task is
already running, Playwright reuses that server (`reuseExistingServer` outside CI). To target a
specific environment explicitly, set `E2E_BASE_URL` (e.g. your ngrok domain) — Playwright then skips
starting its own server.

For an unattended full run after a coding session, use the repository-root command:

```bash
./scripts/ops/run_e2e.sh
```

It refuses to run when :4173, :8000, ngrok's :4040, or another Playwright run is already active.
Otherwise it runs `test:e2e:reset -- --confirm`, clears the old Playwright report/output, starts and
waits for the same five services as the VS Code task, runs every E2E spec, and stops only its own
process groups. Its exit status is the Playwright result; service logs are retained under
`logs/e2e/`. On a deployed instance the equivalent is `verify-instance.sh --e2e`
([server_setup.md](server_setup.md), ADR 0064), which needs no ngrok.

A real run leaves two records of the Xero contract it exercised. Every request and
response, verbatim, is one `XERO_WIRE` JSON line in `logs/e2e/django.log` and `worker.log`
(logger `apps.xero.wire`, DEBUG only, the token endpoint excluded); read them back with
`grep -h XERO_WIRE logs/e2e/*.log | sed 's/^.*XERO_WIRE //'`. The routes and statuses the
run reached, grouped, are in `frontend/test-results/vendor-calls.csv`, written by the
teardown before the restore. Together they are how a recording in the fake Xero (ADR 0060)
is checked against what Xero actually sent.

The recovery command remains available independently. It is a dry run unless confirmed:

```bash
cd frontend
npm run test:e2e:reset
npm run test:e2e:reset -- --confirm
```

## Before you push

The commit and push hooks run automatically. By hand, the same set plus the unit suites:

```bash
pre-commit run --all-files                        # the CI set
pre-commit run --all-files --hook-stage pre-push  # plus what CI omits
uv run pytest && (cd frontend && npm run test:unit)
```

[`../CLAUDE.md`](../CLAUDE.md) has the tier table and the standards these gates enforce.

## Environment facts worth knowing

- **A worktree needs three things the main checkout already has**:
  `MEDIA_ROOT` set in its `.env`, `ngrok.yml` copied across (untracked, so
  a fresh worktree has none and the Xero callback domain cannot come up),
  and `manage.py migrate` run against the dev database whenever a branch
  adds to `INSTALLED_APPS`.
- **The E2E user's required properties** (office-staff flag, superuser,
  wage rate exactly 45.00) are part of the restore runbook's E2E-user step
  ([restore-prod-to-nonprod.md](restore-prod-to-nonprod.md)) — a fresh
  restore does not carry them, and the specs fail in oblique ways without
  them. The timesheet specs additionally rely on restore data that already
  holds: an "Annual Leave" job findable by name whose default pay item is
  the Annual Leave pay item, `labour_cost_loading > 0` in company
  defaults, and at least one active staff member with `base_wage_rate > 0`.
- A Gemini API key lives in the local `AIProvider` row: DB only, not in the
  repo or env files. Anything needing the LLM path needs that row.
- Steel & Tube login and page selectors are credential-blocked — never
  exercised against the live portal (cutover checklist item).
- Demo-organisation expiry, tenant drift, and Xero token-material rules:
  see [xero_setup.md](xero_setup.md#demo-organisation-lifecycle).
