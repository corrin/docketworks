# MSM Production Cutover Plan

Move MSM production from the old server (`/home/django_user`, MariaDB) to the new server
(`/opt/docketworks`, PostgreSQL). The old server is turned off after this migration — every
business function must work on the new one: DocketWorks app, Samba file sharing, CUPS printing,
Maestral Dropbox sync, rclone Google Drive backups, and automated DB backups.

**Status going in:** Phase 1 (`server-setup.sh --no-cert`) is already complete.

---

## Known Concerns

Identified by comparing the actual backup (`system-data-20260417T080539Z.tar.zst`) against the
new architecture. The phases below do not yet address all of these.

### C1: `api.` subdomain no longer exists

Old server has two nginx vhosts:
- `office.morrissheetmetal.co.nz` — Vue.js frontend
- `api.office.morrissheetmetal.co.nz` — Django backend

New architecture consolidates both under `office.morrissheetmetal.co.nz` with `/api/` prefix for
Django. The `api.` subdomain disappears.

The following are all configured against the old `api.` domain and will break:
- Xero OAuth redirect URI: `https://api.office.morrissheetmetal.co.nz/api/xero/oauth/callback/`
- Xero webhook delivery URL (configured in Xero portal under the MSM organisation)
- `DJANGO_SITE_DOMAIN=api.office.morrissheetmetal.co.nz` in old `.env`
- `APP_DOMAIN=api.office.morrissheetmetal.co.nz` in old `.env`
- Old SSL cert covers both `office.` and `api.office.` — new cert request only covers `office.`

### C2: `ALLOWED_HOSTS` likely wrong with custom FQDN

The backend env template sets `ALLOWED_HOSTS=__INSTANCE__.__DOMAIN__`. With `--fqdn
office.morrissheetmetal.co.nz`, if instance.sh substitutes `__INSTANCE__` and `__DOMAIN__`
literally (not the FQDN), `ALLOWED_HOSTS` becomes `msm-prod.docketworks.site` and Django
returns 400 for every request.

Old server `ALLOWED_HOSTS` also included LAN names: `msm`, `msm.local`, `192.168.1.17`.
The new template has none of these.

### C3: GCP JSON file location confirmed ✓

The GCP service account JSON is at `/home/django_user/django-integrations-18ac8d1391c0.json` on
the old server (confirmed from backup). Phase 3 has been updated with the correct path.

### C4: Miguel's SSH access — intentionally not carried over ✓

`home/miguel/.ssh/authorised_keys` in the backup contains an SSH key for
`miguelfernandoaurelius@gmail.com`. His access is not being migrated to the new server.

### C5: Credentials are available in the backup

All Phase 4 credential values are in `/usr/local/semantic-backup/env-files/jobs_manager.env`
on the old server (or in the backup). The Phase 4 prerequisite list implies they need to be
hunted down manually — they don't.

Note: several values from the old env file must NOT be copied verbatim because they reference
the old `api.` domain (see C1 and C2): `XERO_REDIRECT_URI`, `APP_DOMAIN`, `DJANGO_SITE_DOMAIN`,
`ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`.

---

---

## Prerequisites — Gather Before You Start

- [ ] SSH access to old server (192.168.1.17)
- [ ] SSH access to new server
- [ ] Dreamhost API key (for SSL cert — panel.dreamhost.com → Home → API, `dns-*` permissions)
- [ ] GCP service account JSON at `/home/django_user/django-integrations-18ac8d1391c0.json` on old server (confirmed)
- [ ] Django admin email(s) for `DJANGO_ADMINS`
- [ ] Email BCC address
- [ ] Anthropic, Gemini, Mistral API keys
- [ ] All other credentials are in `/home/django_user/jobs_manager/.env` on old server (see C5)


---

## Phase 1: Verify Base Server Setup

Already done. Quick sanity check:

