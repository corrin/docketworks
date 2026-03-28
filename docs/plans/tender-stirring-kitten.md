# Plan: Refine instance-setup-uat.md + instance user ergonomics

## Context

We have a draft `docs/instance-setup-uat.md` for setting up a UAT/test instance from a production backup. Major reframe: the doc is written for the **instance user** (`dw-<client>-uat`) who has SSH access with no sudo, no root, no access to other instances. They SSH in, activate their venv, source their .env, and run commands directly.

## Part 1: Instance user ergonomics (instance.sh change)

### Add to `scripts/server/instance.sh` create, after OS user creation:

1. **Symlink .venv** — `ln -s /opt/docketworks/.venv /opt/docketworks/instances/<client>-<env>/.venv`
   - Instance user activates with `source ~/.venv/bin/activate`
   - Keeps it quiet that the venv is shared (they don't have write permission anyway)

2. **Create `.bashrc`** for the instance user that auto-activates venv and sources .env:
   ```bash
   source ~/../../.venv/bin/activate  # or just source ~/.venv/bin/activate via symlink
   set -a; source ~/.env; set +a
   cd ~/code
   ```
   Wait — the home dir for instance users is not the instance dir. Let me check.

Currently: `useradd --system --shell /bin/bash --no-create-home` — home defaults to `/`.

**Fix:** Add `--home-dir "$INSTANCE_DIR"` to useradd. Then `~` = `/opt/docketworks/instances/<client>-<env>`. Only for new instances — fix msm-uat manually on the server.

### Files to modify
- `scripts/server/instance.sh` — add symlink + .bashrc setup during create

## Part 2: Rewrite instance-setup-uat.md

### Audience
The instance user `dw-<client>-uat`, SSH'd in. No sudo. No root. No dw-run.sh. Just their own environment.

### Preamble
Prerequisite: `instance.sh create` has already been run by the server admin. You have:
- SSH access as `dw-<client>-uat`
- A production backup zip file (provided by the server admin or SCP'd from prod)

### On login
If `.bashrc` auto-setup is done: venv active, .env loaded, in code dir. Otherwise:
```bash
source ~/.venv/bin/activate
set -a && source ~/.env && set +a
cd ~/code
```

### Step sequence (all commands as the instance user, no sudo)

1. **Extract backup** — `unzip ~/prod_backup_*.zip -d ~/` then `gunzip ~/prod_backup_*.json.gz`
2. **Reset database** — `python manage.py dbshell -- -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"`
3. **Apply migrations** — `python manage.py migrate`
4. **Load production data** — `python manage.py loaddata ~/prod_backup_*.json`
5. **Load fixtures** — company_defaults.json, ai_providers.json
6. **Reset passwords** — `python scripts/setup_dev_logins.py`
7. **Create dummy job files** — `python scripts/recreate_jobfiles.py`
8. **Fix shop client** — `python scripts/restore_checks/fix_shop_client.py`
9. **Verify test client** — `python scripts/restore_checks/check_test_client.py`
10. **Xero OAuth** — `cd frontend && npx tsx tests/scripts/xero-login.ts && cd ..`
11. **Configure Xero** — `python manage.py xero --setup`
12. **Sync accounts** — `python manage.py start_xero_sync --entity accounts --force`
13. **Sync pay items** — `python manage.py xero --configure-payroll`
14. **Seed Xero** — `nohup python manage.py seed_xero_from_database > logs/seed_xero_output.log 2>&1 &`
15. **Final sync** — `python manage.py start_xero_sync`
16. **Verify** — checklist
17. **Cleanup** — `rm ~/prod_backup_*`

### Key differences from current draft
- No `dw-run.sh` wrapper — user runs commands directly
- No `sudo` anywhere
- DB reset via DROP SCHEMA instead of setup_database.sh
- Backup is a prerequisite in the instance dir, not transferred via root
- All paths relative to `~` (the instance directory)

## Files to modify
- `scripts/server/instance.sh` — symlink .venv, set instance user home dir, create .bashrc
- `docs/instance-setup-uat.md` — full rewrite per above

## Verification
- All `scripts/restore_checks/*.py` exist (confirmed)
- `scripts/recreate_jobfiles.py` exists (confirmed)
- `scripts/setup_dev_logins.py` exists (confirmed)
- `manage.py dbshell` uses Django DB settings from .env
- Playwright xero-login.ts works headless (confirmed by user)
