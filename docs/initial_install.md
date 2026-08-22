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

## Private configuration: Xero app, AI providers, integration settings

A fresh database has no `XeroApp` or `AIProvider` rows, and there is no admin UI to create
them — the fixtures below are the dev path (server instances get theirs rendered by
`scripts/server/instance.sh` from the root-owned credentials file instead). Copy each
`.example` to its real name, fill in the credentials, and load it. The real filenames are
gitignored because they hold live keys.

1. **`apps/ai/fixtures/ai_providers.json`** — copy from `ai_providers.json.example` and add
   your API keys for Claude, Gemini, and Mistral:
   ```bash
   cp apps/ai/fixtures/ai_providers.json.example apps/ai/fixtures/ai_providers.json
   # edit in your keys, then:
   uv run python manage.py loaddata apps/ai/fixtures/ai_providers.json
   ```
2. **`apps/xero/fixtures/xero_apps.json`** — copy from `xero_apps.json.example` and fill in
   the dev Xero app credentials: `client_id`, `client_secret`, `redirect_uri`, and
   `webhook_key`. The dev Xero credentials are shared team credentials — ask the team for
   them. Set `label` to `<your-name> xero` so your row is distinguishable from other devs'.
   The `redirect_uri` is `https://<your-ngrok-domain>/api/xero/oauth/callback/` and must
   match the redirect URI registered for the app in the Xero developer portal exactly.
   ```bash
   cp apps/xero/fixtures/xero_apps.json.example apps/xero/fixtures/xero_apps.json
   # edit in the shared credentials, then:
   uv run python manage.py loaddata apps/xero/fixtures/xero_apps.json
   ```

3. **`apps/core/fixtures/integration_settings.json`** — the install-level credentials
   (ADR 0053): the Google Maps key and, if you need it, the phone provider's login. They are
   columns on the `IntegrationSettings` row that `migrate` creates; nothing reads them from
   `.env`. Leave the phone provider unset on a dev machine so dev Celery cannot reach the
   production phone system. The E2E preflight refuses to run without the Maps key.
   ```bash
   cp apps/core/fixtures/integration_settings.json.example apps/core/fixtures/integration_settings.json
   # edit in the shared Maps key, then:
   uv run python manage.py load_integration_settings apps/core/fixtures/integration_settings.json
   ```
   The command applies each integration only while its columns are unset, so re-running it
   never overwrites what a superuser has since entered on **Admin > Integrations**.

Production data moves from v1 by `pg_dump`/restore (models keep v1's app labels and table
names — see [`../CLAUDE.md`](../CLAUDE.md)); refreshing from a production dump is
[`restore-prod-to-nonprod.md`](restore-prod-to-nonprod.md), which preserves these rows
across the load.

## Troubleshooting

1. **Dependencies** — rerun `uv sync`; check for errors. Confirm `uv run python --version` is 3.12.
2. **`.env`** — verify `SECRET_KEY`, `JWT_SIGNING_KEY`, and the `DB_*` values; `settings.py` names any missing variable.
3. **Database** — is PostgreSQL running? Does the role/database exist and match `.env`?
4. **Redis** — `redis-cli ping` should return `PONG`.
5. **ngrok** — is the tunnel up without errors? Does the domain match `APP_DOMAIN`/`FRONT_END_URL`?
   The tunnel must target :4173 (the compiled frontend preview).
6. **Xero app configured?** `uv run python -m scripts.ops.restore_checks.check_xero_app` proves
   exactly one active `XeroApp` row with a webhook key. After the OAuth login the row must be
   authorised — it holds token material (there is no admin UI; v1 showed this as
   Admin → Xero Apps → `Authorised: ✓`):
   ```bash
   uv run python manage.py shell -c "from apps.xero.models import XeroApp; app = XeroApp.objects.get(is_active=True); print('authorised:', bool(app.access_token and app.refresh_token))"
   ```
   An OAuth flow that never completes usually means the row's `redirect_uri` does not match
   the URI registered in the Xero developer portal — they must be identical.
7. **Django** — run `uv run python -m uvicorn config.asgi:application --port 8000` directly to see
   startup errors with `DEBUG=true`.
