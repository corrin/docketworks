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

- **`backup_db.sh`** — Instance-user database backup. Writes daily/monthly dumps, then runs retention and Google Drive upload through `cleanup_backups.py`. Runs via `backup-db-<instance>.timer`.
- **`backup_instance_files.sh`** — Instance-user mutable file backup. Incrementally syncs instance-owned files (`phone-recordings`, `session-replays`, `mediafiles`) to Google Drive with 30-day dated remote archive folders for replaced/deleted files. Runs via `backup-files-<instance>.timer`.
- **`predeploy_backup.sh`** — Called by `scripts/server/deploy.sh` before each instance is switched to a new release. Stamps the dump with the current release hash so rollback is a (switch release, psql restore) pair. Runnable by hand: `sudo predeploy_backup.sh <instance>`
- **`predeploy_rollback.sh`** — Restore an instance to the release + data that paired with a given commit hash. Usage: `sudo predeploy_rollback.sh <instance> <8-char-hash>` (interactive confirm; restores the dump into a temporary DB before stopping services and swapping DBs)
- **`cleanup_backups.py`** — DB backup retention and remote upload. Copies local dumps before pruning, then purges only the matching expired remote names. Legacy `ts_dir` style: keep 24h + daily for a week + monthly beyond. `predeploy_*.sql.gz`: keep 30 days. `daily_*.sql.gz`: keep 14. `monthly_*.sql.gz`: keep 12. Other filenames left alone.
- **`cleanup_backups.sh`** — Wrapper that activates venv and runs `cleanup_backups.py`

## Archive

`scripts/archive/` contains scripts that were useful historically but are no longer active:

- **`configure_tunnels.py`** — Old tunnel URL configuration (replaced by Vite proxy)
- **`test_cross_domain_cookies.py`** — Old cross-domain cookie testing (obsolete with single-origin)
- **`auto_shutdown.sh`** — Old AWS auto-shutdown (obsolete since move to docketworks.site)
