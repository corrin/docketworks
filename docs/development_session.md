# Development Session Startup

Steps to start a development session. For first-time setup, see [initial_install.md](initial_install.md).

This document uses my real development URL (docketworks-msm-dev.ngrok-free.app). Replace with your own domain from initial setup.

## Quick Start Checklist

Each development session requires starting these services:

1. **Django server** (VS Code debugger or terminal 1)
2. **Frontend dev server** (terminal 2)
3. **Ngrok tunnel** (terminal 3) - single tunnel to Vite, which proxies `/api` to Django
4. **Connect to Xero** (in browser, if token expired)
5. **Background scheduler** (terminal 4) - keeps Xero token alive

## Detailed Steps

### 1. Start Django Server

VS Code: Run menu > Start Debugging (F5)

### 2. Start Frontend Dev Server

In the frontend directory:

```bash
npm run dev
```

### 3. Start Ngrok Tunnel

```bash
ngrok start --config ngrok.yml --all
```

This uses the `ngrok.yml` in the project root. A single tunnel points to Vite on port 5173; Vite proxies `/api` requests to Django on localhost:8000. See [initial_install.md](initial_install.md) for setup instructions.

### 4. Connect to Xero

Visit https://docketworks-msm-dev.ngrok-free.app/xero and click "Login with Xero" if token has expired.

### 5. Start Celery Worker + Beat

Two separate processes. The worker executes tasks; Beat dispatches periodic
tasks (Xero heartbeat, hourly sync, nightly housekeeping) on a schedule. Both
are needed.

```bash
poetry run celery -A docketworks worker --concurrency=4 --loglevel=info
poetry run celery -A docketworks beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

The `Celery Worker` and `Celery Beat` VS Code tasks (`.vscode/tasks.json`) run
the same commands.

## Verifying Everything is Running

- **App**: Visit https://docketworks-msm-dev.ngrok-free.app - should show the Vue app (Vite proxies API requests to Django)
- **ngrok tunnel**: The ngrok terminal should show the tunnel active

## Troubleshooting

| Issue | Solution |
|-------|----------|
| ngrok domain already in use | Check for other ngrok processes: `pkill ngrok` |
| Port 8000 already in use | Find process: `lsof -i :8000` and kill it |
| Port 5173 already in use | Find process: `lsof -i :5173` and kill it |
| Database connection errors | Ensure PostgreSQL is running: `sudo systemctl start postgresql` |
| Virtual environment not active | Run `poetry shell` in the project directory |
