# Initial Installation Guide

Start here if you're new to the repo. This doc covers dev machine setup and links to other docs in the right order.

## Sequence

1. **This file** — First-Time Setup below (tools, venv, database, .env, ngrok)
2. **[xero_setup.md](xero_setup.md)** — Create a Xero developer app and configure the Xero org (earnings rates, leave types, payroll calendar)
3. **[restore-prod-to-nonprod.md](restore-prod-to-nonprod.md)** — Restore production data (steps 1-14)
4. **This file** — "Every Restore" section below (start ngrok, dev server, frontend)
5. **[restore-prod-to-nonprod.md](restore-prod-to-nonprod.md)** — Continue from step 15 (Xero OAuth onwards)

---

## First-Time Setup (New Developer)

One-off steps when setting up a new dev machine. These persist across restores.

### Defining Your Application Name

Choose a short client code and environment suffix. For example, if your company is "MSM Sheetmetal", your client code is `msm` and for development the database name would be `dw_msm_dev`.

The naming convention is `dw_<client>_<env>` where:
- `<client>` is your short company code (e.g., `msm`)
- `<env>` is the environment: `dev`, `test`, or `prod`

This constructs:
- Your PostgreSQL database name (e.g., `dw_msm_dev`)
- Your PostgreSQL database username (e.g., `dw_msm_dev`)
- Part of your ngrok subdomain (e.g., `docketworks-msm-dev.ngrok-free.app`)
- Part of your Xero App name (e.g., `docketworks-msm Development`)

**Decide on your client code now and use it consistently throughout this guide.**

### Install Tools and Dependencies

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
5. **ngrok** — Sign up at [ngrok.com](https://ngrok.com/) and install the client. You need static domains for backend and frontend callbacks. See [ngrok.com](https://ngrok.com/) for free-tier static domain options.

### Clone and Install

```bash
git clone https://github.com/corrin/docketworks.git
cd docketworks
python -m venv .venv
source .venv/bin/activate
poetry install
cd frontend && npm install && npx playwright install --with-deps && cd ..
```

### Create Database

```bash
sudo -u postgres ./scripts/setup_database.sh
```

### Configure Environment

1. **`.env`** — Copy from `.env.example` and configure `DB_NAME`, `DB_USER`, `DB_PASSWORD`, and all other required variables.
2. **Configure tunnel URLs:**
   ```bash
   python scripts/configure_tunnels.py --backend https://<name>-dev.ngrok-free.app --frontend https://<name>-front.ngrok-free.app
   ```
   This updates backend `.env`, frontend `.env`, and `vite.config.ts` with the correct URLs.
3. **`apps/workflow/fixtures/ai_providers.json`** — Copy from `ai_providers.json.example` and add real API keys for Claude, Gemini, and Mistral.

### Set Up Xero App

Follow [xero_setup.md](xero_setup.md) to create a Xero developer app and add credentials to `.env`.

### Target State

You should end up with:
1. The backend running on port 8000
2. ngrok mapping a public domain to the backend
3. ngrok mapping a public domain to the frontend
4. The frontend running on port 5173
5. The database fully deleted, then restored from prod
6. All migrations applied
7. Linked to the dev Xero
8. Key data from prod's restore synced to the dev Xero
9. The Xero token is locked in via `python manage.py run_scheduler`
10. LLM keys set up and configured
11. Playwright tests pass

---

## Every Restore

Run these before the Xero OAuth step (step 15 in [restore-prod-to-nonprod.md](restore-prod-to-nonprod.md)). The Xero OAuth flow requires ngrok, the backend, and the frontend all running.

### Start ngrok Tunnel

Note, this is often already running. Check first.

```bash
ngrok http 5173 --domain=your-domain.ngrok-free.app
```

**Check:** The ngrok tunnel should show "Forwarding" status with a public URL. Vite proxies `/api` to Django.

### Start Development Server

**Check if server is already running:**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000
```

**Windows (PowerShell):**

```powershell
curl.exe -s -o $null -w "%{http_code}`n" http://localhost:8000
```

If you get 302, **SKIP this step** - server is already running.

**If curl fails, ask the user to start the server:**

In VS Code: Run menu > Start Debugging (F5)

**Check:** Re-run the curl command above - should return 302.

### Start Frontend

**Check if frontend is already running:**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5173
```

**Windows (PowerShell):**

```powershell
curl.exe -s -o $null -w "%{http_code}`n" http://localhost:5173
```

If you get 200, **SKIP this step** - frontend is already running.

**If curl fails, start the frontend (in separate terminal):**

```bash
cd frontend && npm run dev
```

**Check:** Re-run the curl command above - should return 200.

---

## Windows-Specific Alternatives

These replace the bash commands in the restore doc when running on Windows/PowerShell.

### Extract Backup (PowerShell)

```powershell
Expand-Archive -Path restore\prod_backup_YYYYMMDD_HHMMSS_complete.zip -DestinationPath restore -Force
```

### Environment Variables (PowerShell)

```powershell
Select-String -Path .env -Pattern '^(DB_NAME|DB_USER|DB_PASSWORD)='
```

### Seed Xero (PowerShell)

```powershell
Start-Process -FilePath python -ArgumentList "manage.py", "seed_xero_from_database" -RedirectStandardOutput logs\seed_xero_output.log -RedirectStandardError logs\seed_xero_output.log
Get-Content logs\seed_xero_output.log -Tail 50 -Wait
```

## Troubleshooting

If you encounter issues:

1.  **Dependencies:** Rerun `poetry install`. Check for errors.
2.  **.env File:** Verify `DB_NAME`, `DB_USER`, `DB_PASSWORD`, Xero keys, `NGROK_DOMAIN`.
3.  **Database:** Is PostgreSQL running? Do credentials in `.env` match the `CREATE ROLE` command?
4.  **Migrations:** Run `python manage.py migrate`. Any errors?
5.  **ngrok:** Is the ngrok terminal running without errors? Does the domain match Xero's redirect URI and `.env`? Is the port correct?
6.  **Xero Config:** Double-check Redirect URI in Xero Dev portal. Check Client ID/Secret.
7.  **Django Debug Page/Logs:** Look for detailed errors when `DEBUG=True`. Check `logs/` directory.
