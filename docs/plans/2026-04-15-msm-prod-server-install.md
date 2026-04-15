# MSM Production Server: Pre-Cutover Install

> **This is an ops runbook, not a code implementation plan.**

**Goal:** Get the new production server fully provisioned up to (but not including) the MariaDB data migration, so cutover day is just the database transfer and DNS flip.

**Short answer:** Yes — Phase 1 (base server setup) installs Linux packages, Python, PostgreSQL, Nginx, etc. but creates **no application database**. You can safely run it now. You can optionally do Phase 2 (create empty instance) to smoke-test the stack, which does create a placeholder DB that gets overwritten on cutover day.

**Reference:** `docs/production-cutover-plan.md` covers the full cutover sequence. This plan covers Phases 1–2 only.

---

## Prerequisites: Gather Before SSH-ing In

Collect these before you start — the setup script will pause and ask for some interactively:

- [ ] SSH access to new server as `ubuntu`
- [ ] Dreamhost API key — `panel.dreamhost.com/?tree=home.api` with `dns-*` permissions
- [ ] Google Maps API key (for `shared.env`, used by geocoding features)
- [ ] Xero Client ID + Secret for MSM prod Xero app
- [ ] Xero Webhook Key
- [ ] GCP service account JSON key file
- [ ] Gmail app password for email sending

---

## Phase 1: Base Server Setup

### Step 1: Bootstrap the repo onto the server

```bash
sudo apt install git
git clone https://github.com/corrin/docketworks.git /tmp/docketworks-bootstrap
sudo /tmp/docketworks-bootstrap/scripts/server/server-setup.sh <dreamhost-api-key> <google-maps-api-key>
rm -rf /tmp/docketworks-bootstrap
```

The script pauses twice — be ready to:
1. Add the displayed SSH public key as a GitHub deploy key (Settings → Deploy keys → Add)
2. Paste the Dreamhost API key when prompted

It then automatically obtains the wildcard SSL cert (allow 2–4 min for DNS propagation).

Logs everything to `/var/log/docketworks-setup.log`.

### Step 2: Verify Phase 1

```bash
# Repo present and on main
ls /opt/docketworks/repo
git -C /opt/docketworks/repo log --oneline -3

# Python venv works
/opt/docketworks/.venv/bin/python --version

# PostgreSQL installed (system package — no application DB yet)
psql --version

# Nginx config valid, cert exists
sudo nginx -t
ls /etc/letsencrypt/live/docketworks.site/
```

---

## Phase 2 (Optional — do now or on cutover day): Create Empty Instance

This creates the OS user, directory structure, placeholder database, systemd service, and Nginx config. The instance will serve an empty login page. The placeholder DB is overwritten during the MariaDB migration on cutover day.

### Step 1: Scaffold credentials file

```bash
sudo /opt/docketworks/repo/scripts/server/instance.sh prepare-config msm prod
```

### Step 2: Fill in credentials

```bash
sudo vi /opt/docketworks/instances/msm-prod/credentials.env
```

Required fields: Xero Client ID/Secret/Webhook Key, GCP key path, Gmail address/password. Leave `XERO_DEFAULT_USER_ID` blank for now.

### Step 3: Create instance

```bash
sudo /opt/docketworks/repo/scripts/server/instance.sh create msm prod
```

### Step 4: Verify

```bash
sudo systemctl status gunicorn-msm-prod
curl -s https://msm-prod.docketworks.site/api/health
# Open https://msm-prod.docketworks.site in browser — login page, no data
```

---

## What Stays for Cutover Day

Phases 3–8 from `docs/production-cutover-plan.md`:

- Transfer MariaDB backup from old server
- Run `migrate_mariadb_to_postgres.sh` to populate PostgreSQL
- Post-migration config (phone number, logos, Google Drive rename)
- DNS flip: `office.morrissheetmetal.co.nz` → new server IP
- Post-cutover verification

**Rollback:** The old server stays untouched until Phase 8 cleanup. If anything goes wrong before DNS is cut, just keep using the old server.