```bash
ls /opt/docketworks/repo
git -C /opt/docketworks/repo log --oneline -3
/opt/docketworks/.venv/bin/python --version
psql --version
sudo nginx -t
```

If anything is wrong, re-run:
```bash
sudo /opt/docketworks/repo/scripts/server/server-setup.sh --no-cert <google-maps-api-key>
```

---

## Phase 2: Install Office Services (Packages Only)

Not installed by `server-setup.sh`. Config comes from the old server in Phase 3.

```bash
sudo apt install -y redis-server samba cups rclone
```

Create the Samba OS user and group:

```bash
sudo groupadd samba_users
sudo useradd --system --shell /sbin/nologin --no-create-home -g samba_users samba_user
```

Enable services that need no config:

```bash
sudo systemctl enable --now redis-server
redis-cli ping   # expected: PONG

sudo systemctl enable cups
```

Do NOT start `smbd`/`nmbd` yet — Samba config must be updated first (Phase 6).

---

## Phase 3: Copy Configs and Data from Old Server

Run from the **new server**:

```bash
OLD=192.168.1.17

# Samba config
scp root@$OLD:/etc/samba/smb.conf /tmp/smb.conf

# CUPS config (full directory)
ssh root@$OLD "tar czf /tmp/cups-config.tar.gz /etc/cups"
scp root@$OLD:/tmp/cups-config.tar.gz /tmp/

# rclone (Google Drive backup credentials)
scp root@$OLD:/root/.config/rclone/rclone.conf /tmp/rclone.conf

# Samba user password database
ssh root@$OLD "pdbedit -L -w" > /tmp/samba-tdbsam-export.txt
```

### Create Samba share directories

The old server has three data shares: Dropbox, MSM, ADMIN. MSM and ADMIN are currently empty —
just create the directories. Dropbox files are migrated separately in Phase 7.

```bash
sudo mkdir -p /srv/samba/msm
sudo mkdir -p /srv/samba/admin
sudo mkdir -p /var/lib/samba/printers   # required for [print$] share

sudo chown samba_user:samba_users /srv/samba/msm /srv/samba/admin
sudo chmod 2770 /srv/samba/msm /srv/samba/admin
```

### Apply CUPS config

Printer is driverless IPP (Brother MFC-J6945DW) — no driver package needed, auto-discovered on LAN.

```bash
sudo tar xzf /tmp/cups-config.tar.gz -C /
sudo systemctl start cups
```

**Verify:** `lpstat -p` — printer visible. If not shown immediately, it appears once CUPS discovers
the printer on the network.

### Copy GCP service account JSON

`instance.sh create` copies this file into the instance directory at creation time. It must exist
on the new server before Phase 4.

```bash
scp root@$OLD:/home/django_user/django-integrations-18ac8d1391c0.json /tmp/gcp-credentials.json
```

### Apply rclone config

```bash
sudo mkdir -p /root/.config/rclone
sudo cp /tmp/rclone.conf /root/.config/rclone/rclone.conf
sudo chmod 600 /root/.config/rclone/rclone.conf
```

**Verify:** `rclone lsd gdrive:` — lists Google Drive.

---

## Phase 4: Create Production Instance

### Step 1: Scaffold credentials file

```bash
sudo /opt/docketworks/repo/scripts/server/instance.sh prepare-config msm prod
```

### Step 2: Fill in credentials

```bash
sudo vi /opt/docketworks/config/msm-prod.credentials.env
```

Required: `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`, `XERO_WEBHOOK_KEY`, `XERO_DEFAULT_USER_ID`,
`GCP_CREDENTIALS` (full path to JSON key file), `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
`DJANGO_ADMINS`, `EMAIL_BCC`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`,
`E2E_TEST_USERNAME`, `E2E_TEST_PASSWORD`, `XERO_USERNAME`, `XERO_PASSWORD`.

### Step 3: Create instance

