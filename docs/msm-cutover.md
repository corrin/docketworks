# MSM Production Cutover

Move MSM production from the old server (`/home/django_user`, MariaDB, `192.168.1.17`) to the new
server (`/opt/docketworks/instances/msm-prod`, PostgreSQL). The old server is turned off after
this migration. Every business function of the old server must work on the new one:

- DocketWorks web app (Django + Vue frontend)
- Samba file sharing (`\\msm\Dropbox`, `\\msm\MSM`, `\\msm\ADMIN`)
- CUPS printing (Brother MFC-J6945DW)
- Maestral Dropbox sync
- rclone → Google Drive backups
- Automated nightly DB backups
- Email (Gmail SMTP)
- Xero integration (OAuth + webhooks)

**Approach:** everything on the old server is preserved via the `system-data-20260417T080539Z.tar.zst`
backup. The tarball is the source of truth for OS configs, package list, Samba password database,
rclone credentials, SSH host keys, GCP credentials, and the MariaDB dump. The new architecture
(PostgreSQL, `/opt/docketworks/...`, per-instance users) replaces the app layer — the old paths
and the MariaDB → PostgreSQL migration are the only deliberate differences.

**Status going in:** `server-setup.sh --no-cert` has already been run. Pre-Cutover section below
must be complete BEFORE Monday.

---

## Pre-Cutover (do before Monday)

### 1. [x] DONE — Stage the tarball on the new server

Tarball is at `/opt/docketworks/restore/system-data.tar.zst` on the new server.

Verify if re-running:
```bash
ls -la /opt/docketworks/restore/system-data.tar.zst
# Expect: ~219MB file
```

### 2. [x] DONE — Extract the tarball

Extracted at `/opt/docketworks/restore/extracted/`.

Verify if re-running:
```bash
ls /opt/docketworks/restore/extracted/
# Expect: etc home opt root srv usr var
```

### 3. [ ] Verify CODE_DIR bug is fixed in the repo

**STATUS: BUG PRESENT on the server's repo. Fix committed on branch `docs/production-cutover` but
NOT merged to main. MUST merge PR and `git pull` on server before Phase 8.**

```bash
sudo -u docketworks git -C /opt/docketworks/repo pull
grep "CODE_DIR=" /opt/docketworks/repo/scripts/migrate_mariadb_to_postgres.sh
# Must show: CODE_DIR="$INSTANCE_DIR"  (not "$INSTANCE_DIR/code")
```

### 4. [x] DONE — Create the `corrin` user on the new server

Done. `corrin` exists (uid 1001), groups: `sudo`, `adm`, `samba_users`, SSH key installed, and
password hash restored from the tarball's `/etc/shadow` so old password works for sudo.

Verify if re-running:
```bash
ssh corrin@<new-server-ip>                    # logs in, no password prompt
ssh corrin@<new-server-ip> 'id; sudo -n true' # shows groups; sudo works with saved creds
```

---

## Prerequisites

- [x] Tarball staged and extracted at `/opt/docketworks/restore/extracted/`
- [ ] `CODE_DIR` fix merged to main and pulled on server (Pre-Cutover step 3)
- [x] SSH access to new server as `corrin` (with sudo password)
- [ ] Hyper-V console access to old server (for Phase 12 IP change)
- [ ] Dreamhost API key (panel.dreamhost.com → Home → API, `dns-*` permissions)
- [ ] Django admin email(s) for `DJANGO_ADMINS`
- [ ] Email BCC address

All other app credentials (Xero, Gmail, Anthropic/Gemini/Mistral, E2E) are in the tarball at
`/opt/docketworks/restore/extracted/usr/local/semantic-backup/env-files/jobs_manager.env`.

---

## Phase 1: Verify Base Server Setup

`server-setup.sh --no-cert` has been run. Quick sanity check:

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

## Phase 2: Install Packages and Create Service Users

### 2.1 Install every package that was on the old server

This matches the old server's `pkg.manual.txt` exactly — avahi-daemon, smbclient, poppler-utils,
antiword, python3-systemd, and everything else:

```bash
sudo apt-get update
sudo xargs -a /opt/docketworks/restore/extracted/usr/local/semantic-backup/pkg.manual.txt \
    -r apt-get install -y
```

