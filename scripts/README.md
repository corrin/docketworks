# Scripts

## Pre-commit hooks

These run automatically on every commit via `.pre-commit-config.yaml`:

- **`detect_fstrings_without_placeholder.py`** — Catches f-strings that have no `{}` placeholders
- **`find_duplicates.py`** — Catches duplicate class attributes/methods from bad merges
- **`find_late_imports.py`** — Catches stdlib imports hiding inside functions (circular-import workarounds excluded)
- **`update_init.py`** — Regenerates `__init__.py` files (never edit these by hand)

## Code quality utilities

Run manually for periodic code quality analysis:

- **`find_wrapper_candidates.py`** — Finds short wrapper functions with few callers, candidates for inlining. Usage: `python scripts/find_wrapper_candidates.py [--max-lines N] [--max-callers N]`

## Google Drive / Sheets

Require `GCP_CREDENTIALS` env var pointing to a service account JSON file:

- **`explore_google_drive.py`** — Browse Google Drive folder structure
- **`create_master_template.py`** — Create/manage Google Sheets quote templates
- **`get_gapi_token.py`** — Print a Google API access token for debugging

## Data operations

Run manually for one-off or periodic data tasks:

- **`dump_settings.py`** — Dumps sanitized Django settings as JSON for diagnostics. Usage: `python scripts/dump_settings.py`
- **`move_time_between_jobs.py`** — Moves timesheet time entries from one job to another. Usage: `python scripts/move_time_between_jobs.py --from 96881 --to 96882 [--execute]`
- **`production_data_fixer.py`** — Idempotent fixes for known production data issues. Usage: `python scripts/production_data_fixer.py --fix-empty-notes [--live]`

## Dependency management

- **`upgrade_script.py`** — Checks PyPI for outdated dependencies and prints a staleness report. Requires `pandas`, `requests`, `toml`. Usage: `python scripts/upgrade_script.py pyproject.toml`

## Production infrastructure

- **`backup_db.sh`** — Daily automated database backup (runs via cron on prod). See `docs/server_setup_prod.md`
- **`cleanup_backups.py`** — Backup retention (keep 24h, daily for a week, monthly beyond)
- **`cleanup_backups.sh`** — Wrapper that activates venv and runs `cleanup_backups.py`

## Archive

`scripts/archive/` contains scripts that were useful historically but are no longer active:

- **`configure_tunnels.py`** — Old tunnel URL configuration (replaced by Vite proxy)
- **`test_cross_domain_cookies.py`** — Old cross-domain cookie testing (obsolete with single-origin)
- **`auto_shutdown.sh`** — Old AWS auto-shutdown (obsolete since move to docketworks.site)
