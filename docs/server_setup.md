# Server Setup

Multi-instance server on `192.9.188.248` (Oracle Cloud, Ubuntu 24.04 ARM/aarch64).
Each client gets their own subdomain, database, and Xero credentials.

```
Architecture:
  DNS: *.docketworks.site → 192.9.188.248
       docketworks.site   → 192.9.188.248
  Website:     https://docketworks.site        → /opt/docketworks-website/ (separate repo, Astro/PM2)
  Instance "msm":  https://msm.docketworks.site   → /opt/docketworks/instances/msm/
  Instance "acme": https://acme.docketworks.site   → /opt/docketworks/instances/acme/
  Each instance: own DB, .env, Gunicorn service, Nginx server block
  Single wildcard SSL cert covers all subdomains
```

---

## Part A: Prerequisites

- SSH access to `192.9.188.248` as `ubuntu` user
- Wildcard DNS: `*.docketworks.site` A record → `192.9.188.248`
- Per instance:
  - Xero OAuth app credentials (client ID + secret)
  - These are generated automatically: Django `SECRET_KEY`, DB password

---

## Part B: Base Server Setup (one-time)

Run the automated base setup script as `ubuntu` with sudo. This installs all
system dependencies, creates the `docketworks` user, configures the firewall,
and sets up the base Nginx config.

Every box needs a Dreamhost API key (all customer DNS lives on Dreamhost,
so DNS-01 challenges work uniformly). Every box also needs an explicit
decision about which domains it serves certs for: one or more
`--cert-domain` flags, or `--no-cert-domain` for a DR-posture box.

```bash
# First install on UAT (wildcard cert covering every *-uat.docketworks.site):
sudo ./scripts/server/server-setup.sh \
    --dreamhost-key   "$DREAMHOST_API_KEY" \
    --cert-domain     '*.docketworks.site'

# Same UAT box also serving a client-branded URL (additional cert):
sudo ./scripts/server/server-setup.sh \
    --dreamhost-key   "$DREAMHOST_API_KEY" \
    --cert-domain     '*.docketworks.site' \
    --cert-domain     uat-office.morrissheetmetal.co.nz

# First install on a prod box (one cert for the customer FQDN):
sudo ./scripts/server/server-setup.sh \
    --dreamhost-key   "$DREAMHOST_API_KEY" \
    --cert-domain     office.heuserlimited.com

# First install on a DR box (no certs obtained):
sudo ./scripts/server/server-setup.sh \
    --dreamhost-key   "$DREAMHOST_API_KEY" \
    --no-cert-domain

# Re-run on an already-configured server (reads everything from saved files):
sudo ./scripts/server/server-setup.sh
```

The Dreamhost key and cert-domain list are persisted on first install at
`/etc/letsencrypt/dreamhost-api-key.txt` and `/etc/letsencrypt/cert-domains.txt`
respectively. Re-runs read both from disk, so `deploy.sh` can
re-invoke `server-setup.sh` with no flags on every deploy.

To add or remove a single cert-domain on an already-configured server,
edit `/etc/letsencrypt/cert-domains.txt` (one FQDN per line; blanks and
`#`-comments ignored) and re-run `server-setup.sh`.

The script logs every action to `/var/log/docketworks-setup.log` with timestamps,
and writes a manifest of installed software to `/opt/docketworks/server-manifest.txt`.

It is **idempotent** — safe to re-run on an already-configured server.

### What it installs

- etckeeper (tracks /etc changes in git)
- Python 3.12 + dev packages
- Node.js 22 (NodeSource)
- PostgreSQL server (configured for password auth over sockets)
- Redis (per-instance Celery broker databases; database 2 is the shared cache)
- Nginx, with per-IP rate-limit zones for the two authentication endpoints
- Certbot + Dreamhost DNS hook scripts (for wildcard cert auto-renewal)
- pnpm (via corepack) and pm2 (for marketing website)
- Claude Code CLI
- Build dependencies (build-essential, libpq-dev, pkg-config)
- uv (for the `docketworks` system user; release builds run `uv sync --frozen`)
- UFW: default-deny incoming on IPv4 and IPv6; only rate-limited SSH, 80 and 443 open
- rpcbind disabled, socket and service — Ubuntu ships it publicly bound on
  port 111 and no docketworks host uses NFS