```bash
sudo /opt/docketworks/repo/scripts/server/instance.sh create msm prod --fqdn office.morrissheetmetal.co.nz
```

Creates: OS user `dw-msm-prod`, PostgreSQL database `dw_msm_prod` (empty), directory at
`/opt/docketworks/instances/msm-prod/` including `dropbox/`, gunicorn and scheduler services,
nginx config.

**Expected:** nginx logs "SSL cert not yet found — skipping reload." This is correct.

**Verify:**

```bash
sudo systemctl status gunicorn-msm-prod
sudo systemctl status scheduler-msm-prod
```

---

## Phase 5: Set Up Maestral (Dropbox Sync)

Maestral runs as `dw-msm-prod` and syncs to the instance dropbox directory.

### Install

```bash
sudo -u dw-msm-prod python3 -m venv /opt/docketworks/instances/msm-prod/maestral-venv
sudo -u dw-msm-prod /opt/docketworks/instances/msm-prod/maestral-venv/bin/pip install maestral
```

### Link to Dropbox account (interactive — requires browser)

```bash
sudo -u dw-msm-prod /opt/docketworks/instances/msm-prod/maestral-venv/bin/maestral link -c msm
# Open the printed URL, log in as MSM's Dropbox account, paste the code back
```

### Configure sync folder

```bash
sudo -u dw-msm-prod /opt/docketworks/instances/msm-prod/maestral-venv/bin/maestral config set \
    local_folder /opt/docketworks/instances/msm-prod/dropbox -c msm
```

### Install as systemd service

```bash
cat <<'EOF' | sudo tee /etc/systemd/system/maestral-msm-prod.service
[Unit]
Description=Maestral Dropbox sync for MSM production instance
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=dw-msm-prod
ExecStart=/opt/docketworks/instances/msm-prod/maestral-venv/bin/maestral start -f -c msm
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now maestral-msm-prod
```

**Verify:**

```bash
sudo -u dw-msm-prod /opt/docketworks/instances/msm-prod/maestral-venv/bin/maestral status -c msm
```

Expected: syncing or "up to date". Initial sync may take time.

---

## Phase 6: Configure Samba

Only the `[Dropbox]` share path needs updating — it moves to the Django instance directory.
MSM and ADMIN paths stay at `/srv/samba/` unchanged.

```bash
sudo cp /tmp/smb.conf /etc/samba/smb.conf
sudo vi /etc/samba/smb.conf
```

Find the `[Dropbox]` section and update:

```
[Dropbox]
    path = /opt/docketworks/instances/msm-prod/dropbox
    force user = dw-msm-prod
    # all other settings unchanged
```

`force user = dw-msm-prod` means Samba accesses the directory as the Django instance user — no
chmod needed on the 700 directory created by instance.sh.

### Restore Samba user passwords

```bash
sudo pdbedit -i smbpasswd:/tmp/samba-tdbsam-export.txt
# If that fails, set the password manually:
sudo smbpasswd -a samba_user
```

### Start Samba

```bash
sudo systemctl enable --now smbd nmbd
```

**Verify (from a Windows machine):** `\\<new-server-ip>\Dropbox` — connects and shows files.

---

## Phase 7: Migrate Job Files

rsync existing job files from the old server — faster than waiting for Maestral to sync from cloud.

```bash
OLD=192.168.1.17   # old server still has this IP until Phase 13
rsync -av --progress root@$OLD:/srv/samba/dropbox/ /opt/docketworks/instances/msm-prod/dropbox/
sudo chown -R dw-msm-prod:dw-msm-prod /opt/docketworks/instances/msm-prod/dropbox/
```

Maestral reconciles with Dropbox cloud in the background and won't re-download files that already match.

---

## Phase 8: Transfer MariaDB Backup

### On old server

```bash
mysqldump jobs_manager | gzip > /tmp/jobs_manager_$(date +%Y%m%d).sql.gz
scp /tmp/jobs_manager_$(date +%Y%m%d).sql.gz <new-server-ip>:/tmp/
```

