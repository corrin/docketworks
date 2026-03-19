# Development Session Startup

Steps to start a development session. For first-time setup, see [initial_install.md](initial_install.md).

This document uses my real development URLs (msm-workflow.ngrok-free.app and msm-workflow-front.ngrok-free.app). Replace with your own domains from initial setup.

## Quick Start Checklist

Each development session requires starting these services:

1. **Ngrok tunnels** (terminal 1) - both backend and frontend
2. **Django server** (VS Code debugger or terminal 2)
3. **Frontend dev server** (terminal 3, in frontend repo)
4. **Connect to Xero** (in browser, if token expired)
5. **Background scheduler** (terminal 4) - keeps Xero token alive

## Detailed Steps

### 1. Start Ngrok Tunnels

Start both backend and frontend tunnels with a single command:

```bash
ngrok start --config ngrok.yml --all
```

This uses the `ngrok.yml` in the project root. See [initial_install.md](initial_install.md) for setup instructions.

### 2. Start Django Server

VS Code: Run menu > Start Debugging (F5)

### 3. Start Frontend Dev Server

In the frontend repository:

```bash
npm run dev
```

### 4. Connect to Xero

Visit https://msm-workflow-front.ngrok-free.app/xero and click "Login with Xero" if token has expired.

### 5. Start Background Scheduler

```bash
python manage.py run_scheduler
```

## Verifying Everything is Running

- **Backend**: Visit https://msm-workflow.ngrok-free.app - should show the Django app
- **Frontend**: Visit https://msm-workflow-front.ngrok-free.app - should show the Vue app
- **ngrok tunnels**: The ngrok terminal should show both tunnels active

## Troubleshooting

| Issue | Solution |
|-------|----------|
| ngrok domain already in use | Check for other ngrok processes: `pkill ngrok` |
| Port 8000 already in use | Find process: `lsof -i :8000` and kill it |
| Port 5173 already in use | Find process: `lsof -i :5173` and kill it |
| Database connection errors | Ensure MariaDB is running: `sudo systemctl start mariadb` |
| Virtual environment not active | Run `poetry shell` in the project directory |