Expect warnings for packages that are only valid for the old server's architecture — harmless.

### 2.2 Create Samba service account

`samba_users` group was already created in Pre-Cutover step 4.

```bash
# samba_user doesn't exist yet — create it
sudo useradd --system --shell /sbin/nologin --no-create-home -g samba_users samba_user
```

### 2.3 Enable services that need no config

```bash
sudo systemctl enable --now redis-server
redis-cli ping   # expected: PONG

sudo systemctl enable cups
```

Do NOT start `smbd`/`nmbd` yet — Samba config is applied in Phase 6.

---

## Phase 3: Apply Configs from the Tarball

All config comes from the extracted tarball at `/opt/docketworks/restore/extracted/`.

```bash
EXTRACT=/opt/docketworks/restore/extracted
```

### 3.1 CUPS config

```bash
sudo cp -a $EXTRACT/etc/cups/. /etc/cups/
sudo systemctl start cups
```

Verify: `lpstat -p` — Brother MFC-J6945DW visible. If absent, CUPS auto-discovers it over mDNS
within a minute.

### 3.2 Samba config (stage — Phase 6 edits the Dropbox path and activates it)

```bash
sudo cp $EXTRACT/etc/samba/smb.conf /tmp/smb.conf

# Samba password database
sudo mkdir -p /var/lib/samba/private
sudo cp $EXTRACT/var/lib/samba/private/passdb.tdb /var/lib/samba/private/
sudo cp $EXTRACT/var/lib/samba/private/secrets.tdb /var/lib/samba/private/
sudo chmod 600 /var/lib/samba/private/*.tdb
```

### 3.3 Samba share directories

MSM and ADMIN were empty on the old server — just recreate the directories. The Dropbox share's
path is on the new instance directory (set up in Phase 4) and the smb.conf is edited in Phase 6.

```bash
sudo mkdir -p /srv/samba/msm /srv/samba/admin
sudo mkdir -p /var/lib/samba/printers   # required for [print$] share
sudo chown samba_user:samba_users /srv/samba/msm /srv/samba/admin
sudo chmod 2770 /srv/samba/msm /srv/samba/admin
```

### 3.4 rclone (Google Drive) credentials

```bash
sudo mkdir -p /root/.config/rclone
sudo cp $EXTRACT/root/.config/rclone/rclone.conf /root/.config/rclone/rclone.conf
sudo chmod 600 /root/.config/rclone/rclone.conf

# Verify
sudo rclone lsd gdrive:
# Expected: lists Google Drive folders
```

### 3.5 GCP service account JSON

```bash
sudo cp $EXTRACT/home/django_user/django-integrations-18ac8d1391c0.json /tmp/gcp-credentials.json
sudo chmod 644 /tmp/gcp-credentials.json
```

`instance.sh` will copy this into the instance directory during Phase 4.

### 3.6 root SSH known_hosts

```bash
sudo mkdir -p /root/.ssh
sudo cp $EXTRACT/root/.ssh/known_hosts /root/.ssh/known_hosts
sudo chmod 600 /root/.ssh/known_hosts
```

### 3.7 SSH host keys + sshd_config (applied during Phase 13)

No action here — Phase 13 copies these from `$EXTRACT/etc/ssh/` directly to `/etc/ssh/` as part
of the LAN cutover.

---

## Phase 4: Create Production Instance

### 4.1 Scaffold the credentials file

```bash
sudo /opt/docketworks/repo/scripts/server/instance.sh prepare-config msm prod
```

### 4.2 Fill in credentials

Open the credentials file and paste values — most come from the old `.env` in the tarball:

```bash
sudo vi /opt/docketworks/config/msm-prod.credentials.env

# In another terminal, open the source:
less /opt/docketworks/restore/extracted/usr/local/semantic-backup/env-files/jobs_manager.env
```

Values:

- `GCP_CREDENTIALS=/tmp/gcp-credentials.json`
- `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`, `XERO_WEBHOOK_KEY`, `XERO_DEFAULT_USER_ID` — from old `.env`
- `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` — from old `.env`
- `DJANGO_ADMINS`, `EMAIL_BCC` — from old `.env`
- `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY` — from old `.env`
- `E2E_TEST_USERNAME`, `E2E_TEST_PASSWORD`, `XERO_USERNAME`, `XERO_PASSWORD` — from old `.env`