### On new server

```bash
sudo apt install -y mariadb-server

gunzip /tmp/jobs_manager_*.sql.gz
sudo mysql -e "CREATE DATABASE jobs_manager CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
sudo mysql jobs_manager < /tmp/jobs_manager_*.sql

sudo -u docketworks /opt/docketworks/.venv/bin/pip install mysqlclient
```

**Verify:**

```bash
sudo mysql jobs_manager -e "SELECT COUNT(*) FROM workflow_job;"
# Must be a realistic count — not 0
```

---

## Phase 9: Migrate MariaDB → PostgreSQL

Verify the CODE_DIR fix is present (was patched before cutover):

```bash
grep "CODE_DIR" /opt/docketworks/instances/msm-prod/scripts/migrate_mariadb_to_postgres.sh
# Must show: CODE_DIR="$INSTANCE_DIR"
```

If not, pull latest: `sudo -u dw-msm-prod git -C /opt/docketworks/instances/msm-prod pull`

Run:

```bash
sudo /opt/docketworks/instances/msm-prod/scripts/migrate_mariadb_to_postgres.sh msm-prod jobs_manager
```

The script: stops gunicorn, copies MariaDB data, runs pending migrations against MariaDB, dumps all
data, recreates PostgreSQL `dw_msm_prod`, runs migrations on PostgreSQL, loads data, verifies row
counts match, restarts gunicorn.

**Verify:**

```bash
sudo systemctl status gunicorn-msm-prod
# Check log at /opt/docketworks/instances/msm-prod/logs/ — row counts must match
```

---

## Phase 10: Post-Migration Configuration

New fields added since the last production deploy:

```bash
# Company phone number (migration 0205)
sudo /opt/docketworks/repo/scripts/server/dw-run.sh msm-prod python manage.py shell -c "
from apps.workflow.models import CompanyDefaults
cd = CompanyDefaults.objects.get()
cd.company_phone = '+64 9 XXX XXXX'   # replace with actual number
cd.save()
print('Phone set:', cd.company_phone)
"
```

**Company logos** (migration 0206): upload via Django admin →
`https://office.morrissheetmetal.co.nz/admin/` → Company Defaults → Logo and Logo Wide.

**Google Drive folder rename** (code now looks for "DocketWorks", not "Jobs Manager"):

```bash
sudo /opt/docketworks/repo/scripts/server/dw-run.sh msm-prod python manage.py shell -c "
from apps.job.importers.google_sheets import _svc
drive = _svc('drive', 'v3')
results = drive.files().list(
    q=\"name='Jobs Manager' and mimeType='application/vnd.google-apps.folder' and trashed=false\",
    fields='files(id, name)', supportsAllDrives=True, includeItemsFromAllDrives=True,
).execute()
folders = results.get('files', [])
if not folders:
    print('No Jobs Manager folder found - may already be renamed')
else:
    fid = folders[0]['id']
    drive.files().update(fileId=fid, body={'name': 'DocketWorks'}, supportsAllDrives=True).execute()
    print(f'Renamed folder {fid} to DocketWorks')
"
```


---

## Phase 11: SSL Certificate

`server-setup.sh --no-cert` skipped hook setup and the SSL config files nginx needs. Install manually.

