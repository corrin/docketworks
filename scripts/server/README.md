# Server Management Scripts

These scripts provision and manage multiple isolated DocketWorks instances on a single Ubuntu server. Each instance gets its own subdomain (`<name>.docketworks.site`), database, Unix user, systemd service, and Nginx config — all behind a shared wildcard SSL certificate.

## Prerequisites

**Server:** Fresh Ubuntu 24.04 ARM (Oracle Cloud free tier works).

**DNS:** `*.docketworks.site` A record pointing to the server's public IP.

**Collect before you start:**

| What                | Where to get it                                                           | Used for                             |
| ------------------- | ------------------------------------------------------------------------- | ------------------------------------ |
| Dreamhost API key   | panel.dreamhost.com → API → generate key with `dns-*` permissions         | Wildcard SSL cert (DNS-01 challenge) |
| Google Maps API key | console.cloud.google.com/apis/credentials (enable Address Validation API) | Address validation                   |

**Per instance (configured in `config/<name>.credentials.env`):**

| What                         | Where to get it                                                                                          | Used for                        |
| ---------------------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------- |
| Gmail address + app password | Google Account → Security → App passwords                                                                | Password resets, notifications  |
| GCP service account JSON key | Create service account, enable Sheets + Drive APIs, download JSON key, copy to server                    | Google Sheets/Drive integration |
| Google Drive backup folder   | Share a Drive folder with the service account; optional folder ID goes in `BACKUP_GDRIVE_ROOT_FOLDER_ID` | Nightly DB backups              |

## Server Setup

`server-setup.sh` provisions all host-level dependencies. It is idempotent: every install block is dpkg-guarded, so re-running is cheap. **It is intended to run on every release** — `deploy.sh` invokes it at the start of each deploy so new system deps added in any future PR (a new apt package, a new systemd-managed service) auto-converge on every host without an operator-remembered bootstrap step. You can also run it directly on a fresh server.

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

Installs host-level requirements: Python 3.12, Node 22, PostgreSQL, Redis, Nginx, Certbot, Poetry, rclone, Claude Code CLI. Creates the `docketworks` system user, clones the repo, prepares release/cache directories, and obtains the wildcard SSL cert. App dependencies are installed by `deploy.sh` into each shared release directory.

Required keys (passed once on first run, then cached):