Do NOT copy `XERO_REDIRECT_URI`, `ALLOWED_HOSTS`, `APP_DOMAIN`, `DJANGO_SITE_DOMAIN`,
`CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` — these are generated from `--fqdn` by instance.sh.

### 4.3 Create the instance

```bash
sudo /opt/docketworks/repo/scripts/server/instance.sh create msm prod \
    --fqdn office.morrissheetmetal.co.nz
```

Creates: user `dw-msm-prod`, PostgreSQL database `dw_msm_prod` (empty), instance directory at
`/opt/docketworks/instances/msm-prod/` including `dropbox/`, gunicorn + scheduler services, and
nginx config.

Expected log: "SSL cert not yet found — skipping reload." This is correct.

Verify:

```bash
sudo systemctl status gunicorn-msm-prod
sudo systemctl status scheduler-msm-prod
# Both should be listed (gunicorn may be up and failing — no DB yet. That's fine.)
```

---

## Phase 5: Set Up Maestral (Dropbox Sync)

Maestral replaces the old Dropbox daemon. It runs as `dw-msm-prod` and syncs the MSM Dropbox
account to the instance's `dropbox/` directory.

```bash
sudo -u dw-msm-prod python3 -m venv /opt/docketworks/instances/msm-prod/maestral-venv
sudo -u dw-msm-prod /opt/docketworks/instances/msm-prod/maestral-venv/bin/pip install maestral
```

### 5.1 Link to the Dropbox account (browser required)

```bash
sudo -u dw-msm-prod /opt/docketworks/instances/msm-prod/maestral-venv/bin/maestral link -c msm
# Open the printed URL, log in as MSM's Dropbox account, paste the code back
```

### 5.2 Point Maestral at the instance dropbox directory

```bash
sudo -u dw-msm-prod /opt/docketworks/instances/msm-prod/maestral-venv/bin/maestral \
    config set local_folder /opt/docketworks/instances/msm-prod/dropbox -c msm
```

### 5.3 Install as a systemd service

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

Verify:

```bash
sudo -u dw-msm-prod /opt/docketworks/instances/msm-prod/maestral-venv/bin/maestral status -c msm
# Expected: Syncing or Up to date
```

Initial sync pulls the entire MSM Dropbox — can take a while depending on size. Subsequent
phases do not need to wait for the sync to finish, but verification in Phase 14 does.

---

## Phase 6: Activate Samba

### 6.1 Install the staged smb.conf and edit the Dropbox share

```bash
sudo cp /tmp/smb.conf /etc/samba/smb.conf
sudo vi /etc/samba/smb.conf
```

Replace the entire `[Dropbox]` section with:

```
[Dropbox]
path = /opt/docketworks/instances/msm-prod/dropbox
browseable = yes
writable = yes
create mask = 0660
directory mask = 0770
valid users = samba_user
force user = dw-msm-prod
```

`force user = dw-msm-prod` makes Samba access the (700) dropbox directory as its owner. Remove
`force group = samba_users` from the old config — `dw-msm-prod` isn't in that group and it would
break file creation.

Leave `[MSM]` and `[ADMIN]` at `/srv/samba/msm` and `/srv/samba/admin` unchanged.

### 6.2 Start Samba

```bash
sudo systemctl enable --now smbd nmbd
```

Verify:

```bash
sudo smbclient -L //localhost -U samba_user
# Should list Dropbox, MSM, ADMIN, printers, etc.
```

Samba passwords were restored from the tarball in Phase 3.2 — the existing `samba_user`
password still works.

---

## Phase 7: Load the MariaDB Dump

The MariaDB dump is in the tarball — no need to re-dump from the old server.

```bash
sudo apt install -y mariadb-server

sudo zcat /opt/docketworks/restore/extracted/usr/local/semantic-backup/mysql-dumps/jobs_manager.sql.gz \
    > /tmp/jobs_manager.sql

sudo mysql -e "CREATE DATABASE jobs_manager CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
sudo mysql jobs_manager < /tmp/jobs_manager.sql

sudo -u docketworks /opt/docketworks/.venv/bin/pip install mysqlclient
```