```bash
# Certbot hooks (from the repo)
sudo mkdir -p /opt/docketworks/certbot-hooks
sudo cp /opt/docketworks/repo/scripts/server/certbot-dreamhost-auth.sh /opt/docketworks/certbot-hooks/auth.sh
sudo cp /opt/docketworks/repo/scripts/server/certbot-dreamhost-cleanup.sh /opt/docketworks/certbot-hooks/cleanup.sh
sudo chmod 700 /opt/docketworks/certbot-hooks/*.sh

# Dreamhost API key
sudo sh -c 'echo "<your-dreamhost-api-key>" > /etc/letsencrypt/dreamhost-api-key.txt'
sudo chmod 600 /etc/letsencrypt/dreamhost-api-key.txt

# SSL config files required by nginx template
sudo mkdir -p /etc/letsencrypt
sudo curl -fsSL -o /etc/letsencrypt/options-ssl-nginx.conf \
    https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf
sudo curl -fsSL -o /etc/letsencrypt/ssl-dhparams.pem \
    https://raw.githubusercontent.com/certbot/certbot/master/certbot/certbot/ssl-dhparams.pem

# Obtain cert (DNS-01 challenge via Dreamhost — no DNS cutover needed first)
sudo certbot certonly \
    --manual --preferred-challenges dns \
    --manual-auth-hook /opt/docketworks/certbot-hooks/auth.sh \
    --manual-cleanup-hook /opt/docketworks/certbot-hooks/cleanup.sh \
    -d "office.morrissheetmetal.co.nz" \
    --non-interactive --agree-tos --email admin@docketworks.site

# Activate nginx SSL
sudo nginx -t && sudo systemctl reload nginx
```

**Verify:** `curl -sI https://office.morrissheetmetal.co.nz/` — HTTP 200 or redirect (no cert error).

---

## Phase 12: Set Up Backup Cron Jobs

```bash
sudo crontab -e
```

Add:

```
# DocketWorks MSM production backups
0  0 * * * /opt/docketworks/instances/msm-prod/scripts/backup_db.sh msm-prod
10 0 * * * /opt/docketworks/instances/msm-prod/scripts/cleanup_backups.sh msm-prod --delete
```

**Verify:**

```bash
sudo /opt/docketworks/instances/msm-prod/scripts/backup_db.sh msm-prod
# Creates file in /opt/docketworks/instances/msm-prod/backups/ and syncs to gdrive:dw_backups/msm-prod/
```

---

## Phase 13: LAN Cutover

The old server is `192.168.1.17` with hostname `msm`. LAN clients use this IP and hostname for
Samba (`\\msm\Dropbox`), web app, and any bookmarks. Give the new server the same identity.

**Do this via Hyper-V console on the old server — not SSH (you will lose the connection):**

### Step 1: Change old server's IP

On old server via Hyper-V console:

```bash
# Find the netplan config file
ls /etc/netplan/

# Edit it — change 192.168.1.17 to a temporary address e.g. 192.168.1.18
sudo vi /etc/netplan/01-netcfg.yaml   # filename may differ
sudo netplan apply
```

### Step 2: Give new server the old IP and hostname

On new server:

```bash
# Set IP to 192.168.1.17
sudo vi /etc/netplan/<config-file>
# Change address to 192.168.1.17
sudo netplan apply

# Set hostname to msm
sudo hostnamectl set-hostname msm
sudo vi /etc/hosts   # update 127.0.1.1 line to: 127.0.1.1  msm
```

LAN clients now hit the new server at the familiar IP and hostname — no changes needed on Windows
machines. `\\msm\Dropbox` and any existing shortcuts continue to work.

Public DNS (`office.morrissheetmetal.co.nz`) points to the router, and the router port-forwards 443
to `192.168.1.17`. Since the new server takes that IP, nothing external needs to change.

---

## Phase 13b: Update Xero Configuration

The new server is now live at `office.morrissheetmetal.co.nz`. The `api.` subdomain no longer
exists — update Xero before webhook deliveries accumulate failures.

**Xero developer portal — redirect URI:**

- Go to myapps.developer.xero.com → MSM app → Redirect URIs
- Change `https://api.office.morrissheetmetal.co.nz/api/xero/oauth/callback/`
  to `https://office.morrissheetmetal.co.nz/api/xero/oauth/callback/`

**Xero portal — webhook delivery URL:**

