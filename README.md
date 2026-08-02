# Docketworks v2

Job/docket management for jobbing shops — businesses that do lots of small-to-medium jobs for many
clients (fabrication shops, trades, IT consultancies). Jobs on a Kanban board, quoting, time
tracking, materials, invoicing and payroll reporting, with Xero handling the accounting around it.

This is a full rewrite of [`../docketworks`](../docketworks) (v1) with no functional changes:
Django 6 + django-ninja backend, React/Vite frontend, PostgreSQL, Redis, Celery. See
[`CLAUDE.md`](CLAUDE.md) for the architecture and the rules that govern changes, and
[`docs/adr/`](docs/adr/README.md) for the decisions behind them.

## Requirements

- **Python 3.12** (managed with [uv](https://docs.astral.sh/uv/))
- **Node.js 22+** (frontend)
- **PostgreSQL 16+**
- **Redis** (Celery broker + Django cache)
- **ngrok** — required for Xero OAuth callbacks (a free static domain is enough)

## Quick start

```bash
uv sync                                  # backend deps (creates .venv)
cp .env.example .env                     # then configure DB_*, SECRET_KEY, etc.
sudo -u postgres createdb docketworks_v2 # match DB_NAME in .env
uv run python manage.py migrate

cd frontend && npm install && npx playwright install --with-deps && cd ..

cp ngrok.yml.example ngrok.yml           # fill in authtoken + your static domain
pre-commit install
```

Full setup detail (Postgres/Redis, ngrok domains, Xero) is in
[docs/initial_install.md](docs/initial_install.md) and [docs/ngrok_setup.md](docs/ngrok_setup.md).

## Starting

v2 always runs the **compiled** frontend (no hot dev server). In VS Code:
**Terminal → Run Task → "Start E2E Environment"**. This starts, in parallel:

- the production frontend build on **:4173** (`vite preview`, proxies `/api` → :8000)
- Django on **:8000** (`runserver --noreload` — no debugger)
- Celery worker + beat
- a single ngrok tunnel to :4173 (Xero callbacks)

Equivalent manual commands:

```bash
uv run python manage.py runserver --noreload          # backend :8000
uv run celery -A config worker --concurrency=4 -l info
uv run celery -A config beat -l info
ngrok start dev --config ngrok.yml
cd frontend && npm run preview:e2e                     # compiled build :4173
```

To run Playwright against an already-running environment, set `E2E_BASE_URL` (see
[docs/development_session.md](docs/development_session.md)).

## Gates (all enforced in CI and pre-commit)

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy                 # strict, zero baseline
uv run lint-imports         # layer contract
uv run deptry .
uv run pytest
```

Frontend: `npm run lint` (oxlint), `npm run format:check`, `npm run type-check`,
`npm run test:unit`, `npm run build`. See [`CLAUDE.md`](CLAUDE.md) — never weaken or baseline a gate.

## Documentation

- [`CLAUDE.md`](CLAUDE.md) — architecture, coding standards, porting rules (read before non-trivial work)
- [`docs/README.md`](docs/README.md) — documentation index and new-developer setup order
- [`docs/adr/`](docs/adr/README.md) — architectural decision records

## License

Proprietary. For usage or inquiries, contact the repository maintainer.