- Fail2ban: an sshd jail plus two jails watching the nginx access logs for
  HTTP 401s on `POST /api/accounts/token/` (10/10min, 1h ban) and
  `POST /api/accounts/token/refresh/` (60/10min, 15min ban), banning via UFW.
  Only genuine 401s on those exact routes count — nginx's own 429
  rate-limit responses never cause a ban.
- Automatic security updates, rebooting at 04:30 server-local — deliberately
  clear of the backup timers (02:30 plus up to 45 minutes of jitter)

### What happens on first install

The script:

- Persists `--dreamhost-key` to `/etc/letsencrypt/dreamhost-api-key.txt`.
- Persists every `--cert-domain` (or the `--no-cert-domain` decision) to `/etc/letsencrypt/cert-domains.txt`.
- Iterates over the cert-domains list and obtains each cert via Dreamhost DNS-01 (~2-4 min per cert for DNS propagation). Wildcards include the apex automatically.
- Configures and starts Nginx with the first cert as the default-server fallback (DR boxes get a port-80-only default).

Certs auto-renew via `certbot renew` using the same Dreamhost DNS hooks.

---

## Part C: Creating an Instance

### Automated (recommended)

```bash
# Step 1: scaffold credentials and CompanyDefaults config
# (--seed selects the seeded CompanyDefaults template; omit for a prospect)
sudo scripts/server/instance.sh prepare-config <client> <env> [--seed]

# Step 2: fill in both root-owned configuration files
sudoedit /opt/docketworks/config/<client>-<env>.credentials.env
sudoedit /opt/docketworks/config/<client>-<env>.company-defaults.json

# Step 3: create the instance
sudo scripts/server/instance.sh create <client> <env> --no-start

# Step 4 (fresh instances): create the first login interactively.
# Nothing scripted — a stored bootstrap password is a liability, and
# instances restored from an existing database already have their staff.
sudo scripts/server/dw-run.sh <client>-<env> python manage.py createsuperuser

# Re-run after root-owned credential edits
sudo scripts/server/instance.sh reconfigure <client> <env>
```

### What instance.sh creates

`instance.sh create` is the supported provisioning path. It creates the OS
user, database, generated `.env` (including a per-instance Redis broker
database, so one instance's celery worker can never consume another's
tasks), per-instance data directories, service units, backup timers,
sudoers drop-in, nginx config, and `app` symlink to a shared
`/opt/docketworks/releases/<sha>` release. App code, Python dependencies,
and frontend builds live in the shared release, not in the instance
directory. Integration credentials (Xero app, AI provider keys, phone
provider) are loaded into the instance's database as fixture rows; the
loaders skip anything a restored database already carries.

### Per-instance test database

`create` (and `reconfigure`, for instances that predate this) also provisions
a per-tenant pytest role: a `dw_<client>_<env>_test` Postgres role with
`CREATEDB`, its credentials written into the instance `.env` as
`TEST_DB_USER` and `TEST_DB_PASSWORD`. The role owns no database at rest:
the suite runs under xdist, so pytest itself creates and drops the throwaway
`dw_<client>_<env>_test` database (one clone per worker) — which is why the
role carries `CREATEDB` instead of a single pre-provisioned database.
Running `pytest` on the server therefore needs no cluster-wide test role,
each tenant's test runs are confined to databases its own role creates and
never touch the app database, and `destroy` drops the test role along with
every database it owns.

---

## Part C.1: Post-Create Setup

After `instance.sh create`, the instance has infrastructure plus its
configured Company and CompanyDefaults. Choose the next data workflow:

### Path A: Backup restore (e.g. MSM demo)

For instances that need production data, follow
[restore-prod-to-nonprod.md](restore-prod-to-nonprod.md).

### Path B: Fresh instance

