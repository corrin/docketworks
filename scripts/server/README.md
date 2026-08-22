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
| Xero app credentials         | developer.xero.com → New App (client ID/secret, webhook key)                                             | Xero integration (database rows) |
| AI provider API keys         | Anthropic / Google / Mistral consoles                                                                    | The LLM gateway (database rows) |
| GCP service account JSON key | Create service account, download JSON key, copy to server                                                | Backup uploads to Google Drive  |
| Google Drive backup folder   | Share a Shared Drive with the service account; optional Shared Drive/folder IDs go in `BACKUP_GDRIVE_TEAM_DRIVE_ID` / `BACKUP_GDRIVE_ROOT_FOLDER_ID` | Nightly DB and file backups     |

## Server Setup

`server-setup.sh` provisions all host-level dependencies. It is idempotent: every install block is dpkg-guarded, so re-running is cheap. **It is intended to run on every release** — `deploy.sh` invokes it at the start of each deploy so new system deps added in any future PR (a new apt package, a new systemd-managed service) auto-converge on every host without an operator-remembered bootstrap step. You can also run it directly on a fresh server.

```bash
# UAT (wildcard cert via Dreamhost DNS):
sudo ./scripts/server/server-setup.sh --dreamhost-key <DREAMHOST_API_KEY>

# Prod (no wildcard; DNS lives elsewhere):
sudo ./scripts/server/server-setup.sh --no-cert

# Re-run (reads any saved keys from disk):
sudo ./scripts/server/server-setup.sh
```

Installs host-level requirements: Python 3.12, Node 22, PostgreSQL, Redis, Nginx, Certbot, uv, rclone, UFW, Fail2ban, Claude Code CLI. Creates the `docketworks` system user, clones the repo, prepares release/cache directories, and obtains the wildcard SSL cert. App dependencies are installed by `deploy.sh` into each shared release directory.

Required keys (passed once on first run, then cached):

