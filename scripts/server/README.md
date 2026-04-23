# Server Management Scripts

These scripts provision and manage multiple isolated DocketWorks instances on a single Ubuntu server. Each instance gets its own subdomain (`<name>.docketworks.site`), database, Unix user, systemd service, and Nginx config — all behind a shared wildcard SSL certificate.

## Prerequisites

**Server:** Fresh Ubuntu 24.04 ARM (Oracle Cloud free tier works).

**DNS:** `*.docketworks.site` A record pointing to the server's public IP.

**Collect before you start:**

| What | Where to get it | Used for |
|------|----------------|----------|
| Dreamhost API key | panel.dreamhost.com → API → generate key with `dns-*` permissions | Wildcard SSL cert (DNS-01 challenge) |
| Google Maps API key | console.cloud.google.com/apis/credentials (enable Address Validation API) | Address validation |

**Per instance (configured in `config/<name>.credentials.env`):**

| What | Where to get it | Used for |
|------|----------------|----------|
| Gmail address + app password | Google Account → Security → App passwords | Password resets, notifications |
| GCP service account JSON key | Create service account, enable Sheets + Drive APIs, download JSON key, copy to server | Google Sheets/Drive integration |

## Server Setup (One-Time)

```bash
# UAT (wildcard cert via Dreamhost DNS):
sudo ./scripts/server/server-setup.sh \
    --dreamhost-key   <DREAMHOST_API_KEY> \
    --google-maps-key <GOOGLE_MAPS_API_KEY>

# Prod (no wildcard; DNS lives elsewhere):
sudo ./scripts/server/server-setup.sh --no-cert --google-maps-key <GOOGLE_MAPS_API_KEY>

# Re-run (reads any saved keys from disk):
sudo ./scripts/server/server-setup.sh
```

Installs everything: Python 3.12, Node 22, MariaDB, Nginx, Certbot, Poetry, Claude Code CLI. Creates the `docketworks` system user, clones the repo, builds the shared venv and node_modules, obtains the wildcard SSL cert.

Required keys (passed once on first run, then cached):
1. Dreamhost API key (for the Let's Encrypt DNS-01 challenge — UAT only)
2. Google Maps API key (for address validation)

The Maps API key is stored in `/opt/docketworks/shared.env` and appended to every instance's `.env`. Email and GCP credentials are configured per-instance (see below).

Idempotent — safe to re-run (skips already-completed steps).

## Creating an Instance

Two-step process:

```bash
# Step 1: creates the credentials file from template
sudo ./scripts/server/instance.sh prepare-config mycompany uat

# Fill out the credentials file (see "Xero Setup" below)
sudo vi /opt/docketworks/config/mycompany-uat.credentials.env

# Step 2: reads credentials, creates everything
sudo ./scripts/server/instance.sh create mycompany uat
```

Add `--seed` to load demo fixture data:

```bash
sudo ./scripts/server/instance.sh create mycompany uat --seed
```

After creation, the instance is live at `https://mycompany-uat.docketworks.site`.

## Per-Instance Xero Setup

The credentials file needs seven values:

```
XERO_CLIENT_ID=
XERO_CLIENT_SECRET=
XERO_WEBHOOK_KEY=
XERO_DEFAULT_USER_ID=
GCP_CREDENTIALS=
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
```

How to get them:

1. **Create a Xero app** at https://developer.xero.com/app/manage
2. **Set redirect URI** to `https://<instance>.docketworks.site/api/xero/oauth/callback/`
3. **Copy Client ID and Client Secret** into the credentials file
4. **Create a webhook subscription** in the Xero app, copy the webhook key
5. **XERO_DEFAULT_USER_ID:** Create the instance first (it will work without Xero initially), create a Staff member in the app's admin, then copy that staff member's UUID into the credentials file and re-run create
6. **GCP_CREDENTIALS:** Path to a GCP service account JSON key file. Each instance needs its own service account to isolate tenant data. The key file is copied into the instance directory during creation.
7. **EMAIL_HOST_USER + EMAIL_HOST_PASSWORD:** Gmail address and app password for this instance's outgoing email (password resets, notifications). Generate an app password at Google Account → Security → App passwords.

## Deploying Updates

```bash
# Single instance
sudo ./scripts/server/deploy.sh mycompany-uat

# All instances
sudo ./scripts/server/deploy.sh --all
```

Pulls latest code from GitHub (via the local repo), updates shared Python/Node deps, then for each instance: builds frontend, runs migrate, restarts gunicorn.

## Destroying an Instance

```bash
sudo ./scripts/server/instance.sh destroy mycompany uat
```

Prompts for confirmation, then removes: systemd service, Nginx config, database + DB user, instance directory, OS user.

## Listing Instances

```bash
./scripts/server/instance.sh list
```

Shows each instance's name, status (running/stopped/no service), git branch, and URL. No sudo required.

## Architecture Quick Reference

### Directory Layout

```
/opt/docketworks/
├── .venv/                    # Shared Python venv (all instances use this)
├── repo/                     # Local git clone (source for instance clones)
├── shared.env                # Maps API key (appended to each .env)
├── package.json              # Shared node_modules
├── certbot-hooks/            # Dreamhost DNS challenge scripts
├── config/
│   └── <name>.credentials.env    # Xero + GCP + email secrets (survives destroy)
└── instances/
    └── <name>/               # = git checkout (always on main)
        ├── gcp-credentials.json  # Copied from path in credentials.env (mode 600)
        ├── .env                  # Full env (generated from template + credentials + shared.env)
        ├── manage.py
        ├── apps/
        ├── frontend/dist/
        ├── mediafiles/
        ├── dropbox/
        ├── logs/
        └── gunicorn.sock
```

### How Env Vars Flow

```
config/<name>.credentials.env (user fills Xero + GCP + email values)
        ↓
instance.sh reads + validates
        ↓
GCP key file copied to instance dir (gcp-credentials.json)
        ↓
sed substitutes into env-instance.template → .env
        ↓
shared.env appended to .env
        ↓
gunicorn systemd service loads .env via EnvironmentFile=
```

### Security Model

- **Shared user** `docketworks` owns the venv, repo, and shared.env
- **Per-instance user** `dw-<name>` runs gunicorn, owns the instance directory
- Instance dirs are `dw-<name>:www-data` mode 750 — Nginx (www-data) can read static files, other instance users cannot access
- `.env` files are mode 600, owner-only — even www-data can't read secrets
- Each instance has its own PostgreSQL database and user

## File Inventory

| File | Description |
|------|-------------|
| `common.sh` | Shared constants: domain, paths, directories |
| `server-setup.sh` | One-time server provisioning (packages, venv, SSL, shared config) |
| `instance.sh` | Prepare config, create, destroy, or list instances |
| `deploy.sh` | Pull updates and redeploy one or all instances |
| `dw-run.sh` | Run a command in an instance's environment |
| `certbot-dreamhost-auth.sh` | Certbot DNS-01 auth hook (adds TXT record via Dreamhost API) |
| `certbot-dreamhost-cleanup.sh` | Certbot DNS-01 cleanup hook (removes TXT record) |
| `templates/credentials-instance.template` | Template for per-instance credentials (Xero, GCP, email) |
| `templates/env-instance.template` | Template for full .env file |
| `templates/gunicorn-instance.service.template` | Systemd service unit template |
| `templates/nginx-instance.conf.template` | Nginx server block template |
