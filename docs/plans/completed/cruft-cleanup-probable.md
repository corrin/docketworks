# Cruft Cleanup — Probable cruft (needs decision)

- [x] `ngrok.yml` — Not cruft. Added to .gitignore, created .example, updated docs for self-contained config
- [x] `MIGRATION_PLAN.md` — Moved to docs/plans/completed/monorepo-migration.md
- [x] `scripts/auto_shutdown.sh` — Obsolete (Oracle runs 24/7). Archived to scripts/archive/
- [x] `scripts/backup_db.sh` — Not cruft, active on prod. Documented in server_setup_prod.md
- [x] `scripts/cleanup_backups.py` — Not cruft, active on prod. Documented in server_setup_prod.md
- [x] `scripts/cleanup_backups.sh` — Not cruft, wrapper for above. Documented in server_setup_prod.md
- [x] `adhoc/mistral_parsing.py` — Already deleted in prior cleanup. Cleaned stale docstring reference
- [x] `adhoc/check_ai_providers.py` — Deleted stale copy (newer version in scripts/restore_checks/)
- [x] `docs/development_session.md` — Not cruft, active daily workflow doc
