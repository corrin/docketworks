# Development Session Startup

Steps to start a development session. For first-time setup, see [initial_install.md](initial_install.md).

## Start

1. **Terminal → Run Task → Start Hotfix Environment** — fans out to Vite, ngrok, Celery worker, Celery Beat in dedicated panels.
2. **Run → Start Debugging** (F5) — launches Django under the debugger.

Then visit your ngrok URL (e.g. `https://docketworks-<name>-dev.ngrok-free.app`). If the Xero token has expired, hit `/xero` and click "Login with Xero".

## What each task does

Defined in `.vscode/tasks.json`:

- **Frontend Dev Server** — `npm run dev` in `frontend/`. Vite on :5173, proxies `/api` to Django on :8000.
- **Ngrok Tunnels** — `ngrok start dev --config ngrok.yml`. Single tunnel points at Vite, not Django.
- **Celery Worker** — executes async tasks.
- **Celery Beat** — dispatches periodic tasks (Xero heartbeat, hourly sync, nightly housekeeping). Both worker and Beat are required.
