# Scheduler Service Per Instance - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a systemd scheduler service to every docketworks instance so APScheduler runs reliably and survives reboots.

**Architecture:** New service template mirroring the gunicorn pattern. Wire into instance.sh create/destroy/list. Add DJANGO_RUN_SCHEDULER to .env template.

**Tech Stack:** Bash, systemd

---

### Task 1: Create scheduler service template

**Files:**
- Create: `scripts/server/templates/scheduler-instance.service.template`

- [ ] **Step 1: Create the service template**

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

- [ ] **Step 2: Commit**

```bash
git add scripts/server/templates/scheduler-instance.service.template
git commit -m "feat: add scheduler systemd service template"
```

---

### Task 2: Add DJANGO_RUN_SCHEDULER to .env template

**Files:**
- Modify: `scripts/server/templates/env-instance.template`

- [ ] **Step 1: Add env var under feature flags**

Add `DJANGO_RUN_SCHEDULER=true` at the end of the feature flags section in `env-instance.template`.

- [ ] **Step 2: Commit**

```bash
git add scripts/server/templates/env-instance.template
git commit -m "feat: enable scheduler by default in instance .env template"
```

---

### Task 3: Wire scheduler into instance.sh create

**Files:**
- Modify: `scripts/server/instance.sh`

- [ ] **Step 1: Add scheduler service install after gunicorn install**

After the block that installs `gunicorn-$INSTANCE.service` (lines 350-357), add an identical block for `scheduler-$INSTANCE`:

```bash
log "Installing systemd service scheduler-$INSTANCE..."
sed \
    -e "s|__INSTANCE__|$INSTANCE|g" \
    "$TEMPLATE_DIR/scheduler-instance.service.template" \
    > "/etc/systemd/system/scheduler-$INSTANCE.service"
systemctl daemon-reload
systemctl enable "scheduler-$INSTANCE"
systemctl restart "scheduler-$INSTANCE"
```

- [ ] **Step 2: Add scheduler to summary output**

Add `log "  Scheduler: scheduler-$INSTANCE"` to the summary block at the end of `do_create`.

- [ ] **Step 3: Commit**

```bash
git add scripts/server/instance.sh
git commit -m "feat: install scheduler service on instance create"
```

---

### Task 4: Wire scheduler into instance.sh destroy

**Files:**
- Modify: `scripts/server/instance.sh`

- [ ] **Step 1: Add scheduler to confirmation message**

In the `do_destroy` function, add `echo "    - Service:   scheduler-$INSTANCE"` after the gunicorn line in the confirmation prompt.

- [ ] **Step 2: Add scheduler stop/remove after gunicorn stop/remove**

After the block that stops and removes `gunicorn-$INSTANCE` (lines 411-419), add an identical block for `scheduler-$INSTANCE`:

```bash
if systemctl is-active --quiet "scheduler-$INSTANCE" 2>/dev/null; then
    echo "=== Stopping Scheduler service ==="
    systemctl stop "scheduler-$INSTANCE"
fi
if [[ -f "/etc/systemd/system/scheduler-$INSTANCE.service" ]]; then
    echo "=== Removing scheduler service ==="
    systemctl disable "scheduler-$INSTANCE" 2>/dev/null || true
    rm -f "/etc/systemd/system/scheduler-$INSTANCE.service"
    systemctl daemon-reload
fi
```

- [ ] **Step 3: Commit**

```bash
git add scripts/server/instance.sh
git commit -m "feat: remove scheduler service on instance destroy"
```

---

### Task 5: Wire scheduler into instance.sh list

**Files:**
- Modify: `scripts/server/instance.sh`

- [ ] **Step 1: Add scheduler status column**

In `do_list`, add a `SCHEDULER` column. Check `systemctl is-active --quiet "scheduler-$name"` alongside the existing gunicorn check and display both statuses.

Update the header:
```bash
printf "%-15s %-12s %-12s %-20s %-40s\n" "INSTANCE" "GUNICORN" "SCHEDULER" "BRANCH" "URL"
printf "%-15s %-12s %-12s %-20s %-40s\n" "--------" "--------" "---------" "------" "---"
```

Add scheduler status lookup alongside the existing gunicorn check:
```bash
local sched_status
if systemctl is-active --quiet "scheduler-$name" 2>/dev/null; then
    sched_status="running"
elif systemctl is-enabled --quiet "scheduler-$name" 2>/dev/null; then
    sched_status="stopped"
else
    sched_status="no service"
fi
```

Update the printf to include it:
```bash
printf "%-15s %-12s %-12s %-20s %-40s\n" "$name" "$status" "$sched_status" "$branch" "https://$name.$DOMAIN"
```

- [ ] **Step 2: Commit**

```bash
git add scripts/server/instance.sh
git commit -m "feat: show scheduler status in instance list"
```
