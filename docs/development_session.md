# Development Session

How to start work each session and run the tests.

## Start the environment

v2 always runs the **compiled** frontend — there is deliberately no hot dev server, and Django runs
with `--noreload` (no debugger). In VS Code:

**Terminal → Run Task → "Start E2E Environment"**

This starts, in parallel, each in its own terminal panel:

| Service | What it runs | Where |
|---------|--------------|-------|
| Frontend Preview (build) | `npm run preview:e2e` (`vite build && vite preview`) | :4173 (proxies `/api`, `/media` → :8000) |
| Django (runserver) | `manage.py runserver --noreload` | :8000 |
| Celery Worker | `uv run celery -A config worker` | — |
| Celery Beat | `uv run celery -A config beat` (in-code schedule) | — |
| Ngrok Tunnels | `ngrok start dev --config ngrok.yml` | public domain → :4173 |

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

## Before you push

Pre-commit runs the full gate set on commit; do not bypass it with `--no-verify`. Manually:

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy                 # strict, zero baseline
uv run lint-imports
uv run deptry .
uv run pytest
cd frontend && npm run lint && npm run format:check && npm run type-check && npm run test:unit && npm run build
```

See [`../CLAUDE.md`](../CLAUDE.md) for the standards these gates enforce.