1. Dreamhost API key (for the Let's Encrypt DNS-01 challenge — UAT only)
2. Google Maps API key (for address validation)

The Maps API key is stored in `/opt/docketworks/shared.env` and appended to every instance's `.env`. Email and GCP credentials are configured per-instance (see below).

This script is host-level only. It does NOT touch existing instances; per-instance setup lives in `instance.sh`.

## Creating an Instance

Two-step process:

```bash
# Step 1: creates the credentials file from template
sudo ./scripts/server/instance.sh prepare-config mycompany uat

# Fill out the root-owned credentials file (see "Xero Setup" below)
sudoedit /opt/docketworks/config/mycompany-uat.credentials.env

# Step 2: reads credentials, creates everything
sudo ./scripts/server/instance.sh create mycompany uat

# Re-run after root-owned credential/config edits
sudo ./scripts/server/instance.sh reconfigure mycompany uat
```

Add `--seed` to load demo fixture data:

```bash
sudo ./scripts/server/instance.sh create mycompany uat --seed
```

After creation, the instance is live at its configured URL. Each instance also gets `backup-db-<instance>.timer` enabled for nightly database backups.

## Per-Instance Xero Setup

The credentials file needs:

```
XERO_DEFAULT_USER_ID=
XERO_CLIENT_ID=
XERO_CLIENT_SECRET=
XERO_WEBHOOK_KEY=
XERO_REDIRECT_URI=
GCP_CREDENTIALS=
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
```

Xero client_id, client_secret, webhook_key, and redirect URI are also required
in the credentials file. `instance.sh create` renders them into the XeroApp
bootstrap fixture and only loads that fixture when no XeroApp exists yet.

How to get them:

1. **Create a Xero app** at https://developer.xero.com/app/manage
2. **Set redirect URI** to `https://<instance>.docketworks.site/api/xero/oauth/callback/`
3. **Copy Client ID, Client Secret, and webhook signing key** into the instance credentials file.
4. **XERO_DEFAULT_USER_ID:** Use the existing Xero login/user ID that will own time entries. This value is required before `instance.sh create`; do not leave it blank for a first create.
5. **GCP_CREDENTIALS:** Path to a GCP service account JSON key file. Each instance needs its own service account to isolate tenant data. The key file is copied into the instance directory during creation.
6. **BACKUP_GDRIVE_ROOT_FOLDER_ID:** Optional Google Drive folder ID for the backup parent. Share that folder with the service account. Backups upload under `dw_backups/<instance>/` from that root.
7. **EMAIL_HOST_USER + EMAIL_HOST_PASSWORD:** Gmail address and app password for this instance's outgoing email (password resets, notifications). Generate an app password at Google Account → Security → App passwords.

## Deploying Updates

Operator runbook (the commands to run): [docs/updating.md](../../docs/updating.md).

What `deploy.sh` does, in order:

1. Pull latest code from GitHub (into the shared local repo).
2. Run `server-setup.sh` to converge host-level deps. Cheap when nothing's missing; lands new system deps automatically when a future PR adds them.
3. Resolve the target ref to a SHA and build `/opt/docketworks/releases/<sha>` once if it does not already exist.
4. For each instance: pre-deploy backup (unless `--no-backup`), switch `current` to the release, run migrate, render backup units, render+restart `celery-worker-<instance>`, render+restart `celery-beat-<instance>` (the periodic-task dispatcher), restart `gunicorn-<instance>`. Worker restarts before beat so a freshly-dispatched periodic task lands on a worker that knows the task name; gunicorn last for the same reason on webhook-dispatched tasks.
5. Clean up complete releases that are no longer referenced by an instance
   `current` symlink or rollback state. To run only cleanup:
   `sudo ./scripts/server/deploy.sh --cleanup-releases`.

## Backups

Each instance gets a nightly systemd timer:

```bash
sudo systemctl status backup-db-<instance>.timer
sudo systemctl start backup-db-<instance>.service
sudo journalctl -u backup-db-<instance>.service -n 100
```

Backups run as `dw_<instance>` and use `/opt/docketworks/config/rclone/<instance>.conf`, which points at the instance's copied `gcp-credentials.json`. Local dumps live in `/opt/docketworks/instances/<instance>/backups`; remote files live under `gdrive:dw_backups/<instance>/`.

## Destroying an Instance

```bash
sudo ./scripts/server/instance.sh destroy mycompany uat
```

Prompts for confirmation, then removes: systemd service, Nginx config, database + DB user, instance directory, OS user.

## Listing Instances

```bash
./scripts/server/instance.sh list
```

Shows each instance's name, status (running/stopped/no service), current release SHA, and URL. No sudo required.

## Architecture Quick Reference

### Directory Layout

```
/opt/docketworks/
├── repo/                     # Local git clone/cache
├── releases/<sha>/           # Shared immutable app release (code, release-local .venv, frontend dist)
├── shared.env                # Maps API key (appended to each .env)
├── certbot-hooks/            # Dreamhost DNS challenge scripts
├── config/
│   ├── <name>.credentials.env    # root-owned operator input (survives destroy)
│   └── rclone/<name>.conf        # Per-instance backup upload config
└── instances/
    └── <name>/               # Mutable instance state
        ├── current -> ../../releases/<sha>
        ├── gcp-credentials.json  # Copied from path in credentials.env (mode 600)
        ├── .env                  # Full env (generated from template + credentials + shared.env)
        ├── mediafiles/
        ├── dropbox/
        ├── phone-recordings/
        ├── session-replays/
        ├── logs/
        └── gunicorn.sock
```

### How Env Vars Flow

```
config/<name>.credentials.env (root-owned operator input: Xero + GCP + email)
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

- **Shared user** `docketworks` owns the local repo, release directories, release-local venvs, and shared.env
- **Per-instance user** `dw-<name>` runs gunicorn, owns the instance directory
- **Credentials input** in `/opt/docketworks/config` is `root:root` mode 600
  because `instance.sh` and `deploy.sh` source it during root-run orchestration
- Instance dirs are `dw-<name>:www-data` mode 750 — Nginx (www-data) can read static files, other instance users cannot access
- `.env` files are mode 600, owner-only — even www-data can't read secrets
- Each instance has its own PostgreSQL database and user

## File Inventory

| File                                                | Description                                                                                          |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `common.sh`                                         | Shared constants: domain, paths, directories                                                         |
| `server-setup.sh`                                   | Host-level convergence (packages, venv, SSL, shared config). Runs every deploy — see "Server Setup". |
| `instance.sh`                                       | Prepare config, create/reconfigure, destroy, or list instances                                       |
| `deploy.sh`                                         | Pull updates and redeploy one or all instances                                                       |
| `release-utils.sh`                                  | Build, switch, and clean up immutable release directories                                            |
| `dw-run.sh`                                         | Run a command in an instance's environment                                                           |
| `certbot-dreamhost-auth.sh`                         | Certbot DNS-01 auth hook (adds TXT record via Dreamhost API)                                         |
| `certbot-dreamhost-cleanup.sh`                      | Certbot DNS-01 cleanup hook (removes TXT record)                                                     |
| `templates/credentials-instance.template`           | Template for per-instance credentials (Xero, GCP, email)                                             |
| `templates/env-instance.template`                   | Template for full .env file                                                                          |
| `templates/gunicorn-instance.service.template`      | Systemd unit template (web)                                                                          |
| `templates/celery-worker-instance.service.template` | Systemd unit template (Celery worker)                                                                |
| `templates/celery-beat-instance.service.template`   | Systemd unit template (Celery Beat — periodic task dispatcher)                                       |
| `templates/backup-db-instance.service.template`     | Systemd unit template (database backup)                                                              |
| `templates/backup-db-instance.timer.template`       | Systemd timer template (nightly database backup)                                                     |
| `templates/nginx-instance.conf.template`            | Nginx server block template                                                                          |
