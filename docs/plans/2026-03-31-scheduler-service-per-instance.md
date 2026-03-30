# Scheduler Systemd Service Per Instance

**Date:** 2026-03-31
**Status:** Approved

## Problem

Each docketworks instance needs a running APScheduler process for Xero sync, auto-archiving, scraper jobs, etc. Currently there is no systemd service for the scheduler -- it must be started manually and won't survive reboots.

## Design

Add a `scheduler-<instance>.service` systemd unit alongside the existing `gunicorn-<instance>.service`, following the same patterns.

### 1. New Service Template

`scripts/server/templates/scheduler-instance.service.template`

```ini
[Unit]
Description=Scheduler instance for docketworks __INSTANCE__
After=network.target

[Service]
User=dw-__INSTANCE__
Group=www-data
WorkingDirectory=/opt/docketworks/instances/__INSTANCE__
ExecStart=/opt/docketworks/.venv/bin/python manage.py run_scheduler
EnvironmentFile=/opt/docketworks/instances/__INSTANCE__/.env
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Key differences from gunicorn template:
- `Restart=always` with `RestartSec=10` -- the scheduler must stay alive, and should recover from crashes after a brief delay.
- Runs `python manage.py run_scheduler` instead of gunicorn.
- No `--workers` or socket binding -- it's a single blocking process.

### 2. Wire Into instance.sh

**create:** After installing the gunicorn service, install and start `scheduler-<instance>.service` using the same sed/systemctl pattern.

**destroy:** Stop and remove `scheduler-<instance>.service` alongside gunicorn. Update the confirmation message to list it.

**list:** Show scheduler status alongside gunicorn status.

### 3. Add DJANGO_RUN_SCHEDULER to .env Template

Add `DJANGO_RUN_SCHEDULER=true` to `scripts/server/templates/env-instance.template` under the feature flags section. This ensures `AppConfig.ready()` registers jobs when gunicorn starts (not strictly needed since `run_scheduler` calls the registration methods directly, but keeps the environment consistent and enables the ready()-based path as a safety net).

### 4. Retrofit Existing Instances

For instances already running (e.g. msm-uat), no need to recreate. Add the scheduler manually:

```bash
# Add the env var to the instance's .env
echo 'DJANGO_RUN_SCHEDULER=true' >> /opt/docketworks/instances/msm-uat/.env

# Install the service (after the template exists in the codebase)
sed 's|__INSTANCE__|msm-uat|g' \
    /opt/docketworks/instances/msm-uat/scripts/server/templates/scheduler-instance.service.template \
    > /etc/systemd/system/scheduler-msm-uat.service
systemctl daemon-reload
systemctl enable scheduler-msm-uat
systemctl start scheduler-msm-uat
```

### 5. Files Changed

| File | Change |
|------|--------|
| `scripts/server/templates/scheduler-instance.service.template` | New file |
| `scripts/server/templates/env-instance.template` | Add `DJANGO_RUN_SCHEDULER=true` |
| `scripts/server/instance.sh` | Wire scheduler service into create, destroy, list |
