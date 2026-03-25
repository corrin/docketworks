# UAT/Demo Environment Setup

Multi-instance demo server on `192.9.188.248` (Oracle Cloud, Ubuntu 24.04 ARM/aarch64).
Each prospect gets their own subdomain, database, and Xero credentials.

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

```bash
sudo ./scripts/uat/uat-base-setup.sh
```

The script logs every action to `/var/log/docketworks-setup.log` with timestamps,
and writes a manifest of installed software to `/opt/docketworks/server-manifest.txt`.

It is **idempotent** — safe to re-run on an already-configured server.

### What it installs

- etckeeper (tracks /etc changes in git)
- Python 3.12 + dev packages
- Node.js 22 (NodeSource)
- PostgreSQL server
- Nginx
- Certbot + Dreamhost DNS hook scripts (for wildcard cert auto-renewal)
- pnpm (via corepack) and pm2 (for marketing website)
- Claude Code CLI
- Build dependencies (build-essential, libpq-dev, pkg-config)
- Poetry (for the `docketworks` system user)
- iptables rules for ports 80/443 (Oracle Cloud)

### Interactive steps during the script

The script will pause and prompt you for:

1. **SSH deploy key** — generates the key, displays the public key, and waits for you to add it as a deploy key in GitHub (Settings > Deploy keys)
2. **Dreamhost API key** — prompts you to paste your API key (get one from `panel.dreamhost.com/?tree=home.api` with `dns-*` permissions)

The script then automatically:
- Obtains a wildcard SSL cert via Dreamhost DNS API (~2-4 min for DNS propagation)
- Configures and starts Nginx with the SSL cert

Certs auto-renew via `certbot renew` using the same Dreamhost DNS hooks.

---

## Part C: Creating a Demo Instance

### Automated (recommended)

```bash
sudo scripts/uat/uat-create-instance.sh <name>         # Empty database
sudo scripts/uat/uat-create-instance.sh <name> --seed   # With demo fixtures
```

Then update Xero credentials in `/opt/docketworks/instances/<name>/.env` and restart:

```bash
sudo systemctl restart gunicorn-<name>
```

### Manual steps (reference)

1. **Clone repo**
   ```bash
   sudo -u dw-<name> git clone git@github.com:corrin/docketworks.git /opt/docketworks/instances/<name>/code
   ```

2. **Create PostgreSQL database**
   ```bash
   sudo -u postgres psql <<SQL
   CREATE ROLE "dw_<name>" WITH LOGIN PASSWORD '<password>';
   CREATE DATABASE "dw_<name>" OWNER "dw_<name>";
   GRANT ALL PRIVILEGES ON DATABASE "dw_<name>" TO "dw_<name>";
   SQL
   ```

3. **Generate `.env`** from `scripts/uat/templates/env-instance.template`
   - Replace all `__PLACEHOLDER__` values
   - `chmod 600 /opt/docketworks/instances/<name>/.env`

4. **Install dependencies** (uses shared venv)
   ```bash
   scripts/uat/dw-run.sh <name> poetry install --no-interaction
   ```

5. **Migrate + collectstatic**
   ```bash
   scripts/uat/dw-run.sh <name> python manage.py migrate --no-input
   scripts/uat/dw-run.sh <name> python manage.py collectstatic --no-input
   ```

6. **Load fixtures** (optional)
   ```bash
   scripts/uat/dw-run.sh <name> python manage.py loaddata demo_fixtures
   ```

7. **Build frontend**
   ```bash
   sudo -u dw-<name> bash -c "
       cd /opt/docketworks/instances/<name>/code/frontend
       npm install
       npm run build
   "
   ```

8. **Install systemd service**
   ```bash
   sudo sed 's/__INSTANCE__/<name>/g' scripts/uat/templates/gunicorn-instance.service.template \
       > /etc/systemd/system/gunicorn-<name>.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now gunicorn-<name>
   ```

9. **Install Nginx server block**
   ```bash
   sudo sed -e 's/__INSTANCE__/<name>/g' -e 's/__DOMAIN__/docketworks.site/g' \
       scripts/uat/templates/nginx-instance.conf.template \
       > /etc/nginx/sites-available/docketworks-<name>
   sudo ln -sf /etc/nginx/sites-available/docketworks-<name> /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   ```

---

## Part C.1: Post-Create Setup

After `uat-instance.sh create` completes, the instance has infrastructure but no data.
Choose the path that matches your scenario:

### Path A: Backup Restore (e.g. MSM demo)

For instances that need production data:

1. **Instance created** — `uat-instance.sh create <name>` completed
2. **Follow backup-restore-process.md** steps 1-17, running Django commands via the helper:
   ```bash
   scripts/uat/dw-run.sh <name> python manage.py <command>
   ```
3. **Xero setup** — follow backup-restore-process.md steps 21-27

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
   scripts/uat/dw-run.sh <name> python manage.py loaddata /opt/docketworks/instances/<name>/company_defaults.json
   ```

3. **Xero OAuth** — log into `https://<name>.docketworks.site` as admin, go to Admin > Xero Settings, click "Login with Xero" and authorize

4. **Xero configuration**
   ```bash
   scripts/uat/dw-run.sh <name> python manage.py xero --setup
   scripts/uat/dw-run.sh <name> python manage.py xero --configure-payroll
   scripts/uat/dw-run.sh <name> python manage.py start_xero_sync --entity accounts
   ```

5. **Import staff from Xero**
   ```bash
   # Preview first
   scripts/uat/dw-run.sh <name> python manage.py xero --import-staff-dry-run

   # Then import
   scripts/uat/dw-run.sh <name> python manage.py xero --import-staff
   ```
   This pulls employees from Xero Payroll and creates Staff records with their
   wage rates and working hours. All imported staff get `password_needs_reset=True`.

6. **Verify** — log in as admin, check Staff list, mark office staff via admin UI

---

## Part D: Managing Instances

### Deploy (update to latest code)

```bash
sudo scripts/uat/uat-deploy-instance.sh <name>
```

This pulls latest code, installs dependencies, runs migrations, rebuilds frontend, and restarts Gunicorn.

### Destroy (complete removal)

```bash
sudo scripts/uat/uat-destroy-instance.sh <name>
```

Prompts for confirmation, then drops DB, removes files, systemd service, and Nginx config.

### List all instances

```bash
scripts/uat/uat-list-instances.sh
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
sudo scripts/uat/uat-create-instance.sh test1

# Verify
systemctl status gunicorn-test1
curl https://test1.docketworks.site/api/health

# Create second instance with seed data
sudo scripts/uat/uat-create-instance.sh test2 --seed

# Verify both work independently
curl https://test2.docketworks.site/api/health

# Clean up
sudo scripts/uat/uat-destroy-instance.sh test1
sudo scripts/uat/uat-destroy-instance.sh test2
```

---

## Part F: Continuous Deployment

Merging a PR to `main` triggers a two-step deployment process:

1. **Automatic** — GitHub Actions pulls the repo on the server (`.github/workflows/deploy-uat.yml`)
2. **Manual** — Admin SSHes in and runs `uat-deploy.sh` when ready to deploy to instances

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
sudo ./scripts/uat/uat-deploy.sh --all

# Or a single instance
sudo ./scripts/uat/uat-deploy.sh <name>
```

This updates shared Python/Node deps, then for each instance: builds frontend, runs collectstatic + migrate, restarts Gunicorn.

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