The full variant-specific sequences live in
[instance-setup-demo.md](instance-setup-demo.md) and
[instance-setup-production.md](instance-setup-production.md); the Xero-side
prerequisites both depend on are [xero_setup.md](xero_setup.md).

Create the first login (`createsuperuser`, step 4 above), complete Xero
OAuth in the browser, then run:

```bash
sudo scripts/server/dw-run.sh <client>-<env> python manage.py finalize_instance_onboarding
```

The root-owned `/opt/docketworks/config/<name>.company-defaults.json` is the
durable tenant configuration; repo fixtures are only templates.

---

## Part D: Managing Instances

### Deploy (update to latest code)

```bash
sudo scripts/server/deploy.sh <instance>     # deploy the instance's tracked ref
sudo scripts/server/deploy.sh --all          # every instance, each on its own ref
```

Each instance records its tracked git ref alongside its current and previous
SHA in `/opt/docketworks/instances/<instance>/deploy-state.env`
(`origin/production` for prod, `origin/main` for UAT, per ADR 0029).
`deploy.sh` fetches, resolves each target instance's ref, builds or reuses
the shared `/opt/docketworks/releases/<sha>` release, then per instance:
takes a pre-deploy DB backup, stops runtime services, switches `app` to the
release, migrates, re-renders units and nginx from the current templates,
and restarts — you don't run anything per service.

To change what an instance tracks, deploy once with an explicit ref:

```bash
sudo scripts/server/deploy.sh msm-uat --ref origin/main
```

The explicit ref is persisted with the successful deployment state, so
subsequent bare deploys remember it — and a bare `--all` can therefore send
different refs to different instances. `--ref` against a `*-prod` instance
requires interactive confirmation (or `--allow-prod-ref`).

Run `instance.sh reconfigure` instead when root-owned credentials changed.

#### When a migration fails

A failed `migrate` leaves that instance's services **stopped**; there is no
automatic rollback. Django records each successful migration in the instance
database's `django_migrations` table, so the database may be partially
migrated. Never switch only the `app` symlink back after a migration
failure — old code can be incompatible with the partially migrated database.
Diagnose in the failed release first:

```bash
sudo scripts/server/dw-run.sh <client>-<env> python manage.py showmigrations
```

List the releases previously installed on the instance:

```bash
sudo scripts/server/instance.sh history <client> <env>
```

Then roll back. The default (`--latest-db`) rolls back code while retaining
the latest database and applying Django reverse migrations;
`--restore-backup` instead restores the database snapshot paired with the
target release:

```bash
sudo scripts/rollback.sh <client>-<env> <previous-8-char-sha>
sudo scripts/rollback.sh <client>-<env> <previous-8-char-sha> --restore-backup
```

Both modes take a fresh safety backup first. A paired restore requires the
target release's pre-deploy backup; a `--no-backup` deploy may mean that
pair does not exist.

#### Release lifecycle

Releases are built in place at `/opt/docketworks/releases/<sha>` and marked
complete with a `.complete` file, touched again each time an instance
activates the release. Deploy starts by removing incomplete builds more than
a day old (leftovers of an interrupted build; the age guard avoids touching
a build still in progress). Complete releases are retained for 14 days after
their last activation and are never removed while referenced by an instance
`app` symlink or by rollback state (`PREVIOUS_SHA` in `deploy-state.env`).
To run only the cleanup pass:

```bash
sudo scripts/server/deploy.sh --cleanup-releases
```

### Backups

Each instance has nightly database backups via `backup-db-<name>.timer`.
The job runs as the instance user (`dw_<name>`), writes local dumps under
`/opt/docketworks/instances/<name>/backups`, applies retention, and syncs to
Google Drive under `gdrive:dw_backups/`. Cleanup copies local dumps
before pruning and purges only the same expired backup names remotely, so
unrelated remote-only history is not mirrored away. Each DB dump has a sibling `<dump>.migrations.json` sidecar recording the database's migration state (the snapshot `migrate_to_snapshot.py` consumes); legacy `.sha` release-pointer sidecars are deleted by the next retention run.

