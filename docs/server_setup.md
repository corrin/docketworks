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
    --google-maps-key "$GOOGLE_MAPS_API_KEY" \
    --cert-domain     '*.docketworks.site'

# Same UAT box also serving a client-branded URL (additional cert):
sudo ./scripts/server/server-setup.sh \
    --dreamhost-key   "$DREAMHOST_API_KEY" \
    --google-maps-key "$GOOGLE_MAPS_API_KEY" \
    --cert-domain     '*.docketworks.site' \
    --cert-domain     uat-office.morrissheetmetal.co.nz

# First install on a prod box (one cert for the customer FQDN):
sudo ./scripts/server/server-setup.sh \
    --dreamhost-key   "$DREAMHOST_API_KEY" \
    --google-maps-key "$GOOGLE_MAPS_API_KEY" \
    --cert-domain     office.heuserlimited.com

# First install on a DR box (no certs obtained):
sudo ./scripts/server/server-setup.sh \
    --dreamhost-key   "$DREAMHOST_API_KEY" \
    --google-maps-key "$GOOGLE_MAPS_API_KEY" \
    --no-cert-domain

# Re-run on an already-configured server (reads everything from saved files):
sudo ./scripts/server/server-setup.sh
```

The Dreamhost key, Google Maps key, and cert-domain list are persisted
on first install at `/etc/letsencrypt/dreamhost-api-key.txt`,
`/opt/docketworks/shared.env`, and `/etc/letsencrypt/cert-domains.txt`
respectively. Re-runs read all three from disk, so `deploy.sh` can
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
- Nginx
- Certbot + Dreamhost DNS hook scripts (for wildcard cert auto-renewal)
- pnpm (via corepack) and pm2 (for marketing website)
- Claude Code CLI
- Build dependencies (build-essential, libpq-dev, pkg-config)
- Poetry (for the `docketworks` system user)
- iptables rules for ports 80/443 (Oracle Cloud)

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
# Step 1: scaffold credentials file
sudo scripts/server/instance.sh prepare-config <client> <env>

# Step 2: fill in the credentials
sudo nano /opt/docketworks/instances/<client>-<env>/credentials.env

# Step 3: create the instance
sudo scripts/server/instance.sh create <client> <env>

# Or with demo fixtures:
sudo scripts/server/instance.sh create <client> <env> --seed
```

### Manual steps (reference)

1. **Clone repo**
   ```bash
   sudo -u dw-<name> git clone git@github.com:corrin/docketworks.git /opt/docketworks/instances/<name>
   ```

2. **Create PostgreSQL databases and roles**

   Two roles per instance: the app role owns the live and scrub DBs; a
   separate test role owns only the pre-provisioned test DB and has no
   CREATEDB, so a misconfigured pytest run cannot reach the app DB.

   ```bash
   sudo -u postgres psql <<SQL
   CREATE ROLE "dw_<name>" WITH LOGIN PASSWORD '<password>';
   CREATE ROLE "dw_<name>_test" WITH LOGIN PASSWORD '<test_password>';
   CREATE DATABASE "dw_<name>" OWNER "dw_<name>";
   CREATE DATABASE "dw_<name>_scrub" OWNER "dw_<name>";
   CREATE DATABASE "test_dw_<name>" OWNER "dw_<name>_test";
   GRANT ALL PRIVILEGES ON DATABASE "dw_<name>" TO "dw_<name>";
   GRANT ALL PRIVILEGES ON DATABASE "dw_<name>_scrub" TO "dw_<name>";
   GRANT ALL PRIVILEGES ON DATABASE "test_dw_<name>" TO "dw_<name>_test";
   SQL
   ```

   Pytest never needs CREATEDB: `conftest.py` resets the public schema in
   `test_dw_<name>` (the test role owns the DB) and re-runs migrations on
   every session.

3. **Generate `.env`** from `scripts/server/templates/env-instance.template`
   - Replace all `__PLACEHOLDER__` values
   - `chmod 600 /opt/docketworks/instances/<name>/.env`