- Go to Xero portal → MSM organisation → Settings → Webhooks
- Update the delivery URL to `https://office.morrissheetmetal.co.nz/api/xero/webhook/`
  (confirm the exact path if unsure: `grep -r "webhook" /opt/docketworks/instances/msm-prod/apps/workflow/urls*.py`)

---

## Phase 14: Post-Cutover Verification

Do not declare success until every item is checked. Each section has specific expected outputs —
"seems fine" is not a pass.

---

### 14.1 Services Running

```bash
systemctl is-active gunicorn-msm-prod scheduler-msm-prod redis-server nginx smbd nmbd cups maestral-msm-prod
```

Expected: eight lines, each `active`. Fix any that aren't before continuing.

---

### 14.2 DocketWorks Application

**Login:**

- [ ] Open `https://office.morrissheetmetal.co.nz` — loads without cert warning
- [ ] Log in with a staff account — redirects to dashboard, no 500 errors

**Data integrity — spot-check row counts match old server:**

```bash
# On new server
sudo -u dw-msm-prod psql dw_msm_prod -c "SELECT COUNT(*) FROM workflow_job;"
sudo -u dw-msm-prod psql dw_msm_prod -c "SELECT COUNT(*) FROM workflow_costline;"
sudo -u dw-msm-prod psql dw_msm_prod -c "SELECT COUNT(*) FROM workflow_client;"
```

Compare against the row counts logged by the migration script in
`/opt/docketworks/instances/msm-prod/logs/`. Numbers must match.

**Job detail:**

- [ ] Open a recently-active job on the Kanban board
- [ ] Cost lines load (time entries, materials)
- [ ] Event log / audit trail loads

**Timesheet:**

- [ ] Create a time entry for today
- [ ] Entry appears on the job's cost lines
- [ ] Delete or zero it out after confirming

**WebSocket (Django Channels / Redis):**

- [ ] Open the Kanban board — no console errors about WebSocket connection
- [ ] In a second browser tab, move a job card — it moves in the first tab without refresh

---

### 14.3 Email

```bash
sudo /opt/docketworks/repo/scripts/server/dw-run.sh msm-prod python manage.py shell -c "
from django.core.mail import send_mail
from django.conf import settings
send_mail('DocketWorks migration test', 'New server is live.', settings.DEFAULT_FROM_EMAIL, [settings.DEFAULT_FROM_EMAIL])
print('sent')
"
```

- [ ] Command prints `sent` without error
- [ ] Email arrives in the configured inbox

---

### 14.4 Xero Sync

- [ ] Django admin → `https://office.morrissheetmetal.co.nz/admin/` — loads
- [ ] Admin → Workflow → Xero tokens — token exists (not expired)
- [ ] Navigate to the Clients list in the app — clients load (they sync from Xero)
- [ ] Check Django logs for Xero errors: `journalctl -u gunicorn-msm-prod --since "1 hour ago" | grep -i xero`

---

### 14.5 File Sharing (Samba)

From a Windows machine on the LAN:

- [ ] `\\msm\Dropbox` — connects and shows existing job folders
- [ ] `\\msm\MSM` — connects (share is empty, that is expected)
- [ ] `\\msm\ADMIN` — connects (share is empty, that is expected)
- [ ] Create a test file in `\\msm\Dropbox`, confirm it appears at
  `/opt/docketworks/instances/msm-prod/dropbox/` on the server:
  ```bash
  ls /opt/docketworks/instances/msm-prod/dropbox/
  ```
- [ ] Delete the test file

---

### 14.6 Maestral (Dropbox sync)

**Status:**

```bash
sudo -u dw-msm-prod /opt/docketworks/instances/msm-prod/maestral-venv/bin/maestral status -c msm
```

Expected: `Syncing` or `Up to date`. Not `Not linked`, `Paused`, or an error.

**End-to-end sync test:**

