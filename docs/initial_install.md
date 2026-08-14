# Initial Installation Guide

One-off dev-machine setup. These steps persist across restores.

## Install tools

1. **Python 3.12** — exactly 3.12 (the project pins `>=3.12,<3.13`).
2. **[uv](https://docs.astral.sh/uv/)** — manages the Python environment and dependencies.
3. **Node.js 22+ and npm** — the React frontend and Playwright E2E tests.
4. **PostgreSQL 16+** — install and ensure it is running. Allow password auth over sockets for app
   users (keep peer auth for `postgres`):
   ```
   # TYPE  DATABASE  USER      METHOD
   local   all       postgres  peer
   local   all       all       scram-sha-256
   ```
   Restart PostgreSQL after editing.
5. **Redis** — `sudo apt install redis-server && sudo systemctl enable --now redis-server`. Used as
   the Celery broker and Django shared cache on :6379.
6. **ngrok** — see [ngrok_setup.md](ngrok_setup.md) (do this first; you need the domain for `.env`).

## Clone and install

```bash
git clone https://github.com/corrin/docketworks_v2.git
cd docketworks_v2
uv sync                       # creates .venv and installs backend + dev deps
pre-commit install
cd frontend && npm install && npx playwright install --with-deps && cd ..
```

## Create the database

The database name comes from `DB_NAME` in `.env` (default `docketworks_v2`):

```bash
sudo -u postgres createdb docketworks_v2
```

`.env.example` connects as the `postgres` role over `localhost`; adjust `DB_USER` / `DB_PASSWORD` /
`DB_HOST` if your setup differs.

## Configure the environment

1. **`.env`** — copy from `.env.example` and fill in the required values. `settings.py` fails fast
   if any required variable is missing.
   ```bash
   cp .env.example .env
   ```
   At minimum set independent random values for `SECRET_KEY` and `JWT_SIGNING_KEY`, plus the
   `DB_*` values and `REDIS_URL`. Keep `JWT_SIGNING_KEY` stable across ordinary releases; rotating
   it is the deliberate logout-all control. For Xero callbacks set
   `APP_DOMAIN` and `FRONT_END_URL` to your ngrok domain (see
   [ngrok_setup.md](ngrok_setup.md)).
2. **`ngrok.yml`** — copy from `ngrok.yml.example` and fill in your authtoken + static domain
   (see [ngrok_setup.md](ngrok_setup.md)).

## Migrate

```bash
uv run python manage.py migrate
```

> v2 carries no seed fixtures of its own yet. Production data moves from v1 by `pg_dump`/restore
> (models keep v1's app labels and table names — see [`../CLAUDE.md`](../CLAUDE.md)). Xero app
> credentials and AI-provider fixtures land with their respective phases.

## Troubleshooting

1. **Dependencies** — rerun `uv sync`; check for errors. Confirm `uv run python --version` is 3.12.
2. **`.env`** — verify `SECRET_KEY`, `JWT_SIGNING_KEY`, and the `DB_*` values; `settings.py` names any missing variable.
3. **Database** — is PostgreSQL running? Does the role/database exist and match `.env`?
4. **Redis** — `redis-cli ping` should return `PONG`.
5. **ngrok** — is the tunnel up without errors? Does the domain match `APP_DOMAIN`/`FRONT_END_URL`?
   The tunnel must target :4173 (the compiled frontend preview).
6. **Django** — run `uv run python -m uvicorn config.asgi:application --port 8000` directly to see
   startup errors with `DEBUG=true`.