4. **Install dependencies** (uses shared venv)
   ```bash
   scripts/server/dw-run.sh <name> poetry install --no-interaction
   ```

5. **Migrate**
   ```bash
   scripts/server/dw-run.sh <name> python manage.py migrate --no-input
   ```

6. **Load fixtures** (optional)
   ```bash
   scripts/server/dw-run.sh <name> python manage.py loaddata demo_fixtures
   ```

7. **Build frontend**
   ```bash
   sudo -u dw-<name> bash -c "
       cd /opt/docketworks/instances/<name>/frontend
       npm install
       npm run build
   "
   ```

8. **Install systemd service**
   ```bash
   sudo sed 's/__INSTANCE__/<name>/g' scripts/server/templates/gunicorn-instance.service.template \
       > /etc/systemd/system/gunicorn-<name>.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now gunicorn-<name>
   ```

9. **Install Nginx server block**
   ```bash
   sudo sed -e 's/__INSTANCE__/<name>/g' -e 's/__DOMAIN__/docketworks.site/g' \
       scripts/server/templates/nginx-instance.conf.template \
       > /etc/nginx/sites-available/docketworks-<name>
   sudo ln -sf /etc/nginx/sites-available/docketworks-<name> /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   ```

### Migrating an instance created before per-tenant test roles

Instances provisioned before the per-tenant test role landed used a
cluster-wide `dw_test` role with `CREATEDB`. To migrate an existing
instance (one-shot, as a Postgres superuser):

```bash
TEST_PWD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)"
sudo -u postgres psql <<SQL
CREATE ROLE "dw_<name>_test" WITH LOGIN PASSWORD '$TEST_PWD';
CREATE DATABASE "test_dw_<name>" OWNER "dw_<name>_test";
GRANT ALL PRIVILEGES ON DATABASE "test_dw_<name>" TO "dw_<name>_test";
SQL
sudo -u dw_<name> vi /opt/docketworks/instances/<name>/.env
# Add:
#   TEST_DB_USER=dw_<name>_test
#   TEST_DB_PASSWORD=<value of $TEST_PWD>
```

Once every instance has been migrated, drop the now-unused shared role:

```bash
sudo -u postgres psql <<'SQL'
SELECT * FROM pg_database
 WHERE datdba = (SELECT oid FROM pg_roles WHERE rolname = 'dw_test');  -- expect 0 rows
DROP ROLE dw_test;
SQL
```

---

## Part C.1: Post-Create Setup

After `instance.sh create` completes, the instance has infrastructure but no data.
Choose the path that matches your scenario:

### Path A: Backup Restore (e.g. MSM demo)

For instances that need production data, follow [restore-prod-to-nonprod.md](restore-prod-to-nonprod.md).

### Path B: Fresh Prospect (new Xero org)

For a prospect trying DocketWorks with their own Xero:

1. **Instance created** — admin user auto-created (`defaultadmin@example.com` / `Default-admin-password`)

2. **Load CompanyDefaults fixture**
   ```bash
   # Copy the template and edit with prospect's details
   cp apps/workflow/fixtures/company_defaults_prospect.json \
      /opt/docketworks/instances/<name>/company_defaults.json

   # Edit: replace all __PLACEHOLDER__ values with prospect's info
   # Key fields: company_name, acronym, address, email, po_prefix,
   #             xero_payroll_calendar_name (must match their Xero calendar)

   # Load it
   scripts/server/dw-run.sh <name> python manage.py loaddata /opt/docketworks/instances/<name>/company_defaults.json
   ```

3. **Xero OAuth** — log into `https://<name>.docketworks.site` as admin, go to Admin > Xero Settings, click "Login with Xero" and authorize

4. **Xero configuration**
   ```bash
   scripts/server/dw-run.sh <name> python manage.py xero --setup
   scripts/server/dw-run.sh <name> python manage.py xero --configure-payroll
   scripts/server/dw-run.sh <name> python manage.py start_xero_sync --entity accounts
   ```

