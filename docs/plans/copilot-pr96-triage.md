# Copilot PR #96 Review Triage

## 1. `scripts/copy_material_lines.py:54` — DRY RUN rollback fires in LIVE mode
**Genuine bug.** When no source lines exist and `--live` is passed, it raises `RuntimeError("DRY RUN rollback")` unconditionally. Should log and return cleanly in LIVE mode; only raise the rollback exception when DRY_RUN is true.

## 2. `apps/workflow/views/company_defaults_logo_api.py:27` — DELETE needs JSONParser
**Genuine bug.** Frontend sends `Content-Type: application/json` for DELETE, but the view only declares `MultiPartParser` and `FormParser`. Will get 415 or empty `request.data`. Add `JSONParser` to parser_classes.

## 3. `apps/purchasing/services/stock_service.py:38` — N UPDATEs for ext_refs
**Copilot overengineering.** Stock merges are rare admin operations. Per-row save is clear and correct. Bulk jsonb_set would be premature optimization.

## 4. `.env.precommit:7` — Missing TEST_DB_USER/TEST_DB_PASSWORD
**Not a bug.** Pre-commit only runs linters, not tests. `settings_test.py` is only loaded by pytest. Should add them for completeness .

## 5. `scripts/production_data_fixer.py:23` — Wrong DJANGO_SETTINGS_MODULE
**Genuine bug.** Uses stale `jobs_manager.settings` — should be `docketworks.settings`.

## 6. `scripts/move_time_between_jobs.py:20` — Wrong DJANGO_SETTINGS_MODULE
**Genuine bug.** Same stale `jobs_manager.settings` reference.

## 7. `scripts/dump_settings.py:128` — Legacy MySQL env vars
**Genuine bug.** Dumps `MYSQL_DB_USER`/`MYSQL_DATABASE` which no longer exist. Should be `DB_USER`/`DB_NAME`.

## 8. `frontend/tests/scripts/db-backup-utils.ts:96` — Required DB_HOST/DB_PORT
**Genuine bug.** DB_HOST and DB_PORT aren't in `.env.example` but are required by this code. Add them to .env.example.

## 9. `apps/job/services/workshop_pdf_service.py:530` — Hard fail without logo_wide
**Copilot overengineering.** Fail early, no fallbacks. Logos are configured during onboarding before PDFs are generated. ValueError is correct.

## 10. `scripts/restore_checks/check_ai_providers.py:15` — Mismatched Mistral imports
**Genuine bug.** Check script uses `from mistralai.client import Mistral` but actual provider uses `from mistralai.client.sdk import Mistral`. Health check tests the wrong import path.

## 11. `docs/initial_install.md:236` — Missing `sudo -u postgres`
**Genuine bug in docs.** Script requires superuser (says so in its own header). Docs should say `sudo -u postgres ./scripts/setup_database.sh --drop`.

## 12. `scripts/uat/uat-base-setup.sh:143` — Hardcoded dw_test password
**Copilot overengineering.** Test-only role for pytest, local connections only. Fine as-is.

## 13. `frontend/tests/scripts/backup-db.sh:41` — Missing `--clean` in pg_dump
**Genuine bug.** Restore feeds dump into existing DB via `psql < file`. Without `--clean`, existing objects cause errors. global-setup.ts already uses `--clean` — this script should match.

## 14. `apps/workflow/migrations/0187_create_xero_pay_item.py:50` — Multiplier for leave types
**Genuine bug.** Model docstring says `multiplier=NULL` for leave types, `__str__` and `get_by_multiplier` logic depend on NULL. Seeds set Decimal values instead of None. Sick Leave at 1.0 would wrongly match `get_by_multiplier(1.0)`.

## 15. `scripts/upgrade_script.py:36` — No timeout on requests.get
**Minor improvement.** Admin script, not production. But `timeout=10` and `raise_for_status()` are trivially easy and prevent confusing errors. Quick fix.

## 16. `apps/purchasing/services/purchase_order_pdf_service.py:77` — Hard fail without logo
**Copilot overengineering.** Same as #9 — fail early, no fallbacks. Correct per project philosophy.

## 17. `docketworks/settings_test.py:17` — Required TEST_DB vars
**Copilot overengineering.** Intentional fail-fast. `.env.example` documents them. No defaults wanted.

## 18. `pyproject.toml:62` — Both psycopg and psycopg2-binary
**Worth investigating.** Django's postgresql backend uses psycopg2 by default. Having both is confusing. Verify which is needed, remove the other.

## 19. `docs/backup-restore-process.md:165` — Missing `sudo -u postgres`
**Genuine bug in docs.** Same as #11.

## 20. `scripts/setup_database.sh:77` — SQL injection via password interpolation
**Low priority.** Admin scripts reading admin-controlled `.env`. Not user-facing input. But a password with a single quote would break the SQL. Worth fixing eventually.

## 21. `scripts/production_data_fixer.py:97` — Misleading `--dry-run` flag
**Make code clearer.** `--dry-run` arg is declared but never read — `dry_run` derived from `not args.live`. Remove the dead `--dry-run` argument.

## 22. `apps/workflow/views/company_defaults_logo_api.py:14` — SVG + ImageField
**Genuine bug.** View allows `.svg` uploads but model uses `ImageField` (Pillow can't process SVGs). Upload passes extension check then fails at model validation. Remove `.svg` from ALLOWED_EXTENSIONS.

## 23. `apps/workflow/api/xero/sync.py:1295` — Missing space in warning
**Genuine bug (cosmetic).** String literal concatenation produces `"first.In Prod:"` — missing space.

## 24. `scripts/uat/uat-instance.sh:208` — SQL injection in heredoc
**Low priority.** Same as #20 — admin-controlled passwords. Single quote would break it.

---

# Summary

**Genuine bugs to fix (11):** #1, #2, #5, #6, #7, #8, #10, #11, #13, #14, #22
**Genuine bugs in docs (2):** #11, #19
**Cosmetic fix (1):** #23
**Code clarity improvements (2):** #15, #21
**Worth investigating (1):** #18
**Low priority (2):** #20, #24
**Copilot overengineering — skip (5):** #3, #9, #12, #16, #17
**Not a bug (1):** #4