1. Dreamhost API key (for the Let's Encrypt DNS-01 challenge — UAT only)

Integration and backup credentials — including the Google Maps key — are configured per-instance (see below).

This script is host-level only. It does NOT touch existing instances; per-instance setup lives in `instance.sh`.

## Creating an Instance

Two-step process:

```bash
# Step 1: creates durable credentials and CompanyDefaults config
sudo ./scripts/server/instance.sh prepare-config mycompany uat --seed

# Fill out both root-owned files (see "Xero Setup" below)
sudoedit /opt/docketworks/config/mycompany-uat.credentials.env
sudoedit /opt/docketworks/config/mycompany-uat.company-defaults.json

# Step 2: reads credentials, creates everything
sudo ./scripts/server/instance.sh create mycompany uat --no-start

# Re-run after root-owned credential edits
sudo ./scripts/server/instance.sh reconfigure mycompany uat
```

prepare-config's `--seed` flag selects the seeded CompanyDefaults template
(omit it for the prospect template). Create the first login interactively —
nothing scripted stores a bootstrap password, and instances restored from an
existing database already carry their staff:

```bash
sudo ./scripts/server/dw-run.sh mycompany-uat python manage.py createsuperuser
```

After creation, the instance is live at its configured URL. Each instance also gets `backup-db-<instance>.timer` enabled for nightly database backups.

## Per-Instance Credentials

The credentials file (`templates/credentials-instance.template` is the authority) holds:

```
XERO_CLIENT_ID=            → XeroApp row
XERO_CLIENT_SECRET=
XERO_WEBHOOK_KEY=
XERO_REDIRECT_URI=
ANTHROPIC_API_KEY=         → AIProvider rows
GEMINI_API_KEY=
MISTRAL_API_KEY=
GCP_CREDENTIALS=           → <instance>/gcp-credentials.json (backups only)
BACKUP_GDRIVE_ROOT_FOLDER_ID=
BACKUP_GDRIVE_TEAM_DRIVE_ID=
GOOGLE_MAPS_API_KEY=       → IntegrationSettings row (ADR 0053)
PHONE_PROVIDER_*=          → IntegrationSettings row
```

`instance.sh create` renders each group into a fixture and loads it only when
the database does not already hold that configuration (no XeroApp row, no
AIProvider row, no credential on the IntegrationSettings row), so a restored
instance keeps what its admin entered on Admin > Integrations.

How to get them:

1. **Create a Xero app** at https://developer.xero.com/app/manage
2. **Set redirect URI** to `https://<instance>.docketworks.site/api/xero/oauth/callback/`
3. **Copy Client ID, Client Secret, and webhook signing key** into the instance credentials file.
4. **ANTHROPIC_API_KEY / GEMINI_API_KEY / MISTRAL_API_KEY:** loaded as `ai.AIProvider` rows for the LLM gateway.
5. **GCP_CREDENTIALS:** Path to a GCP service account JSON key file, used by rclone to upload backups. Each instance gets its own service account; the key file is copied into the instance directory during creation.
6. **BACKUP_GDRIVE_TEAM_DRIVE_ID / BACKUP_GDRIVE_ROOT_FOLDER_ID:** Optional Shared Drive ID and parent folder ID for backup storage. Service-account backups should target a Shared Drive the service account can write to. Backups upload under `dw_backups/` from the configured root.

### `xero_tenant_id` in the company-defaults JSON

`xero_tenant_id` must be the real tenant UUID for the organisation this
instance connects to — the validation in `instance.sh` refuses placeholders
left in the file, and `enable_xero_sync` stays false in the config source
until onboarding is deliberately completed.

## Deploying Updates

Operator runbook (the commands to run): [docs/server_setup.md](../../docs/server_setup.md), Part D.

What `deploy.sh` does, in order:

1. Pull latest code from GitHub (into the shared local repo).
2. Run `server-setup.sh` to converge host-level deps. Cheap when nothing's missing; lands new system deps automatically when a future PR adds them.
3. Resolve each target instance's tracked ref and build or reuse one release per unique SHA. A bare `--all` deployment may resolve multiple refs and SHAs.
4. For each instance: build the previous release if it is missing (rollback target — a no-op on a normal deploy), take a pre-deploy backup (unless `--no-backup`), stop `celery-beat-<instance>`, `celery-worker-<instance>`, and `gunicorn-<instance>`, switch `app` to the release, run migrate, render backup units, restart `celery-worker-<instance>`, restart `celery-beat-<instance>` (the periodic-task dispatcher), restart `gunicorn-<instance>`. If migrate fails, services stay stopped and rollback is explicit via `sudo ./scripts/rollback.sh <instance> <previous-8-char-sha> --restore-backup` unless `--no-backup` was used. Worker restarts before beat so a freshly-dispatched periodic task lands on a worker that knows the task name; gunicorn last for the same reason on webhook-dispatched tasks.
5. Clean up complete releases unused for 14 days that are no longer
   referenced by an instance `app` symlink or rollback state. To run only cleanup:
   `sudo ./scripts/server/deploy.sh --cleanup-releases`.

### Choosing what to deploy

Each instance stores its tracked ref with its current and previous commit in
`/opt/docketworks/instances/<instance>/deploy-state.env`. Production servers
typically track `origin/production`; testing and UAT servers typically track
`origin/main`:

```bash
sudo ./scripts/server/deploy.sh mycompany-uat --ref origin/main
```

Use `instance.sh create --ref origin/main` for a new UAT instance; re-point an
existing instance with `deploy.sh --ref`. A successful explicit deploy updates
the state file. Bare single-instance and `--all` deploys read each instance's
state; there is no global fallback.

Successful create, deploy, and rollback operations are appended to
`deploy-history.tsv`. Show the prior SHAs and roll back with either the latest
database or the database paired with the target release:

```bash
sudo ./scripts/server/instance.sh history mycompany uat
sudo ./scripts/rollback.sh mycompany-uat <8-char-sha>
sudo ./scripts/rollback.sh mycompany-uat <8-char-sha> --restore-backup
```

A non-production `--ref` on a `*-prod` instance is refused unless acknowledged
(interactive `y/N`, or `--allow-prod-ref` non-interactively) — a merged hotfix
deploys from the default `origin/production` and never trips this.

`instance.sh status <client> <env>` reports the running SHA and which tracked ref
(`origin/production` / `origin/main` / candidate) it matches.

## Backups

Each instance gets a nightly systemd timer:

```bash
sudo systemctl status backup-db-<instance>.timer
sudo systemctl start backup-db-<instance>.service
sudo journalctl -u backup-db-<instance>.service -n 100
```

DB backups run as `dw_<instance>` and use `/opt/docketworks/config/rclone/<instance>.conf`, which points at the instance's copied `gcp-credentials.json`. Local dumps live in `/opt/docketworks/instances/<instance>/backups`; remote dumps live under `gdrive:dw_backups/`. Cleanup copies local dumps before pruning and purges only the same expired backup names remotely, so unrelated remote-only history is not mirrored away. Each DB dump has a sibling `.sha` file recording the deployed release SHA from `app/.release-sha`.

Mutable instance file backups run separately via `backup-files-<instance>.timer`. They incrementally sync `phone-recordings`, `session-replays`, and `mediafiles` to `gdrive:dw_backups/files/current/`, with replaced/deleted remote files moved into `files/archive/<timestamp>/` for 30 days. `dropbox`, `adhoc`, `backups`, `app`, logs, sockets, env files, and credentials are not included.

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

```text
/opt/docketworks/
├── repo/                     # Local git clone/cache
├── releases/<sha>/           # Shared immutable app release (code, release-local .venv, frontend dist)
├── certbot-hooks/            # Dreamhost DNS challenge scripts
├── config/
│   ├── <name>.credentials.env    # root-owned operator input (survives destroy)
│   ├── <name>.company-defaults.json # root-owned tenant bootstrap data
│   └── rclone/<name>.conf        # Per-instance backup upload config
└── instances/
    └── <name>/               # Mutable instance state
        ├── app -> ../../releases/<sha>
        ├── gcp-credentials.json  # Copied from path in credentials.env (mode 600)
        ├── .env                  # Full env (generated from template + credentials)
        ├── mediafiles/
        ├── dropbox/
        ├── phone-recordings/
        ├── session-replays/
        ├── logs/
        └── gunicorn.sock
```

### How Env Vars Flow

```
config/<name>.credentials.env (root-owned operator input: Xero + AI + Maps + phone keys, backup GCP)
        ↓
instance.sh reads + validates
        ↓
GCP key file copied to instance dir (gcp-credentials.json)
        ↓
sed substitutes into env-instance.template → .env
        ↓
integration credentials rendered into fixtures → loaded as database rows
        ↓
gunicorn systemd service loads .env via EnvironmentFile=
```

### Security Model

- **Shared user** `docketworks` owns the local repo, release directories and release-local venvs
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
| `server-setup.sh`                                   | Host-level convergence (system packages, SSL, shared config). Runs every deploy — see "Server Setup". |
| `instance.sh`                                       | Prepare config, create/reconfigure, destroy, or list instances                                       |
| `deploy.sh`                                         | Pull updates and redeploy one or all instances                                                       |
| `release-utils.sh`                                  | Build, switch, and clean up immutable release directories                                            |
| `dw-run.sh`                                         | Run a command in an instance's environment                                                           |
| `certbot-dreamhost-auth.sh`                         | Certbot DNS-01 auth hook (adds TXT record via Dreamhost API)                                         |
| `certbot-dreamhost-cleanup.sh`                      | Certbot DNS-01 cleanup hook (removes TXT record)                                                     |
| `templates/credentials-instance.template`           | Template for per-instance credentials (Xero app, AI keys, backup GCP)                                |
| `templates/env-instance.template`                   | Template for full .env file (mirrors .env.example's contract)                                        |
| `templates/company-defaults.json.template`          | Seeded Company/CompanyDefaults bootstrap fixture (symlink to `apps/core/fixtures/company_defaults.json`) |
| `templates/company-defaults-prospect.json.template` | Prospect Company/CompanyDefaults bootstrap fixture                                                   |
| `templates/ai-providers.json.template`              | ai.AIProvider bootstrap fixture (LLM gateway keys)                                                   |
| `templates/xero-apps.json.template`                 | xero.XeroApp bootstrap fixture                                                                       |
| `templates/integration-settings.json.template`      | core.IntegrationSettings bootstrap fixture (Maps key, phone provider)                                |
| `templates/nginx-ratelimit.conf`                    | Per-IP auth rate-limit zones (http context, conf.d)                                                  |
| `templates/fail2ban-jail-docketworks.conf`          | Fail2ban jails: sshd + the two 401-only auth jails, banning via UFW                                  |
| `templates/fail2ban-filter-docketworks-auth-login.conf` | 401-only filter for POST /api/accounts/token/                                                    |
| `templates/fail2ban-filter-docketworks-auth-refresh.conf` | 401-only filter for POST /api/accounts/token/refresh/                                          |
| `verify-instance.sh`                                | Full serving-path verification (units, build-id, auth gate, media, UFW, jails)                       |
| `test_server_templates.sh`                          | The cheap-tier gate: shellcheck, rendered-template contracts, filter fixtures                        |
| `cutover/`                                          | TEMPORARY v1-to-v2 migration helpers — delete after both hosts run v2                                |
| `templates/gunicorn-instance.service.template`      | Systemd unit template (web)                                                                          |
| `templates/celery-worker-instance.service.template` | Systemd unit template (Celery worker)                                                                |
| `templates/celery-beat-instance.service.template`   | Systemd unit template (Celery Beat — periodic task dispatcher)                                       |
| `templates/backup-db-instance.service.template`     | Systemd unit template (database backup)                                                              |
| `templates/backup-db-instance.timer.template`       | Systemd timer template (nightly database backup)                                                     |
| `templates/backup-files-instance.service.template`  | Systemd unit template (mutable instance file backup)                                                  |
| `templates/backup-files-instance.timer.template`    | Systemd timer template (nightly mutable instance file backup)                                         |
| `templates/nginx-instance.conf.template`            | Nginx server block template                                                                          |