Verify:

```bash
sudo mysql jobs_manager -e "SELECT COUNT(*) FROM workflow_job;"
# Must be a realistic count (>0)
```

**Note on staleness:** the tarball was taken at the time of the backup. Any changes made on the
old server since that timestamp are NOT in the dump. If too much has changed, take a fresh
`mysqldump` and replace `/tmp/jobs_manager.sql` before continuing. Decide based on the tarball
timestamp vs. current state.

---

## Phase 8: Migrate MariaDB → PostgreSQL

```bash
sudo /opt/docketworks/instances/msm-prod/scripts/migrate_mariadb_to_postgres.sh msm-prod jobs_manager
```

The script: stops gunicorn, copies MariaDB data, runs pending migrations against MariaDB, dumps
all data, recreates PostgreSQL `dw_msm_prod`, runs migrations on PostgreSQL, loads data, verifies
row counts match, restarts gunicorn.

Verify:

```bash
sudo systemctl status gunicorn-msm-prod
# Check log at /opt/docketworks/instances/msm-prod/logs/ — row counts must match
```

---

## Phase 9: Post-Migration Configuration

New fields added since the last production deploy:

```bash
# Company phone (migration 0205)
sudo /opt/docketworks/repo/scripts/server/dw-run.sh msm-prod python manage.py shell -c "
from apps.workflow.models import CompanyDefaults
cd = CompanyDefaults.objects.get()
cd.company_phone = '+64 9 XXX XXXX'
cd.save()
print('Phone set:', cd.company_phone)
"
```

**Company logos** (migration 0206): upload via Django admin →
`https://office.morrissheetmetal.co.nz/admin/` → Company Defaults → Logo and Logo Wide.

**Google Drive folder rename** — code now looks for `DocketWorks` not `Jobs Manager`:

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

## Phase 10: SSL Certificate (DNS-01 via Dreamhost)

`server-setup.sh --no-cert` skipped hook setup and SSL config files. Install manually.

```bash
# Certbot hooks from the repo
sudo mkdir -p /opt/docketworks/certbot-hooks
sudo cp /opt/docketworks/repo/scripts/server/certbot-dreamhost-auth.sh \
    /opt/docketworks/certbot-hooks/auth.sh
sudo cp /opt/docketworks/repo/scripts/server/certbot-dreamhost-cleanup.sh \
    /opt/docketworks/certbot-hooks/cleanup.sh
sudo chmod 700 /opt/docketworks/certbot-hooks/*.sh

# Dreamhost API key
sudo sh -c 'echo "<your-dreamhost-api-key>" > /etc/letsencrypt/dreamhost-api-key.txt'
sudo chmod 600 /etc/letsencrypt/dreamhost-api-key.txt

# SSL config files required by nginx
sudo curl -fsSL -o /etc/letsencrypt/options-ssl-nginx.conf \
    https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf
sudo curl -fsSL -o /etc/letsencrypt/ssl-dhparams.pem \
    https://raw.githubusercontent.com/certbot/certbot/master/certbot/certbot/ssl-dhparams.pem

# Obtain cert (DNS-01 — no DNS cutover needed first)
sudo certbot certonly \
    --manual --preferred-challenges dns \
    --manual-auth-hook /opt/docketworks/certbot-hooks/auth.sh \
    --manual-cleanup-hook /opt/docketworks/certbot-hooks/cleanup.sh \
    -d "office.morrissheetmetal.co.nz" \
    --non-interactive --agree-tos --email admin@docketworks.site

sudo nginx -t && sudo systemctl reload nginx
```