Mutable instance file backups run separately via `backup-files-<name>.timer`.
They incrementally sync `phone-recordings`, `session-replays`, and `mediafiles`
to `gdrive:dw_backups/files/current/`, preserving replaced/deleted
remote files under `files/archive/<timestamp>/` for 30 days.

Before enabling backups for a new instance, share a backup Shared Drive with
the instance service account. Put its ID in `BACKUP_GDRIVE_TEAM_DRIVE_ID`. If
you want rclone anchored to a folder inside that Shared Drive, put the folder ID
in `BACKUP_GDRIVE_ROOT_FOLDER_ID` in
`/opt/docketworks/config/<name>.credentials.env`; create/deploy writes
`/opt/docketworks/config/rclone/<name>.conf`.

The credentials file is a root-owned operator input (`root:root`, mode 600).
Edit it with `sudoedit`; do not hand ownership to the instance user, because
root-run orchestration sources the file.

Smoke test:

```bash
sudo systemctl status backup-db-<name>.timer
sudo systemctl start backup-db-<name>.service
sudo journalctl -u backup-db-<name>.service -n 100
sudo systemctl status backup-files-<name>.timer
sudo systemctl start backup-files-<name>.service
sudo journalctl -u backup-files-<name>.service -n 100
sudo -u dw_<name> RCLONE_CONFIG=/opt/docketworks/config/rclone/<name>.conf \
  rclone lsf gdrive:dw_backups/
```

### Cold standby (DR mode)

For a DR box that shares Xero credentials with a live primary: create with `--no-start` so celery-beat / celery-worker never auto-start (no heartbeat to Xero with shared tokens), and a `.dr-mode` marker is dropped in the instance dir. Subsequent `deploy.sh` runs see the marker and skip enable/restart of celery-beat, celery-worker, and gunicorn — migrations, builds, and unit/nginx re-renders still run, so the standby stays current.

```bash
sudo scripts/server/instance.sh create <client> <env> --no-start

# To go live (after DNS cutover):
sudo rm /opt/docketworks/instances/<client>-<env>/.dr-mode
sudo systemctl enable --now celery-beat-<client>-<env> celery-worker-<client>-<env> gunicorn-<client>-<env>
```

### Destroy (complete removal)

```bash
sudo scripts/server/instance.sh destroy <client> <env>
```

Prompts for confirmation, then drops DB, removes files, systemd service, and Nginx config.

### List all instances

```bash
scripts/server/instance.sh list
```

Shows instance name, Gunicorn status, and URL.

---

## Part E: Verification

After creating an instance:

```bash
# The full serving-path check: units, build-id through nginx+TLS, the
# auth gate, media, UFW, fail2ban jails, backup timers
sudo scripts/server/verify-instance.sh <client> <env>

# Or by hand:
sudo systemctl status gunicorn-<name>
curl -s https://<name>.docketworks.site/api/build-id/

# Open in browser — should show login page
# https://<name>.docketworks.site
```

### Full verification sequence

```bash
# Create test instance
sudo scripts/server/instance.sh prepare-config test uat --seed
# Fill in credentials...
sudo scripts/server/instance.sh create test uat

# Verify
systemctl status gunicorn-test-uat
curl https://test-uat.docketworks.site/api/build-id/

# Create second instance
sudo scripts/server/instance.sh prepare-config test2 uat --seed
# Fill in both config files...
sudo scripts/server/instance.sh create test2 uat

# Verify both work independently
curl https://test2-uat.docketworks.site/api/build-id/

# Idempotency: a second run must change nothing
sudo scripts/server/server-setup.sh
sudo scripts/server/instance.sh reconfigure test uat

# Clean up
sudo scripts/server/instance.sh destroy test uat
sudo scripts/server/instance.sh destroy test2 uat
```

---

## Part F: Continuous Deployment

Merging a PR to `main` triggers a two-step deployment process:

1. **Automatic** — GitHub Actions (`.github/workflows/deploy-uat.yml`) SSHes
   into the server as `docketworks` on push to `main` and pulls the latest
   code into the shared repo at `/opt/docketworks/repo`. Only the repo is
   updated — no instances are touched.