5. **Import staff from Xero**
   ```bash
   # Preview first
   scripts/server/dw-run.sh <name> python manage.py xero --import-staff-dry-run

   # Then import
   scripts/server/dw-run.sh <name> python manage.py xero --import-staff
   ```
   This pulls employees from Xero Payroll and creates Staff records with their
   wage rates and working hours. All imported staff get `password_needs_reset=True`.

6. **Verify** — log in as admin, check Staff list, mark office staff via admin UI

---

## Part D: Managing Instances

### Deploy (update to latest code)

```bash
sudo scripts/server/deploy.sh <name>
```

This pulls latest code, installs dependencies, runs migrations, rebuilds frontend, and restarts Gunicorn.

### Cold standby (DR mode)

For a DR box that shares Xero credentials with a live primary: create with `--no-start` so scheduler/celery never auto-start (no heartbeat to Xero with shared tokens), and a `.dr-mode` marker is dropped in the instance dir. Subsequent `deploy.sh` runs see the marker and skip enable/restart of celery-worker and gunicorn — migrations, builds, and unit/nginx re-renders still run, so the standby stays current.

```bash
sudo scripts/server/instance.sh create <client> <env> --no-start

# To go live (after DNS cutover):
sudo rm /opt/docketworks/instances/<client>-<env>/.dr-mode
sudo systemctl enable --now scheduler-<client>-<env> celery-worker-<client>-<env> gunicorn-<client>-<env>
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
# Check Gunicorn is running
sudo systemctl status gunicorn-<name>

# Test API health endpoint
curl -s https://<name>.docketworks.site/api/health

# Open in browser — should show login page
# https://<name>.docketworks.site
```

### Full verification sequence

```bash
# Create test instance
sudo scripts/server/instance.sh prepare-config test uat
# Fill in credentials...
sudo scripts/server/instance.sh create test uat

# Verify
systemctl status gunicorn-test-uat
curl https://test-uat.docketworks.site/api/health

# Create second instance with seed data
sudo scripts/server/instance.sh prepare-config test2 uat
# Fill in credentials...
sudo scripts/server/instance.sh create test2 uat --seed

# Verify both work independently
curl https://test2-uat.docketworks.site/api/health

# Clean up
sudo scripts/server/instance.sh destroy test uat
sudo scripts/server/instance.sh destroy test2 uat
```

---

## Part F: Continuous Deployment

Merging a PR to `main` triggers a two-step deployment process:

1. **Automatic** — GitHub Actions pulls the repo on the server (`.github/workflows/deploy-uat.yml`)
2. **Manual** — Admin SSHes in and runs `deploy.sh` when ready to deploy to instances

### Setup (one-time)

Add these GitHub repository secrets:

| Secret | Value |
|--------|-------|
| `UAT_SSH_KEY` | Private SSH key that can connect to the server as `docketworks` |
| `UAT_HOST` | Server IP address |
| `UAT_USER` | `docketworks` |

To generate the SSH key:

```bash
ssh-keygen -t ed25519 -C "github-actions-uat" -f uat_deploy_key -N ""
# Add uat_deploy_key.pub to ~docketworks/.ssh/authorized_keys on the server
# Add the contents of uat_deploy_key as the UAT_SSH_KEY secret in GitHub
```

### How it works

**Step 1 (automatic):** On push to `main`, `deploy-uat.yml` SSHes into the server as `docketworks` and pulls the latest code into `/opt/docketworks/repo`. This only updates the shared repo — no instances are touched.

**Step 2 (manual):** When ready to deploy to instances, SSH into the server and run:

```bash
# Deploy all instances
sudo ./scripts/server/deploy.sh --all

# Or a single instance
sudo ./scripts/server/deploy.sh <name>
```

This updates shared Python/Node deps, then for each instance: builds frontend, runs migrate, restarts Gunicorn.

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

- Each Gunicorn service runs 3 workers
- Oracle Cloud ARM free tier: 4 OCPU / 24GB RAM
- 5-10 concurrent demo instances should run comfortably
- All packages (Python 3.12, Node 22, PostgreSQL, etc.) have aarch64/ARM builds
- The wildcard cert auto-renews via certbot with Dreamhost DNS hooks
