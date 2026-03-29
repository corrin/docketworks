# Initial Installation Guide

Dev machine setup. One-off steps that persist across restores.

## Install Tools and Dependencies

1. **Python 3.12+** — Install Python 3.12 or later.
2. **Poetry** — Install [Poetry](https://python-poetry.org/) for dependency management.
3. **Node.js 22+ and npm** — Required for the Vue frontend and Playwright tests.
4. **PostgreSQL 16+** — Install PostgreSQL and ensure it's running. Configure `pg_hba.conf` to allow password auth over sockets for app users (keep peer auth for `postgres`):
   ```
   # TYPE  DATABASE  USER      METHOD
   local   all       postgres  peer
   local   all       all       scram-sha-256
   ```
   Restart PostgreSQL after editing.

## Clone and Install

```bash
git clone https://github.com/corrin/docketworks.git
cd docketworks
python -m venv .venv
source .venv/bin/activate
poetry install
cd frontend && npm install && npx playwright install --with-deps && cd ..
```

## Create Database

```bash
sudo -u postgres ./scripts/setup_database.sh
```

## Configure Environment

1. **`.env`** — Copy from `.env.example` and configure `DB_NAME`, `DB_USER`, `DB_PASSWORD`, and all other required variables.
2. **Configure tunnel URLs:**
   ```bash
   python scripts/configure_tunnels.py --backend https://<name>-dev.ngrok-free.app --frontend https://<name>-front.ngrok-free.app
   ```
   This updates backend `.env`, frontend `.env`, and `vite.config.ts` with the correct URLs.
3. **`apps/workflow/fixtures/ai_providers.json`** — Copy from `ai_providers.json.example` and add your API keys for Claude, Gemini, and Mistral. Then `python manage.py loaddata apps/workflow/fixtures/ai_providers.json`.

## Troubleshooting

If you encounter issues:

1.  **Dependencies:** Rerun `poetry install`. Check for errors.
2.  **.env File:** Verify `DB_NAME`, `DB_USER`, `DB_PASSWORD`, Xero keys, `NGROK_DOMAIN`.
3.  **Database:** Is PostgreSQL running? Do credentials in `.env` match the `CREATE ROLE` command?
4.  **Migrations:** Run `python manage.py migrate`. Any errors?
5.  **ngrok:** Is the ngrok terminal running without errors? Does the domain match Xero's redirect URI and `.env`? Is the port correct?
6.  **Xero Config:** Double-check Redirect URI in Xero Dev portal. Check Client ID/Secret.
7.  **Django Debug Page/Logs:** Look for detailed errors when `DEBUG=True`. Check `logs/` directory.