2. **Manual** — an operator SSHes in and runs `deploy.sh` (Part D) when
   ready to deploy to instances. `deploy.sh` fetches the repo itself, so
   the workflow keeps the mirror current rather than gating the deploy.

### Setup (one-time)

Add these GitHub repository secrets:

| Secret        | Value                                                                   |
| ------------- | ----------------------------------------------------------------------- |
| `UAT_SSH_KEY` | Private ed25519 key that can connect to the server as `docketworks`     |
| `UAT_HOST`    | Server IP address                                                       |
| `UAT_USER`    | `docketworks`                                                           |

To generate the SSH key:

```bash
ssh-keygen -t ed25519 -C "github-actions-uat" -f uat_deploy_key -N ""
# Add uat_deploy_key.pub to ~docketworks/.ssh/authorized_keys on the server
# Add the contents of uat_deploy_key as the UAT_SSH_KEY secret in GitHub
```

### Install log

All setup and instance operations are logged to `/var/log/docketworks-setup.log`.
The server manifest at `/opt/docketworks/server-manifest.txt` lists all installed software with versions.

---

## Part G: Marketing Website

The bare domain (`docketworks.site` and `www.docketworks.site`) serves the marketing website — a separate project from the docketworks app.

- **Repo**: `https://github.com/corrin/docketworks-website.git`
- **Location on server**: `/opt/docketworks-website/`
- **Runtime**: Node server (Astro) managed by PM2 on port 4321, proxied by nginx
- **Nginx config**: `/etc/nginx/sites-available/docketworks-website`

The base setup script (Part B) installs the dependencies the website needs (pnpm, pm2).

### Initial setup (one-time)

```bash
# 1. Clone and build
sudo mkdir -p /opt/docketworks-website
sudo chown ubuntu:ubuntu /opt/docketworks-website
git clone https://github.com/corrin/docketworks-website.git /opt/docketworks-website
cd /opt/docketworks-website
pnpm install
pnpm build

# 2. Create nginx server block
sudo tee /etc/nginx/sites-available/docketworks-website > /dev/null <<'NGINX'
server {
    listen 80;
    server_name docketworks.site www.docketworks.site;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name docketworks.site www.docketworks.site;

    ssl_certificate /etc/letsencrypt/live/docketworks.site/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/docketworks.site/privkey.pem;

    # Static assets — served directly by nginx
    location /assets/ {
        alias /opt/docketworks-website/dist/client/assets/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location /favicon.svg {
        alias /opt/docketworks-website/dist/client/favicon.svg;
        expires 1y;
    }

    # Everything else — proxy to Astro Node server
    location / {
        proxy_pass http://127.0.0.1:4321;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX

# 3. Enable the site and reload nginx
sudo ln -sf /etc/nginx/sites-available/docketworks-website /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# 4. Start the site with PM2
cd /opt/docketworks-website
pm2 start ecosystem.config.cjs
pm2 save
pm2 startup   # run whatever command it prints
```

### Deploying updates

After pushing changes to the `master` branch:

```bash
cd /opt/docketworks-website
./deploy/deploy.sh
```

This pulls, installs deps, rebuilds, and restarts PM2.

### Verification

```bash
# Node server responding
curl -s http://localhost:4321/ | head -5

# Nginx proxying correctly with SSL
curl -sI https://docketworks.site/
# Should return HTTP/2 200
```

---

## Resource Notes

- Each Gunicorn service runs 4 uvicorn workers (`-k
  uvicorn_worker.UvicornWorker`, per the ASGI serving model of ADR 0047) —
  SSE streams ride the event loop, so many can be open per worker at once,
  and sync views are not serialised per worker either; resize against
  observed load, not against this number
- Oracle Cloud ARM free tier: 4 OCPU / 24GB RAM
- 5-10 concurrent demo instances should run comfortably
- All packages (Python 3.12, Node 22, PostgreSQL, etc.) have aarch64/ARM builds
- The wildcard cert auto-renews via certbot with Dreamhost DNS hooks