Verify: `curl -sI https://office.morrissheetmetal.co.nz/` — HTTP 200 or redirect, no cert error.
(The old server still holds `192.168.1.17`, but DNS resolves to the router which still forwards
to the old server. The curl will hit the old server — that's expected until Phase 12.)

---

## Phase 11: Set Up Backup Cron Jobs

```bash
sudo crontab -e
```

Add:

```
# DocketWorks MSM production backups (runs as root)
0  0 * * * /opt/docketworks/repo/scripts/backup_db.sh msm-prod
10 0 * * * /opt/docketworks/repo/scripts/cleanup_backups.sh msm-prod --delete
```

Verify:

```bash
sudo /opt/docketworks/repo/scripts/backup_db.sh msm-prod
# Creates file in /opt/docketworks/instances/msm-prod/backups/
# and uploads to gdrive:dw_backups/msm-prod/
```

---

## Phase 12: LAN Cutover

The old server is `192.168.1.17` with hostname `msm`. LAN clients use this IP and hostname for
Samba (`\\msm\Dropbox`), the web app, and bookmarks. Give the new server that identity.

**Do this via Hyper-V console on the old server, not SSH — changing the IP will drop SSH
immediately. The Hyper-V console gives you a Linux terminal on the VM.**

### 12.1 Change old server's IP

Via Hyper-V console on the old server:

```bash
ls /etc/netplan/
# Edit the config — change 192.168.1.17 to a temporary e.g. 192.168.1.18
sudo vi /etc/netplan/01-netcfg.yaml   # filename may differ
sudo netplan apply
```

### 12.2 Give the new server the old identity

On the new server:

```bash
# 1. Change IP
sudo vi /etc/netplan/<config-file>
# Edit address to 192.168.1.17
sudo netplan apply

# 2. Change hostname
sudo hostnamectl set-hostname msm
sudo vi /etc/hosts   # update 127.0.1.1 line to: 127.0.1.1  msm

# 3. Replace SSH host keys (preserves fingerprint for existing clients)
EXTRACT=/opt/docketworks/restore/extracted
sudo cp $EXTRACT/etc/ssh/ssh_host_* /etc/ssh/
sudo chmod 600 /etc/ssh/ssh_host_*_key
sudo chmod 644 /etc/ssh/ssh_host_*_key.pub

# 4. Replace sshd_config (old server had non-default HostKeyAlgorithms +ssh-rsa,
#    PubkeyAcceptedAlgorithms +ssh-rsa for older clients)
sudo cp $EXTRACT/etc/ssh/sshd_config /etc/ssh/sshd_config

# 5. Restart sshd with the new keys and config
sudo systemctl restart sshd
```

LAN clients hit the new server at the familiar IP and hostname. `\\msm\Dropbox` and existing
shortcuts continue to work.

Public DNS (`office.morrissheetmetal.co.nz`) points to the router, and the router port-forwards
443 to `192.168.1.17`. Nothing external needs to change.

---

## Phase 13: Update Xero Configuration

The old server had two domains (`office.` + `api.office.`). The new one uses only
`office.morrissheetmetal.co.nz` with `/api/` prefix. Xero must be updated.

**Xero developer portal — redirect URI:**

- Go to myapps.developer.xero.com → MSM app → Redirect URIs
- Change `https://api.office.morrissheetmetal.co.nz/api/xero/oauth/callback/`
  to `https://office.morrissheetmetal.co.nz/api/xero/oauth/callback/`

**Xero portal — webhook delivery URL:**

- Xero portal → MSM organisation → Settings → Webhooks
- Update delivery URL to `https://office.morrissheetmetal.co.nz/api/xero/webhook/`
  (exact path: `grep -r "webhook" /opt/docketworks/instances/msm-prod/apps/workflow/urls*.py`)

---

## Phase 14: Post-Cutover Verification

Do not declare success until every item passes. "Seems fine" is not a pass.

### 14.1 Services

```bash
systemctl is-active gunicorn-msm-prod scheduler-msm-prod redis-server nginx smbd nmbd cups maestral-msm-prod
```

Expected: eight lines, each `active`.

### 14.2 DocketWorks app

- [ ] `https://office.morrissheetmetal.co.nz` loads, no cert warning
- [ ] Log in with a staff account, dashboard loads, no 500 errors

Row counts match the old server:

```bash
sudo -u dw-msm-prod psql dw_msm_prod -c "SELECT COUNT(*) FROM workflow_job;"
sudo -u dw-msm-prod psql dw_msm_prod -c "SELECT COUNT(*) FROM workflow_costline;"
sudo -u dw-msm-prod psql dw_msm_prod -c "SELECT COUNT(*) FROM workflow_client;"
```

Compare to the numbers the migration script logged in `/opt/docketworks/instances/msm-prod/logs/`.

- [ ] Open a recently-active job → cost lines load, audit trail loads
- [ ] Create a time entry for today, it appears on the job, delete it
- [ ] Open Kanban in two tabs, move a card in one — it moves in the other without refresh

### 14.3 Email

```bash
sudo /opt/docketworks/repo/scripts/server/dw-run.sh msm-prod python manage.py shell -c "
from django.core.mail import send_mail
from django.conf import settings
send_mail('DocketWorks migration test', 'New server live.',
          settings.DEFAULT_FROM_EMAIL, [settings.DEFAULT_FROM_EMAIL])
print('sent')
"
```

- [ ] Prints `sent`
- [ ] Email arrives

### 14.4 Xero

- [ ] `https://office.morrissheetmetal.co.nz/admin/` loads
- [ ] Admin → Workflow → Xero tokens → token exists, not expired
- [ ] Clients list loads (data syncs from Xero)
- [ ] `journalctl -u gunicorn-msm-prod --since "1 hour ago" | grep -i xero` — no errors

### 14.5 Samba

From a Windows machine on the LAN:

- [ ] `\\msm\Dropbox` — connects, shows existing job folders
- [ ] `\\msm\MSM` — connects (empty)
- [ ] `\\msm\ADMIN` — connects (empty)
- [ ] Create a test file in `\\msm\Dropbox`; it appears on server at
      `/opt/docketworks/instances/msm-prod/dropbox/`
- [ ] Delete it

### 14.6 Maestral

```bash
sudo -u dw-msm-prod /opt/docketworks/instances/msm-prod/maestral-venv/bin/maestral status -c msm
```

Expected: `Syncing` or `Up to date`. Not `Not linked`, `Paused`, or error.

End-to-end test:

```bash
sudo -u dw-msm-prod touch /opt/docketworks/instances/msm-prod/dropbox/migration-canary.txt
# Wait ~30s
```

- [ ] `migration-canary.txt` appears in MSM Dropbox on dropbox.com
- [ ] Delete it from server — disappears from dropbox.com within ~60s:
      `sudo -u dw-msm-prod rm /opt/docketworks/instances/msm-prod/dropbox/migration-canary.txt`

### 14.7 Printing

```bash
lpstat -p
```

Expected: Brother MFC-J6945DW `idle` or `processing`.

- [ ] Print a test page from Windows
- [ ] Page prints

### 14.8 Scanning

- [ ] Brother printer web admin → Scan → Scan to FTP/Network — confirm destination is
      `192.168.1.17` or `msm` (should be unchanged since IP/hostname preserved)
- [ ] Scan a test document, file appears at the configured destination

### 14.9 rclone

```bash
rclone lsd gdrive:
```

- [ ] Lists Google Drive, no auth error
- [ ] `rclone lsd gdrive:dw_backups/` → shows `msm-prod` folder
- [ ] `rclone ls gdrive:dw_backups/msm-prod/` → shows the Phase 11 backup file

### 14.10 Automated DB Backup

```bash
sudo /opt/docketworks/repo/scripts/backup_db.sh msm-prod
```

- [ ] Exits 0
- [ ] New `.sql.gz` in `/opt/docketworks/instances/msm-prod/backups/`
- [ ] Same file visible in `gdrive:dw_backups/msm-prod/`

### 14.11 SSL

```bash
certbot certificates
```

- [ ] Cert for `office.morrissheetmetal.co.nz`
- [ ] Expiry ≥ 60 days
- [ ] `curl -sI https://office.morrissheetmetal.co.nz/` — 200 or 302, no cert warning

### 14.12 SSH

- [ ] From a laptop that previously SSH'd to `msm`, `ssh corrin@msm` logs in with NO
      "host key changed" warning (host keys preserved in Phase 12.2)

---

## Phase 15: Cleanup (after 1 week stable)

- [ ] Decommission old server (shut down VM)
- [ ] `sudo apt remove --purge mariadb-server`
- [ ] `sudo -u docketworks /opt/docketworks/.venv/bin/pip uninstall mysqlclient`
- [ ] `sudo rm /tmp/jobs_manager.sql /tmp/smb.conf /tmp/gcp-credentials.json`
- [ ] `sudo rm -rf /opt/docketworks/restore/extracted/`
- [ ] Keep `/opt/docketworks/restore/system-data.tar.zst` archived or copy to cold storage
- [ ] Delete migration dump file in `/opt/docketworks/instances/msm-prod/logs/`
- [ ] Delete `docs/plans/old_msm_restore_plan.md` (replaced by this document)
- [ ] Delete `docs/production-cutover-plan.md` (replaced by this document)
- [ ] Update `docs/production-mysql-to-postgres-migration.md` post-migration checklist

---

## Rollback

### Before Phase 12 (LAN cutover)

The old server is untouched. Abort the new server's setup — keep using the old one.

### After Phase 12

Actions needed, in order:

1. **Via Hyper-V console on the NEW server**, change its IP off `192.168.1.17`:
   ```bash
   sudo vi /etc/netplan/<config>   # set to 192.168.1.18 or other temp
   sudo netplan apply
   ```

2. **Via Hyper-V console on the OLD server**, put it back on `192.168.1.17`:
   ```bash
   sudo vi /etc/netplan/01-netcfg.yaml
   sudo netplan apply
   ```

3. **Revert Xero redirect URI** at myapps.developer.xero.com →
   `https://api.office.morrissheetmetal.co.nz/api/xero/oauth/callback/`

4. **Revert Xero webhook delivery URL** to the previous `api.office.morrissheetmetal.co.nz` path.

5. Verify old server: `systemctl status gunicorn nginx mariadb smbd nmbd cups maestral`
   (should still be running — nothing on the old server was stopped).

6. Verify `https://office.morrissheetmetal.co.nz` and `https://api.office.morrissheetmetal.co.nz`
   both resolve to the old server and serve the old app.

MariaDB, files, and services on the old server were never modified — rollback is IP + Xero only.

---

## Troubleshooting

### gunicorn fails to start

- Check `.env`: `ls -la /opt/docketworks/instances/msm-prod/.env`
- Logs: `journalctl -u gunicorn-msm-prod -f`
- Common: DB doesn't exist yet (pre-Phase 8), missing credential in `.env`

### scheduler fails to start

- Same causes as gunicorn
- Logs: `journalctl -u scheduler-msm-prod -f`

### nginx 502 Bad Gateway

- gunicorn not running: `systemctl status gunicorn-msm-prod`
- Socket permissions: `ls -la /opt/docketworks/instances/msm-prod/gunicorn.sock`

### PostgreSQL connection refused

- `systemctl status postgresql`
- pg_hba: `sudo cat /etc/postgresql/*/main/pg_hba.conf | grep -v '^#'`

### Samba "access denied"

- Passwords restored from tarball; if wrong: `sudo smbpasswd -a samba_user`
- Share path: verify `/etc/samba/smb.conf` matches Phase 6.1
- `dw-msm-prod` owns dropbox dir: `ls -ld /opt/docketworks/instances/msm-prod/dropbox`

### Maestral not syncing

- `sudo -u dw-msm-prod .../maestral status -c msm`
- `sudo -u dw-msm-prod .../maestral start -c msm`
- Re-link if required: `sudo -u dw-msm-prod .../maestral link -c msm`
- Service logs: `journalctl -u maestral-msm-prod -f`

### rclone "token expired"

```bash
sudo rclone config reconnect gdrive:
```

### Printer not discovered

- CUPS running: `systemctl status cups`
- mDNS: `avahi-browse -a -t` — should list `Brother_MFC_J6945DW`
- Manual add: `sudo lpadmin -p Brother -E -v ipp://BRWACD564E66BF1.local:631/ipp/print`

### SSH "host key changed" warning after Phase 12

Phase 12.2 step 3 was skipped or failed. Re-run:
```bash
EXTRACT=/opt/docketworks/restore/extracted
sudo cp $EXTRACT/etc/ssh/ssh_host_* /etc/ssh/
sudo chmod 600 /etc/ssh/ssh_host_*_key
sudo chmod 644 /etc/ssh/ssh_host_*_key.pub
sudo systemctl restart sshd
```

### Xero token error after Phase 13

Xero OAuth redirect didn't match — verify the myapps.developer.xero.com entry is exactly
`https://office.morrissheetmetal.co.nz/api/xero/oauth/callback/` (trailing slash matters).
Reconnect Xero in Django admin.