```bash
# Create a canary file
sudo -u dw-msm-prod touch /opt/docketworks/instances/msm-prod/dropbox/migration-canary.txt

# Wait ~30s then check status
sudo -u dw-msm-prod /opt/docketworks/instances/msm-prod/maestral-venv/bin/maestral status -c msm
```

- [ ] Log in to dropbox.com and confirm `migration-canary.txt` appears in the MSM Dropbox
- [ ] Delete the canary from the server and confirm it disappears from dropbox.com within ~60s:
  ```bash
  sudo -u dw-msm-prod rm /opt/docketworks/instances/msm-prod/dropbox/migration-canary.txt
  ```

---

### 14.7 Printing (CUPS)

```bash
lpstat -p
```

Expected: Brother MFC-J6945DW listed as `idle` or `processing`.

- [ ] From a Windows machine: open any document → Print → select the Brother printer → print a test page
- [ ] Page prints

If the printer isn't listed, CUPS will rediscover it on the LAN via mDNS — wait a minute and
re-check. If still absent: `sudo systemctl restart cups` then `lpstat -p` again.

---

### 14.8 Scanning (Scan-to-Folder)

The Brother MFC-J6945DW supports network scan-to-folder. Verify its scan destination still works.

- [ ] Check the Brother printer's web admin (http://the-printer-ip/) → Scan → Scan to FTP/Network →
  confirm the target path points to the new server's IP (`192.168.1.17`) or hostname (`msm`)
- [ ] Put a test document in the feeder and scan to folder
- [ ] File appears in the expected scan destination on the server

If the printer is configured to scan to a Samba share (e.g. `\\msm\Dropbox\Scans`), the IP/hostname
change in Phase 13 means the destination is already correct. If it used an FTP path with a hardcoded
IP, update the printer's scan profile to use `192.168.1.17` or `msm`.

---

### 14.9 Google Drive Backups (rclone)

```bash
rclone lsd gdrive:
```

Expected: lists Google Drive top-level folders without an auth error.

- [ ] `rclone lsd gdrive:dw_backups/` — shows the `msm-prod` folder created in Phase 12
- [ ] `rclone ls gdrive:dw_backups/msm-prod/` — shows the backup file from the Phase 12 dry run

---

### 14.10 Automated DB Backup

The cron job runs at midnight. Trigger it manually to confirm the full path works:

```bash
sudo /opt/docketworks/instances/msm-prod/scripts/backup_db.sh msm-prod
```

- [ ] Exits 0
- [ ] New `.dump` or `.sql.gz` file appears in `/opt/docketworks/instances/msm-prod/backups/`
- [ ] `rclone ls gdrive:dw_backups/msm-prod/` shows the new file

---

### 14.11 SSL Certificate

```bash
certbot certificates
```

- [ ] Shows cert for `office.morrissheetmetal.co.nz`
- [ ] Expiry is ≥ 60 days away
- [ ] `curl -sI https://office.morrissheetmetal.co.nz/` — HTTP 200 or 302, no cert warning

---

## Phase 15: Cleanup (After 1 Week Stable)

- [ ] Decommission old server
- [ ] `sudo apt remove --purge mariadb-server`
- [ ] `sudo -u docketworks /opt/docketworks/.venv/bin/pip uninstall mysqlclient`
- [ ] `rm /tmp/jobs_manager_*.sql`
- [ ] `rm /tmp/smb.conf /tmp/cups-config.tar.gz /tmp/rclone.conf /tmp/samba-tdbsam-export.txt`
- [ ] Delete dump file: check `/tmp/dw_msm-prod_dump.json` and migration log paths
- [ ] Update post-migration checklist in `docs/production-mysql-to-postgres-migration.md`

---

## Rollback

**Before LAN cutover (Phases 1–12):** Old server is untouched. If anything fails, keep using it.

**After LAN cutover (Phase 13 onward):** Swap IPs back — give the old server `192.168.1.17` again
and move the new server to a temporary address. MariaDB and files on the old server are intact.
LAN clients are back on the old system immediately.
