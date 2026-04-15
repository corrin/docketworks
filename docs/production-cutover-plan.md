# Production Cutover Plan

Move production from the current server (`/home/django_user`, MariaDB) to a fresh Ubuntu server (`/opt/docketworks`, PostgreSQL).

## Prerequisites

- Fresh Ubuntu 24.04 server with SSH access
- DNS control for `docketworks.site`
- Dreamhost API key (for wildcard SSL cert)
- Google Maps API key
- Xero app credentials for production (client ID, secret, webhook key, default user ID)
- GCP service account JSON key
- Gmail app password for email
- A recent MariaDB backup of `jobs_manager` from the old server

## Phase 1: Base Server Setup

Run on the new server as root.

**Reference:** `scripts/server/server-setup.sh` (installs all system packages, PostgreSQL, nginx, certbot, shared venv, repo clone)

```bash
# Bootstrap: get the setup script onto the server
sudo apt install git
git clone https://github.com/corrin/docketworks.git /tmp/docketworks-bootstrap
sudo /tmp/docketworks-bootstrap/scripts/server/server-setup.sh <dreamhost-api-key> <google-maps-api-key>
rm -rf /tmp/docketworks-bootstrap
```

The script creates `/opt/docketworks/repo` itself (proper clone as `docketworks` user).

**Verify:**
- `/opt/docketworks/repo` exists with latest `main`
- `/opt/docketworks/.venv/bin/python` works
- `psql --version` shows PostgreSQL installed
- `nginx -t` passes
- Wildcard cert at `/etc/letsencrypt/live/docketworks.site/`

## Phase 2: Create Production Instance

**Reference:** `scripts/server/instance.sh` (in the codebase)

```bash
# First run creates the credentials template — fill it out
sudo /opt/docketworks/repo/scripts/server/instance.sh create msm prod

# Edit the credentials file with production values
vim /opt/docketworks/instances/msm-prod/credentials.env

# Re-run to complete creation
sudo /opt/docketworks/repo/scripts/server/instance.sh create msm prod
```

This creates:
- OS user `dw-msm-prod`
- PostgreSQL database `dw_msm_prod` (empty — will be overwritten in Phase 4)
- Directory at `/opt/docketworks/instances/msm-prod/`
- Gunicorn service `gunicorn-msm-prod`
- Nginx config at `office.morrissheetmetal.co.nz`

**Verify:**
- `https://office.morrissheetmetal.co.nz` loads (empty app, login page)
- `systemctl status gunicorn-msm-prod` shows active

## Phase 3: Transfer MariaDB Backup

Get the production database onto the new server. Either:

**Option A:** Take a fresh backup from the old server:
```bash
# On old server:
mysqldump jobs_manager > /tmp/jobs_manager_backup.sql
scp /tmp/jobs_manager_backup.sql newserver:/tmp/
```

**Option B:** Use an existing backup file, copy it to the new server.

Then load it into MariaDB on the new server:
```bash
# Install MariaDB (needed temporarily for the migration)
sudo apt install mariadb-server

# Create the database and load the backup
sudo mysql -e "CREATE DATABASE jobs_manager CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
sudo mysql jobs_manager < /tmp/jobs_manager_backup.sql
```

**Also ensure `mysqlclient` is in the shared venv:**
```bash
sudo -u docketworks /opt/docketworks/.venv/bin/pip install mysqlclient
```

**Verify:**
```bash
sudo mysql jobs_manager -e "SELECT COUNT(*) FROM workflow_job;"
```

## Phase 4: Migrate MariaDB → PostgreSQL

**Reference:** `scripts/migrate_mariadb_to_postgres.sh` (in the codebase)

```bash
cd /opt/docketworks/instances/msm-prod/code
sudo scripts/migrate_mariadb_to_postgres.sh msm-prod jobs_manager
```

This will:
1. Stop gunicorn
2. Copy MariaDB `jobs_manager` → `dw_msm_prod`
3. Run pending Django migrations against MariaDB
4. `dumpdata` from MariaDB (no `--natural-foreign`, no `--natural-primary`)
5. Recreate PostgreSQL `dw_msm_prod` (drops the empty one from Phase 2)
6. Run migrations on PostgreSQL
7. Truncate content types, `loaddata`
8. Verify row counts match
9. Restart gunicorn

**Verify:**
- Row counts match between MariaDB and PostgreSQL (script checks this)
- `https://office.morrissheetmetal.co.nz` — log in, check Kanban board, open a job, verify client page

## Phase 5: Post-Migration Configuration

New fields added since the last production deploy that need to be set:

```bash
cd /opt/docketworks/instances/msm-prod/code
```

**Company phone number** (added in migration 0205):
```bash
sudo scripts/server/dw-run.sh msm-prod python manage.py shell -c "
from apps.workflow.models import CompanyDefaults
cd = CompanyDefaults.objects.get()
cd.company_phone = '+64 9 XXX XXXX'  # replace with actual number
cd.save()
print('Phone set:', cd.company_phone)
"
```

**Company logos** (added in migration 0206):

Upload via Django admin at `https://office.morrissheetmetal.co.nz/admin/` → Company Defaults → set Logo and Logo Wide fields.

**Google Drive folder rename** (code now looks for "DocketWorks", not "Jobs Manager"):

Rename the existing "Jobs Manager" folder in Google Drive to "DocketWorks". This preserves all existing quote spreadsheets. Can be done via the Drive web UI or:
```bash
sudo scripts/server/dw-run.sh msm-prod python manage.py shell -c "
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

## Phase 6: DNS Cutover

Point `office.morrissheetmetal.co.nz` to the new server's IP address.

## Phase 7: Post-Cutover Verification

- [ ] Log in to the application
- [ ] Kanban board loads with jobs
- [ ] Job detail page shows cost lines and events
- [ ] Client page loads with contacts
- [ ] Xero sync status — no errors
- [ ] Create a test timesheet entry
- [ ] Verify email sending works

## Phase 8: Cleanup

After running stably for at least 1 week:

- [ ] Decommission old server
- [ ] Remove MariaDB from new server: `sudo apt remove --purge mariadb-server`
- [ ] Remove `mysqlclient` from venv: `pip uninstall mysqlclient`
- [ ] Delete MariaDB backup and dump files from `/tmp/`
- [ ] Tick the pre-migration checklist in `docs/production-mysql-to-postgres-migration.md`

**Reference:** Post-migration cleanup checklist in `docs/production-mysql-to-postgres-migration.md`

## Rollback

If Phase 4 fails or verification fails: the old server is still running with the original MariaDB. Just keep using it — nothing has been modified on the old server.

If DNS has been cut over (Phase 5) but the new server has issues: revert DNS to point back at the old server.
