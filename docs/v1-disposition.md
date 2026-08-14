# v1 operational asset disposition

Ruling (2026-08-14): every v1 doc and script is **ported** — the default — or
**dropped** with a rejecting fact that survives scrutiny. There is no third
tier; the former "post-launch: describe it well enough to rebuild" disposition
is abolished. Code whose v2 feature does not exist yet is marked
**`blocked-by:<feature>`**, naming the specific feature it lands with; its
documentation is ported now, and the code arrives with the feature — never
before it.

This file is written to survive the v1 repository's deletion: it must stay
usable when reading v1 stops being an option. The port record it indexes is the
v2 **working tree** — every "ported" path below was verified to exist there. A
`blocked-by` entry names its blocker precisely so the feature's slice knows
what it owes.

## The producer half of the refresh flow

**`manage.py backport_data_backup` is ported**:
`apps/diagnostics/management/commands/backport_data_backup.py`, with the
scrubber at `apps/diagnostics/services/db_scrubber.py` (staff profiles in
`apps/diagnostics/services/staff_anonymization.py`, shared process plumbing in
`apps/diagnostics/services/scrub_pipeline.py`). It is the producer half of
[`restore-prod-to-nonprod.md`](restore-prod-to-nonprod.md):
`scripts/ops/pull_prod_backup.sh` invokes it over ssh on the production host.
It pipes `pg_dump` of the live database into the `scrub` connection alias
(`SCRUB_DB_NAME`, which must end in `_scrub` or settings, command and scrubber
all refuse), anonymises the configured PII columns, deletes accounting records
not linked to a job, truncates the excluded tables, strips every
database-backed external-system credential, writes a
`<dump>.migrations.json` ledger snapshot beside the archive, and re-dumps the
scrubbed copy to `<BASE_DIR>/restore/` or a named `--output` path. Raw
production data never lands on disk on either host.
`scripts/ops/verify_scrubbed_backup.py` remains the acceptance check of its
output.

**Until cutover the production hosts run v1 and therefore v1's copy of this
command** — the v2 port takes over when those hosts move to v2. A live
rehearsal of the v2 command against production is a cutover-checklist item.
Instances created before the scrub database existed gain it with one
`sudo scripts/server/instance.sh reconfigure <client> <env>`.

## scripts/

| v1 asset | disposition | note |
|---|---|---|
| `analyze_company_people.py` | dropped | One-shot survey of duplicate and empty person names feeding a manual merge pass; the repair tool it fed is ported as the `merge_companies` command. |
| `backup_db.sh` | ported | `scripts/backup_db.sh` |
| `backup_instance_files.sh` | ported | `scripts/backup_instance_files.sh` |
| `check_mypy.sh` | dropped | Ran mypy against `mypy-baseline.txt` and failed only on new errors. v2 runs mypy strict with a zero baseline as a pre-commit hook, so there is nothing for a baseline-tolerant wrapper to do. |
| `check_naive_local_dates.py` | ported | `scripts/checks/check_naive_local_dates.py`, wired as the `check-naive-local-dates` hook in the cheap tier. The gate forbids `timezone.now().date()` and its aliases — UTC-aware now gives the UTC calendar date, the wrong day for any "what day is it here" question — and enforces `django.utils.timezone.localdate()`, which ruff's DTZ rules do not cover. |
| `check_requirements.sh`, `generate_requirements.sh` | dropped | Exported and verified `requirements.txt` against `poetry.lock` for an external analysis tool. v2 uses uv and `uv.lock`; deptry gates dependency hygiene. |
| `cleanup_backups.py`, `cleanup_backups.sh` | ported | `scripts/cleanup_backups.py`, `scripts/cleanup_backups.sh` |
| `copy_material_lines.py` | dropped | One-shot move of material cost lines between two named jobs, run through `manage.py shell`. |
| `debug_xero_fetch.py` | dropped | Live probe that the rate-limited Xero REST client honours a 429. v2 pins that behaviour in unit tests (`apps/xero/tests/test_sync_quota_gates.py`), which run on every push instead of on an operator's memory. |
| `detect_fstrings_without_placeholder.py` | ported | Ruff `F541` (the `F` rule set is selected in `pyproject.toml`). |
| `dump_settings.py` | ported | `scripts/ops/dump_settings.py` — sanitised JSON snapshot of the running configuration for diagnosing an instance whose behaviour does not match its expected settings. |
| `explore_google_drive.py`, `read_google_doc.py`, `write_google_doc.py`, `set_doc_screenshot.py`, `get_gapi_token.py`, `google_doc_manifest.json`, `create_master_template.py` | ported | The Google Docs/Drive authoring toolchain, ported wholesale into `scripts/gdocs/` under the same names, with the shared delegated-service-account auth factored into `scripts/gdocs/gauth.py`. They author the Google-Doc-backed `Procedure` records the process app links to. |
| `find_duplicates.py` | ported | `scripts/checks/find_duplicates.py`, wired as a pre-commit hook. |
| `find_late_imports.py` | ported | Ruff `PLC0415` (import outside top level), which v2 suppresses individually where a cycle makes a late import correct. |
| `find_wrapper_candidates.py` | dropped | Found short functions with few callers to drive a wrapper-deletion campaign against v1's accumulated indirection. v2's standing equivalents are the find-duplicates hook and the generated `docs/code-quality.md` metrics. |
| `fix_test_company.py` | ported | `scripts/ops/fix_test_company.py` |
| `fix_welding_stock_cost.py` | dropped | One-shot repair of a single stock item's unit cost, already applied to production data. |
| `generate_url_docs.py` | dropped | Generated per-app Markdown URL listings. v2's route inventory is the exported OpenAPI schema, regenerated and gated by `scripts/checks/export_openapi.py`. |
| `geocode_addresses.py` | ported | `scripts/ops/geocode_addresses.py` — the backfill sweep over rows that predate on-write geocoding (`apps/company/services/geocoding_service.py`). |
| `migrate_to_snapshot.py` | ported | `scripts/ops/migrate_to_snapshot.py` — applies migrations up to the `migrations.json` snapshot a backup archive ships, so a dump migrates to exactly the graph it came from. |
| `move_time_between_jobs.py` | ported | `scripts/ops/move_time_between_jobs.py` — moves every actual time entry from one job number to another, dry-run by default. |
| `payroll_reconciliation.py` | ported | Its draft functions became `apps/accounting/services/payroll_reconciliation_service.py`. |
| `poc_phone_provider_scraper.py` | ported | `scripts/ops/poc_phone_provider_scraper.py`. Deliberately not a Beat harness: provider-side deletion must be exercised through the real Celery Beat task, never through this script. |
| `populate_product_mappings.py` | ported | Batch parsing of supplier products into product-parsing mappings is the scraper's end-of-run fill in `apps/quoting`. |
| `production_data_fixer.py` | dropped | A menu of idempotent repairs for known v1 data defects. The defects it addressed were repaired in production by v1's data-repair release, and `scripts/ops/validate_restored_data.py` is v2's standing check that a load holds no row the models reject. |
| `pull_prod_backup.sh` | ported | `scripts/ops/pull_prod_backup.sh` |
| `pull_prod_files.sh` | blocked-by:session-replay-storage-decision | Rsyncs a production instance's mutable file directories (`mediafiles/`, `phone-recordings/`, `session-replays/`) into the local storage roots over sudo-rsync — the file-side companion to the database pull. v2 has no replay ingestion and no replay storage root (`apps/diagnostics/tasks.py` records this), so the script has no destination to define until that decision is taken. Not needed by the E2E suite (the job-attachments spec uploads its own fixture); `scripts/ops/recreate_jobfiles.py` covers job-file rows restored without their bytes. |
| `predeploy_backup.sh` | ported | `scripts/predeploy_backup.sh` |
| `push_companies_to_xero.py` | ported | Superseded by the contacts phase of `apps/xero/seeding.py`, driven by `manage.py seed_xero_from_database`. |
| `recreate_jobfiles.py` | ported | `scripts/ops/recreate_jobfiles.py` |
| `regen_golden_pdfs.py` | ported | `scripts/generate/regen_golden_pdfs.py` |
| `regen_openapi_schema.sh`, `update_schema.sh` | ported | `scripts/checks/export_openapi.py` (regenerates on drift, gated on push) plus `npm run gen:api` for the client. |
| `rollback.sh` | ported | `scripts/rollback.sh` |
| `setup_database.sh` | dropped | Created or reset the PostgreSQL database and role as the postgres user. Dev database creation is documented directly in [`initial_install.md`](initial_install.md); instance databases and roles are created by `scripts/server/instance.sh`. |
| `setup_demo_payroll.py` | ported | `scripts/ops/setup_demo_payroll.py` — full port with live SDK calls that set tax code, KiwiSaver, bank account and pay template on demo-organisation employees. The NZ IRD check-digit is inlined with its ADR 0032 recorded reason (replace with `stdnum` when Phase 4 lands). |
| `setup_dev_logins.py` | ported | `scripts/ops/setup_dev_logins.py` |
| `test_chat_conversation.py`, `test_full_quote_conversation.py` | ported | `scripts/ops/test_chat_conversation.py`, `scripts/ops/test_full_quote_conversation.py`, shared plumbing in `scripts/ops/quote_chat_harness.py`. One flag is blocked-by:ai-gateway-attachments — `--with-file` refuses with the reason: the ADR 0041 gateway is text-only, so attaching a file would silently test nothing. |
| `test_kpi_service.py` | dropped | Command-line harness for the KPI calendar service. v2's `apps/accounting/services/kpi_service.py` has unit tests. |
| `test_login_logging.py` | dropped | Drove real login attempts with Selenium to prove failures reach `auth.log` with client IPs. v2 has no Selenium dependency, and the log shapes that matter are pinned by the fail2ban filter tests in `scripts/server/test_server_templates.sh`. |
| `test_quote_import.py` | blocked-by:quote-import | Ported as a refusing harness at `scripts/ops/test_quote_import.py`: the argument surface (`--file`, `--job-id`, `--preview-only`) is kept so the eventual port drops straight in, and it refuses to run until v1's `import_quote_service` has a v2 counterpart. |
| `test_xero_payroll.py` | ported | `scripts/ops/test_xero_payroll.py` — walks the Xero Payroll NZ endpoints one at a time to show which scope or subscription is missing, rather than leaving one opaque 403. |
| `test_release_utils.sh` | ported | `scripts/test_release_utils.sh`, wired as a pre-commit hook. |
| `update_init.py` | dropped | Rewrote package `__init__.py` files with import lists classified by Django-startup safety. v2 keeps explicit module paths under an import-linter contract; generated re-export surfaces are how v1's parallel implementations stayed invisible. |
| `upgrade_script.py` | dropped | Read `pyproject.toml`, queried PyPI and printed how far behind each dependency was. uv reports and applies dependency upgrades directly. |
| `validate_restore_progress.py` | dropped | Enforced that Xero OAuth had happened before the later restore steps ran. In v2 the ordering is enforced by the tools themselves: each Xero command gates on a valid token and exits non-zero, and the runbook states the same gate for a human. |
| `verify_scrubbed_backup.py` | ported | `scripts/ops/verify_scrubbed_backup.py` |
| `pre-push` (git hook) | ported | The pre-push stage of `.pre-commit-config.yaml`. |
| `README.md` | dropped | Indexed v1's hooks and ad-hoc scripts. v2's hooks are declared in `.pre-commit-config.yaml` and its gate tiers in `CLAUDE.md`; a hand-maintained second index drifts. |

## scripts/restore_checks/

Every file ported, into `scripts/ops/restore_checks/`. What each asserts about a
restored database:

- `check_django_orm.py` — the ORM answers and the core tables hold plausible
  counts, which is the first proof a load completed.
- `check_admin_user.py` — the default admin exists and is currently active.
- `check_company_defaults.py` — the singleton company defaults row is populated.
- `check_ai_providers.py` — each configured AI provider answers a live call.
- `check_jobfiles.py` — every job-file row has bytes on disk behind it.
- `check_shop_company.py` — the internal shop company exists under its fixed
  identifier.
- `check_test_company.py` — the company named by `test_company_name` exists,
  which the Xero seed requires.
- `check_xero_app.py` — exactly one active Xero application row, with its webhook
  key set.
- `check_xero_accounts.py` — the chart of accounts mirrored from Xero is present.
- `check_xero_seed.py` — the counts the seed should have produced.
- `fix_shop_company.py` — the one mutation in the directory: repairs the shop
  company's name.
- `test_serializers.py` — walks the restored dataset through every wire contract.
- `test_kanban_api.py` — the kanban route answers over an authenticated request.

Three carry a recorded narrowing or adaptation in their own docstrings, because
v2's shape differs:

| v1 asset | disposition | note |
|---|---|---|
| `check_admin_user.py` | ported | v2's `Staff` has no `is_active` field; the check reports `date_left is None`, which is v2's currently-active semantics. |
| `check_ai_providers.py` | ported | v1 probed Mistral through the `mistralai` SDK's model listing. v2 has one LLM gateway (ADR 0041), so all three providers are validated by a chat completion through it — the same call every real feature makes. A provider row configured with a non-chat model fails this check, correctly. |
| `test_serializers.py` | ported | v2 has no DRF serializers; each sub-test calls the service function the real route calls and validates its output against the matching schema. Timesheet coverage is narrower: v2 has no flat-queryset builder for timesheet cost lines, so time-kind lines go through the generic cost-line pipeline. |

## scripts/integration/

| v1 asset | disposition | note |
|---|---|---|
| `verify_xero_batch_order.py` | ported | `scripts/integration/verify_xero_batch_order.py` — live probe that Xero's create-contacts endpoint answers in submission order, because the seeding path maps responses to local rows by position. The runtime defence remains the name-mismatch tripwire in `apps/xero/seeding.py`, which aborts rather than mislinks. |
| `verify_xero_client_quote_contract.py` | ported | `scripts/integration/verify_xero_client_quote_contract.py` — end-to-end contract check that the public app API and Xero agree on company and quote contact data. It writes real records in both systems; operator-run for incident investigation, never part of the default suite. |
| `README.md` | dropped | Its content — these scripts mutate real external systems and are not part of the default suite — is stated in the entries above and in the scripts' own docstrings. |

## scripts/server/

The server provisioning suite ported wholesale into `scripts/server/`:
`README.md`, `common.sh`, `server-setup.sh`, `instance.sh`, `deploy.sh`,
`dw-run.sh`, `release-utils.sh` and the `certbot-dreamhost-auth.sh` /
`certbot-dreamhost-cleanup.sh` DNS-01 hooks, each under the same name. v2 adds
`test_server_templates.sh` (which shellchecks the suite and renders every
template, and has no v1 counterpart), `verify-instance.sh`, the `cutover/`
scripts, the fail2ban filters and jail, and the nginx rate-limit configuration.

| v1 asset | disposition | note |
|---|---|---|
| `migrate-test-role.sh` | dropped | One-off migration for instances created before per-tenant pytest roles existed: it gave one tenant its own `dw_<instance>_test` role and database in place of the shared cluster-wide `dw_test` role. v2's `instance.sh` creates the per-tenant `dw_<client>_<env>_test` role at instance creation (landing in this branch), so there is no pre-change instance to migrate. |

### scripts/server/templates/

Every v1 template ports under its own name into `scripts/server/templates/`,
where `instance.sh` renders it per instance:

| v1 template | disposition | note |
|---|---|---|
| `env-instance.template` | ported | The instance's `.env`, with v2's own variable set. |
| `credentials-instance.template` | ported | The root-owned per-instance credentials file `instance.sh prepare-config` scaffolds. |
| `gunicorn-instance.service.template` | ported | v2's unit runs the ASGI application under uvicorn workers (ADR 0047). |
| `celery-worker-instance.service.template` | ported | The instance's Celery worker unit. |
| `celery-beat-instance.service.template` | ported | The instance's Beat unit; v2's schedule lives in code rather than in the database. |
| `nginx-instance.conf.template` | ported | The instance's site, now paired with v2's `nginx-ratelimit.conf`. |
| `sudoers-instance.template` | ported | The narrow sudo rights the instance user needs for its own services. |
| `logrotate-docketworks.conf` | ported | Log rotation for the instance log directories. |
| `backup-db-instance.service.template`, `backup-db-instance.timer.template` | ported | The nightly database backup unit and its timer. |
| `backup-files-instance.service.template`, `backup-files-instance.timer.template` | ported | The nightly file backup unit and its timer. |
| `ai-providers.json.template` | ported | Rendered into the instance's private fixture directory and loaded when no provider row exists. |
| `xero-apps.json.template` | ported | Same mechanism, for the Xero application registration. |
| `phone-provider-settings.json.template` | ported | Same mechanism, for the CRM phone provider's base URL, credentials and account code. `instance.sh` loads it only when the settings singleton is still unconfigured, so a reconfigure never overwrites live values, and a local development database deliberately has no row at all — that is what stops development Celery reaching the production phone system. |

## adhoc/

v1's `adhoc/` directory held sixteen session scratch scripts. Two are ported;
the rest reject on facts in the files themselves. Several boot
`jobs_manager.settings` — a settings module that predates v1's rename to
`docketworks.settings` — and so cannot run against any surviving checkout.

| v1 asset | disposition | note |
|---|---|---|
| `debug_xero_email_drop.py` | ported | `scripts/ops/debug_xero_email_drop.py` |
| `drive_storage_check.py` | ported | `scripts/gdocs/drive_storage_check.py` |
| `capture_xero_contact_response.py` | dropped | Captured one live create-contacts response to a fixture file. Superseded by the code builders in `apps/xero/tests/xero_fixtures.py`, which construct production-shaped responses (provenance recorded in that module's docstring). |
| `debug_time_entry_mapping.py` | dropped | Probe of the Xero SDK's `TimeEntryCreateOrUpdate` behaviour, written while v1's payroll sync was being developed; boots the dead `jobs_manager.settings` module. |
| `debug_xero_serialization.py` | dropped | One-off Xero serialization probe from the same development session; boots the dead `jobs_manager.settings` module. |
| `fix_missing_default_tasks.py` | dropped | Self-described dev-only one-off, already applied: created default tasks on jobs that had Xero projects but no `xero_default_task_id`. Xero Projects itself is unported (see the seed's projects phase below). |
| `import_supplier_products_one_off.py` | dropped | Self-named one-off supplier product import, applied. |
| `simple_drive_test.py` | dropped | Bare Google Drive API access probe. Superseded by the `scripts/gdocs/` toolchain, which lists Drive visibility as a maintained tool. |
| `test_actual_job_sync.py` | dropped | Scaffolding for writing v1's `sync_job_to_xero` — its docstring says it exists to help write that function and must never call it. The function exists and its behaviour is pinned by v2's xero tests. |
| `test_costline_sync.py` | dropped | Force-sync probe from the same sync-development effort; boots the dead `jobs_manager.settings` module. |
| `test_google_drive.py` | dropped | Drive folder-permission probe. Superseded by the `scripts/gdocs/` toolchain. |
| `test_mcp_shell.py` | dropped | `manage.py shell` walk of the MCP quoting tools during their development; the tools' behaviour is pinned by unit tests, not by a paste-into-shell script. |
| `test_pdf_parsing.py` | dropped | Development probe of Gemini price-list extraction called through the direct-SDK shape ADR 0041 abolished; v2's extraction goes through the LLM gateway. |
| `test_quote_chat_api.py` | dropped | Probed a DRF content-negotiation 406 on the quote chat endpoint. Moot under django-ninja, which has no content-negotiation layer to misconfigure. |
| `test_template_access.py` | dropped | Probe of access to the quote template spreadsheet. Superseded by the `scripts/gdocs/` toolchain. |
| `upgrade_script.py` | dropped | Byte-for-purpose duplicate of `scripts/upgrade_script.py` (v1's duplication pathology in one file); both are poetry-era and die with the uv move. |

## Management commands

| v1 asset | disposition | note |
|---|---|---|
| `workflow/backport_data_backup.py` | ported | `apps/diagnostics/management/commands/backport_data_backup.py` with `apps/diagnostics/services/db_scrubber.py`; see the producer section at the top of this file. The v1 `--analyze-fields` field sampler is dropped — the PII contract is pinned by `scripts/ops/verify_scrubbed_backup.py` and the scrubber tests, not by an operator eyeballing samples. |
| `workflow/xero.py` | ported | `apps/xero/management/commands/xero.py`, carrying `--setup`, `--seed-xero` and `--configure-payroll`. The other flags are listed under "Deferred Xero capability" below. |
| `workflow/seed_xero_from_database.py` | ported | `apps/xero/management/commands/seed_xero_from_database.py`, with the accounts, contacts, invoices, quotes and stock phases. The employees and projects phases are blocked — see "Deferred Xero capability". |
| `workflow/start_xero_sync.py` | ported | `apps/xero/management/commands/start_xero_sync.py`, which additionally holds the shared sync lock so an inline run cannot interleave with a beat-dispatched one. |
| `workflow/e2e_cleanup.py` | ported | `apps/diagnostics/management/commands/e2e_cleanup.py` |
| `workflow/inspect_xero_quote_pdf.py` | ported | `apps/accounting/management/commands/inspect_xero_quote_pdf.py` |
| `workflow/rollback_migrations.py` | ported | `apps/core/management/commands/rollback_migrations.py` |
| `workflow/sync_sequences.py` | ported | `apps/core/management/commands/sync_sequences.py` |
| `workflow/create_service_api_key.py` | ported | `apps/core/management/commands/create_service_api_key.py` (tests in `apps/core/tests/test_create_service_api_key.py`) — mints a named `ServiceApiKey` row for service-level authentication, printing the key once. |
| `workflow/finalize_instance_onboarding.py` | ported | `apps/xero/management/commands/finalize_instance_onboarding.py` — the post-OAuth onboarding sequence for a FRESH instance: import or create staff from the connected Xero organisation, sync pay items, then enable sync. Deliberately not used by a restore, which re-points an existing dataset instead — the restore path is `xero --setup`, `--configure-payroll` and `seed_xero_from_database`. |
| `workflow/export_dev_demo_dump.py` | ported | `apps/diagnostics/management/commands/export_dev_demo_dump.py`, with its separate lighter scrubber `apps/diagnostics/services/dev_demo_export_scrubber.py`: the audience is a trusted external data-warehouse demonstration, so it removes credentials and direct identifiers rather than anonymising everything. |
| `workflow/backfill_kanban_search_telemetry.py` | dropped | Backfilled legacy `kanban_search.log` lines into search telemetry rows. v2 writes telemetry from the search path itself and no v2 instance has that log. |
| `accounts/flag_weak_passwords.py` | ported | `apps/accounts/management/commands/flag_weak_passwords.py` (tests in `apps/accounts/tests/test_flag_weak_passwords.py`) — marks every user as requiring a password reset at next login. |
| accounts password-reset email flow (`token_view.py`, `serializers.py`) | blocked-by:email-feature | v1's accounts app sent password-reset emails from its token views. v2 consumes no `EMAIL_*` settings and sends no mail; only the `password_needs_reset` flag exists. The email flow lands with the email feature. |
| `job/create_shop_jobs.py` | ported | `apps/job/management/commands/create_shop_jobs.py` — creates the internal shop jobs, the overhead jobs time is booked against when it is not billable. Nine jobs, named exactly: Business Development, Bench - busy work, Worker Admin, Office Admin, Annual Leave, Sick Leave, Bereavement Leave, Travel, Training. The names are a contract: the E2E timesheet specs find the annual leave job by name, so a restored dataset carries them and only a fresh instance needs this command. |
| `job/set_paid_flag_jobs.py` | ported | `apps/job/management/commands/set_paid_flag_jobs.py` — sets the paid flag on completed jobs whose invoices are paid, with dry-run and verbose modes; the same sweep runs nightly from the beat schedule. |
| `job/test_gemini_chat.py` | ported | Renamed to `apps/job/management/commands/ai_chat_harness.py`. The rename is recorded in its docstring: the ADR 0041 gateway routes to whichever provider is configured, so "gemini" would be a lie half the time. |
| `process/import_dropbox_hs_documents.py` | ported | `apps/process/management/commands/import_dropbox_hs_documents.py` — walks a Dropbox health-and-safety folder tree, finds `.doc`/`.docx` files following the `Doc.NNN` naming convention, and creates procedure or form records with the type, tags and metadata implied by their location. A one-per-client import, not a sync. |
| `company/merge_companies.py` | ported | `apps/company/management/commands/merge_companies.py` |
| `quoting/run_scrapers.py` | ported | `apps/quoting/management/commands/run_scrapers.py` |
| `timesheet/create_leave_entries.py` | ported | `apps/timesheet/management/commands/create_leave_entries.py` — backfills leave entries to match what Xero payroll shows, for staff who took leave without logging it. |
| `timesheet/create_overtime_entries.py` | ported | `apps/timesheet/management/commands/create_overtime_entries.py` — closes the gap between local hours and Xero payroll hours for a staff week, overtime first up to the overtime headroom. |
| `timesheet/reclassify_overtime_entries.py` | ported | `apps/timesheet/management/commands/reclassify_overtime_entries.py` — the companion case: totals already agree but too few hours are classified as overtime. |
| `timesheet/create_special_job.py` | ported | `apps/timesheet/management/commands/create_special_job.py` |
| `timesheet/reassign_time_entries.py` | ported | `apps/timesheet/management/commands/reassign_time_entries.py` — moves time entries between staff, updating unit cost to the new person's wage rate. Shared plumbing for the five repair commands lives in `apps/timesheet/management/commands/_repair_shared.py`. |

## Celery beat schedule

The authority in v1 was `apps/workflow/migrations/0003_seed_celery_beat_schedules.py`,
which seeded nine periodic tasks into the django-celery-beat tables.

| v1 beat entry | disposition | note |
|---|---|---|
| `xero_heartbeat`, `xero_regular_sync`, `xero_30_day_sync`, `run_all_scrapers_weekly`, `set_paid_flag_jobs`, `auto_archive_completed_jobs`, `parse_unparsed_stock_items_hourly`, `purge_old_session_replays_daily` | ported | `config/celery.py` — the schedule lives in code, not in seed migrations, each entry stamped with its `periodic_task_name` header (see that module for why). The `SESSION_REPLAY_RETENTION_DAYS` env knob is folded into code at `apps/diagnostics/tasks.py`: every v1 environment set 14 and the knob never varied. |
| `recompute_workshop_schedule` | blocked-by:operations-scheduling | The task does not exist in v2 — operations scheduling is a schema shell (`rewrite-status.md`). `config/celery.py` records the pending entry in a comment where the schedule lives; the beat entry lands with the algorithm, never before, because scheduling a task that dispatches nothing fails silently. |

## Fixtures

| v1 asset | disposition | note |
|---|---|---|
| `apps/workflow/fixtures/ai_providers.json` (+ `.example`) | ported | Server path: `scripts/server/templates/ai-providers.json.template`, rendered per instance by `instance.sh` into the instance's private fixture directory. Dev path: `apps/ai/fixtures/ai_providers.json.example`, copied to the gitignored real name and loaded by hand (`docs/initial_install.md`). |
| `apps/workflow/fixtures/xero_apps.json` (+ `.example`) | ported | Server path: `scripts/server/templates/xero-apps.json.template`, same mechanism. Dev path: `apps/xero/fixtures/xero_apps.json.example`. |
| `apps/workflow/fixtures/company_defaults.json` | ported | `apps/core/fixtures/company_defaults.json` (loadable demo fixture); `scripts/server/templates/company-defaults.json.template` is a symlink to it, so the two cannot drift. |
| `apps/workflow/fixtures/company_defaults_prospect.json` | ported | `scripts/server/templates/company-defaults-prospect.json.template` |
| `apps/workflow/fixtures/initial_data.json` | ported | `apps/accounts/fixtures/initial_data.json` (provenance in `apps/accounts/fixtures/README.md`): eleven demo staff plus the phone endpoints they answer, for demo instances. |

Three orphan test fixtures reject on their own content or history:

| v1 asset | disposition | note |
|---|---|---|
| `apps/quoting/tests/fixtures/ocr_responses/wm_aluminium_price_list_ocr_results.json`, `apps/quoting/tests/fixtures/expected_results/wm_aluminium_expected.json` | dropped | The files self-declare their invalidity in their first key — `"WARNING: THIS FILE IS WRONG. Kept to remind me to regnerate it (correctly)"` — and no v1 revision's code ever referenced them. |
| `apps/job/tests/fixtures/chat_test_data.json` | dropped | Orphan: the suite that loaded it was deleted in v1, and no revision's surviving code reads it. |
| `apps/workflow/tests/fixtures/xero_create_contacts_response.json` | dropped | Superseded, with its capture script (see adhoc/), by the code builders in `apps/xero/tests/xero_fixtures.py` — production-shaped, provenance in that module's docstring. |

## docs/

| v1 asset | disposition | note |
|---|---|---|
| `README.md` | ported | `docs/README.md` |
| `restore-prod-to-nonprod.md` | ported | [`restore-prod-to-nonprod.md`](restore-prod-to-nonprod.md), rewritten around v2's load path. |
| `restore-prod-to-hotfix.md` | ported | `docs/restore-prod-to-hotfix.md` — the hotfix checkout's refresh, differing from the non-production runbook only in which checkout, domain and database it targets. |
| `development_session.md` | ported | `docs/development_session.md`. It records the deliberate no-dev-server decision: v2 always runs the compiled frontend, and the everyday development environment IS the compiled-build E2E environment. |
| `initial_install.md` | ported | `docs/initial_install.md` |
| `ngrok_setup.md` | ported | `docs/ngrok_setup.md` |
| `server_setup.md` | ported | `docs/server_setup.md` |
| `client_onboarding.md` | ported | `docs/client_onboarding.md` — the onboarding specialist's handoff, from signed contract to running instance. Its email phase describes configuration v2 does not yet consume (blocked-by:email-feature, see the `.env.example` row below). |
| `instance-setup-demo.md` | ported | `docs/instance-setup-demo.md` — the demo variant: dummy staff (the `initial_data.json` fixture above) and a Xero Demo Company, which is recreated roughly monthly with a new tenant id. |
| `instance-setup-production.md` | ported | `docs/instance-setup-production.md` — the production variant: the payroll calendar, pay items and invoice branding theme must already exist in the real organisation; `xero --setup` validates rather than creates them there. |
| `xero_setup.md` | ported | `docs/xero_setup.md` — configuring the Xero side before an instance connects: payroll settings named as the application expects, then the developer app and OAuth callback registration. |
| `adr/` | ported | `docs/adr/`, numbering continuous with v1 — the v1 records themselves live on in v2. |
| `architecture.md` | dropped | A narrative description of the system's layers and flows. v2 states its architecture in `CLAUDE.md`'s layout and standards sections and in the ADRs, both of which are read before non-trivial work; a second narrative would drift from them without anything noticing. |
| `updating.md` | dropped | v1's deploy runbook plus a caveat about pre-squash dumps. Deploy is `server_setup.md`'s Part D and `scripts/server/README.md`. The caveat does not transfer: a dump predating v1's July 2026 migration squash needs a pre-squash v1 checkout to migrate, `scripts/ops/verify_scrubbed_backup.py` refuses such an archive outright, and v2's load path takes data only and never v1's migration ledger. |
| `jira-usage.md`, `jira.md` | dropped | The Jira project, board states, labels and definition of done. v2's work is tracked in the approved plan, `rewrite-status.md` and the cutover checklist. |
| `urls/` | dropped | Generated per-app URL listings, the output of `generate_url_docs.py`. The exported OpenAPI schema is v2's route inventory. |
| `function_character_counts.tsv`, `function_under_80_review.tsv` | dropped | Snapshots of a one-off function-length review. v2's `docs/code-quality.md` is generated, committed and gated, so its numbers move in the diff that moves them. |
| `.codesight/KNOWLEDGE.md` | dropped | A knowledge map generated by an external analysis tool over v1's history: decisions, notes and open questions extracted from commits and sessions. Its durable content is the ADRs, which v2 carries forward with continuous numbering. |
| `plans/`, `superpowers/`, `test_plans/`, `test_pdfs/` | dropped | Session planning documents, agent skill and spec directories, a single feature test plan, and price-list PDFs used as parser fixtures. v2 keeps its own `docs/plans/` and `docs/superpowers/`, and its parser fixtures live with the tests that read them. |

## frontend/docs/

Eight v1 documents port into `frontend/docs/` (the delta control guide and its
integrity QA checklist fold into one document); the rest reject:

| v1 asset | disposition | note |
|---|---|---|
| `DATA_AUTOMATION_IDS.md` | ported | `frontend/docs/data-automation-ids.md` |
| `e2e_testing_strategy.md` | ported | `frontend/docs/e2e-testing-strategy.md` |
| `jobview-delta-control-guide.md`, `job-delta-integrity-qa.md` | ported | Merged into `frontend/docs/job-delta-envelope.md` — the delta envelope contract with its QA checklist as a section. |
| `jobview-etag-guide.md` | ported | `frontend/docs/optimistic-concurrency.md` |
| `quote_learning_system.md` | ported | `frontend/docs/quote-insight-engine.md` |
| `output_columns.md` | ported | `frontend/docs/quote-output-columns.md` |
| `xero-payroll-ui-requirements.md` | ported | `frontend/docs/xero-payroll-ui-requirements.md` |
| `ZODIOS_REFACTOR_GUIDE.md` | dropped | Migration guide for a refactor completed in v1; v2's client is generated by @hey-api/openapi-ts and never went through Zodios. |
| `automated_regression_testing_overview.md` | dropped | Bootstrap plan for regression infrastructure that now exists: the Playwright suite, `run_e2e.sh` and the test-history reporting are the built thing the plan proposed. |
| `overview.md` | dropped | Overview of the Vue frontend; v2's frontend is React/TanStack and its shape is stated in `CLAUDE.md`'s layout section. |
| `troubleshooting/pinia-reactivity.md` | dropped | Pinia troubleshooting; v2 has no Pinia — server state lives in TanStack Query only. |
| `done/bugs_edit_estimate.md` | dropped | Closed session notes for a fixed v1 bug. |
| `plans/` | dropped | Empty directory; nothing in it to port. |

## Frontend E2E harness

| v1 asset | disposition | note |
|---|---|---|
| `global-setup.ts`, `global-teardown.ts`, `e2e-reset.ts`, `e2e-sync-windows.ts`, `db-backup-utils.ts` | ported | `frontend/tests/scripts/`, including the database restore and the preservation and re-injection of the Xero token material across it. |
| `xero-login.ts` | ported | `frontend/tests/scripts/xero-login.ts` — Playwright automation of the Xero OAuth consent. It signs in to the app with `E2E_TEST_USERNAME`/`E2E_TEST_PASSWORD` and completes Xero's consent screens with `XERO_USERNAME`/`XERO_PASSWORD`, all loaded from the frontend `.env` (then `.env.test`); `APP_DOMAIN` comes from the backend `.env`. The manual equivalent is the consent step in the restore runbook, started on the instance's ngrok domain because that is where the registered callback points. |
| `analyze-e2e-rolling.ts`, `analyze-e2e-trends.ts`, `analyze-network.ts`, `analyze-timing.ts`, `extract-trace-timing.ts`, `history-reporter.ts`, `backfill-e2e-git-metadata.ts` | ported | `frontend/tests/scripts/`, same names — the E2E history and analysis family: rolling pass rates, per-spec trends, per-test timing from Playwright traces, and network waterfalls, so a flaky or slowing spec is a visible trend rather than one bad afternoon. Shared source handling is factored into `history-sources.ts` and trace parsing into `trace-entries.ts`; run recording is `process-result.ts`. |
| `backup-db.sh`, `restore-db.sh` | ported | Their behaviour lives in `frontend/tests/scripts/db-backup-utils.ts`. |
| `frontend/tests/fixtures/` (`api.ts`, `auth.ts`, `debug-forwarder.ts`, `helpers.ts`, `files/sample-attachment.txt`) | ported | `frontend/tests/e2e/fixtures/` and `frontend/tests/e2e/helpers.ts`, including the upload fixture `files/sample-attachment.txt`. |
| `frontend/test-history/` (the run-history corpus) | ported | Archived outside the repo at `/home/corrin/docketworks-v1-archive/test-history/` (~1 GB). The analysis scripts read it via `--include-v1-baseline` (`history-sources.ts`), tagging every row by era so v1 and v2 runs never blur; a missing archive is an error, not an empty merge. |

## frontend/scripts/

| v1 asset | disposition | note |
|---|---|---|
| `capture-screenshots.ts` | ported | `frontend/scripts/capture-screenshots.ts` |
| `report-patterns.js` | ported | `frontend/scripts/report-patterns.js` |
| `analyze_captures.cjs` | ported | `frontend/scripts/analyze_captures.cjs` |
| `capture_metrics.cjs` | ported | `frontend/scripts/capture_metrics.cjs` |
| `gen-api.js` | dropped | Hand-rolled client generation driver; v2 generates the client with @hey-api/openapi-ts (`npm run gen:api`). |
| `check-api-contract-boundary.js` | dropped | v2's `frontend/scripts/check-api-boundary.mjs` (the `frontend-boundary` hook) is strictly stronger: same rule, no allowlist. |
| `generate-typed-router.ts` | dropped | Hand-rolled route typing; v2 uses TanStack's router-plugin codegen. |
| `audit-numeric-conversions.sh`, `validate-migration.sh` | dropped | One-off audit scripts from a v1 migration campaign, referenced by nothing. |

## .github/

| v1 asset | disposition | note |
|---|---|---|
| `workflows/ci.yml` | ported | `.github/workflows/ci.yml`, rebuilt around v2's gate tiers. |
| `workflows/claude.yml` | ported | `.github/workflows/claude.yml` |
| `workflows/deploy-uat.yml` | ported | `.github/workflows/deploy-uat.yml` |
| `workflows/stale.yml` | ported | `.github/workflows/stale.yml` |
| `workflows/stoney-openapi-sync.yml` | dropped | Its consumer (stoneydev.com) was deleted (2026-08-14) — there is nothing to feed. |
| `copilot-instructions.md` | dropped | States v1-stack facts that are false in v2 (Vue frontend, Black formatting, mypy-baseline); the principles it carried are restated in `CLAUDE.md`. |
| `dependabot.yml` | ported | `.github/dependabot.yml` |
| `pull_request_template.md` | ported | `.github/pull_request_template.md` |

## .vscode/ and the workspace file

| v1 asset | disposition | note |
|---|---|---|
| `launch.json` | ported | `.vscode/launch.json` |
| `settings.json` | ported | `.vscode/settings.json` |
| `tasks.json` | ported | `.vscode/tasks.json`. The v1 "Frontend Dev Server" and "Start Dev Environment" tasks are deliberately not carried: `docs/development_session.md` records the no-dev-server decision — the development environment IS the compiled-build E2E environment ("Start E2E Environment"). |
| `settings_changes.log` | dropped | A 2026-03 debugging changelog for venv auto-activation. The surviving invariant is the configuration in `settings.json` itself; documents record state, not change. |
| `docketworks.code-workspace` | dropped | Presented the repo as two roots (backend plus the frontend subtree) with a login-shell terminal profile. v2's committed `.vscode/` configures the single root, and its tasks and launch configs address `frontend/` by path, so a second workspace root adds nothing. |

## Pre-commit hooks

v1's `.pre-commit-config.yaml` declared twenty-six hooks. Where a v1 hook's
job survives, the v2 hook that does it is named; the rest reject:

| v1 hook | disposition | note |
|---|---|---|
| `ruff`, `black`, `isort`, `flake8`, `autoflake`, `pylint-bugs` | ported | v2's `ruff` and `ruff-format` hooks: one tool owns formatting, import order, unused-code removal and the bug-pattern lints. |
| `detect-empty-fstring` | ported | Ruff `F541`. |
| `find-late-imports` | ported | Ruff `PLC0415`. |
| `find-duplicates` | ported | The `find-duplicates` hook (`scripts/checks/find_duplicates.py`). |
| `check-naive-local-dates` | ported | The `check-naive-local-dates` hook (`scripts/checks/check_naive_local_dates.py`). |
| `shellcheck` | ported | The `server-shell-checks` hook runs `scripts/server/test_server_templates.sh`, which shellchecks the suite and renders every template. |
| `spectacular-validate`, `update-frontend-schema` | ported | The `schema-current` hook (`scripts/checks/export_openapi.py`), which regenerates the exported schema on drift at push time. |
| `frontend-gen-api` | ported | `npm run gen:api` regenerates the client from the exported schema; the schema half is gated by `schema-current`. |
| `frontend-lint-staged` | ported | The `frontend-lint`, `frontend-format` and `frontend-boundary` hooks. |
| `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-added-large-files` | dropped | The generic hygiene repo. ruff-format and frontend-format normalise whitespace and final newlines in every file the formatters own; each durable YAML file is parsed by its consumer (pre-commit parses its own config on every run, GitHub parses the workflows and dependabot config); no v2 gate replaces the large-file check beyond GitHub's hard push limit. |
| `update-init-files` | dropped | Curated generated re-export surfaces; import-linter contracts over explicit module paths replaced re-export curation, and generated `__init__` surfaces are how v1's parallel implementations stayed invisible. |
| `generate-url-docs` | dropped | The exported OpenAPI schema is the route inventory. |
| `frontend-gen-typed-router` | dropped | See `generate-typed-router.ts` above — TanStack's router-plugin codegen. |
| `frontend-workflow-format` (`check:workflow-format`) | dropped | No v2 gate; CI parses the workflows and rejects malformed ones. |
| `codesight-requirements`, `codesight-code`, `codesight-frontend`, `codesight-knowledge` | dropped | Cache maintenance for an external analysis tool; its durable output was the ADRs, which v2 carries forward. |

## Repo-root configuration

| v1 asset | disposition | note |
|---|---|---|
| `.env.example` | ported | `.env.example`, with v2's own variable set. The `EMAIL_*` variables are deliberately absent: v2 consumes no email settings and sends no mail (blocked-by:email-feature — they return with the email flow). |
| `.env.precommit` | dropped | The no-secrets env v1's CI (and one payroll test) loaded. v2's `config/settings_test.py` loads the real `.env` when present and carries safe setdefaults matching the CI service containers, so no committed env file exists. |
| `.mcp.json.example` | dropped | Configured a `claude-code-mcp` server pointing at the then-separate frontend repository — a layout that stopped existing at v1's own subtree merge (ADR 0008). |
| `.shellcheckrc` | ported | Its two directives (follow `source`d files, resolve them relative to each script) became the `shellcheck -x -P SCRIPTDIR` invocation in `scripts/server/test_server_templates.sh` — the single place v2 runs shellcheck. |
| `tox.ini` | dropped | Orchestrated poetry-installed black/isort/flake8 envs and the baseline-tolerant mypy wrapper. Every job it defined exists as a pre-commit tier or `uv run pytest`, and no v2 tool reads tox.ini. |
| `mypy-baseline.txt` | dropped | v2 runs mypy strict with a ZERO baseline; a baseline file is the thing the gate exists to forbid. |
| `stubs/celery` | dropped | v2 takes `celery-types` from PyPI (pyproject dev dependencies) instead of hand-maintaining stubs (ADR 0032). |
| `stubs/drf_spectacular` | dropped | v2 has no DRF. |
| `stubs/simple_history` | ported | `stubs/simple_history` |
| `django-integrations-dev.json` | dropped | A live GCP private key (service account `id-django-integrator-dev@django-integrations`), not code — it was never a repo asset to port. Deleting the v1 repository does not revoke it: rotation is recorded as a USER action in `docs/cutover-checklist.md`, and the replacement goes wherever `GCP_CREDENTIALS` points. |
| `ngrok.yml`, `ngrok.yml.example` | ported | v2 has its own `ngrok.yml` (gitignored) and `ngrok.yml.example`. v1's real file carried the live authtoken and the reserved `docketworks-msm-dev.ngrok-free.app` domain binding; both are carried in v2's local `ngrok.yml`, so deleting v1 loses neither. |
| `SECURITY.md` | ported | `SECURITY.md` — the GitHub vulnerability-reporting policy; both repositories are public, so the report-privately channel must survive the v1 deletion. |
| `.claude/skills/stock/SKILL.md`, `.claude/skills/add-stock/SKILL.md` | ported | `.claude/skills/stock/`, `.claude/skills/add-stock/` — operator skills for stock lookup and adding stock to job material lines over `manage.py shell`. Ported verbatim: every model and field they reference (`purchasing.Stock` item_code/description/unit_cost/unit_revenue/is_active, `quoting.SupplierProduct` product_name/parsed_description/parsed_metal_type, `job.Job`) exists unchanged in v2 (verified against the live models). |

## On-disk state (not repo assets)

Directories on the v1 checkout that hold state rather than code. None port —
state is either recreated by v2's own tools or archived:

- `mediafiles/` — development placeholder bytes only.
  `scripts/ops/recreate_jobfiles.py` fabricates placeholders for restored
  `JobFile` rows; real production bytes were never carried between
  environments (the rsync that would carry them is `pull_prod_files.sh`,
  blocked above).
- `restore/` — the landing directory for scrubbed dump archives, recreated by
  the tools that write it.
- `backups/` — local pre/post-restore snapshots of the development database,
  recreated by `scripts/backup_db.sh` and the restore flow.
- `logs/` — runtime logs; empty at audit.
- `.local/session-replays/` — v1's disk store of replay chunk payloads, pulled
  from production for debugging. v2 has no replay ingestion (rrweb is not in
  the frontend) and no storage-root setting; the purge task's docstring in
  `apps/diagnostics/tasks.py` records that rows are the whole v2 store. The
  storage decision is taken when replay capture is ported.
- `frontend/test-history/` — archived; see the E2E harness table above.

## Deferred Xero capability

v1's `xero` command carried fifteen flags; three are ported (`--setup`,
`--seed-xero`, `--configure-payroll`). The twelve deferred flags are blocked by
one of two named features — the payroll employee API port
(`blocked-by:payroll-employees`) or the Xero Projects port
(`blocked-by:xero-projects`) — and are recorded here rather than in the
command, which names only its own supported actions.

| v1 flag | disposition | note |
|---|---|---|
| `--tenant` | blocked-by:payroll-employees | Lists the connected organisations with tenant ids and names — the tenant-selection step of the staff-linking flows below. The ported `--setup` binds to the first connection and prints it. |
| `--no-set` | blocked-by:payroll-employees | Reports the tenant without writing it to company defaults; the read-only mode of the same selector. |
| `--users` | blocked-by:xero-projects | Lists Xero users from the Projects API. |
| `--payroll-employees`, `--payroll-rates`, `--payroll-calendars`, `--payroll-leave-types`, `--payroll-pay-runs` | blocked-by:payroll-employees | Read-only listings of the payroll objects, one flag each, for checking what an organisation actually holds when a payroll operation refuses. Calendars, earnings rates and leave types are already readable from `apps/xero/payroll_setup.py` and `apps/xero/payroll_sync.py` — only the operator-facing print is missing; employees and pay runs need the unported employee API itself. |
| `--link-staff` (+ `-emails`, `-dry-run`) | blocked-by:payroll-employees | Links local staff to existing Xero payroll employees by matching email address, optionally limited to a named list, with a preview mode. |
| `--create-staff` (+ `-emails`, `-dry-run`) | blocked-by:payroll-employees | Creates Xero payroll employees for unlinked staff, required to be given an explicit email list, with a preview mode. |
| `--import-staff` (+ `-dry-run`, `-password`) | blocked-by:payroll-employees | The prospect-instance direction: create local staff from the organisation's payroll employees, with an initial password. Refuses when staff already exist unless forced. |
| `--force` | blocked-by:payroll-employees | Bypasses the safety check on the staff-import path. |
| `--raw-api` | blocked-by:payroll-employees | Fetches payroll employees over plain HTTP instead of the Xero SDK, keeping only id, name and email and skipping employees with no date of birth — a Xero demo organisation's contractor records have none and the SDK's model raises on them. Rebuild only alongside the employee port, and only for non-production use. |
| `seed_xero_from_database --only projects` | blocked-by:xero-projects | Creates a Xero project per job and stores its id; v2's jobs carry no project id. |
| `seed_xero_from_database --only employees` | blocked-by:payroll-employees | Links or creates a payroll employee per active staff member, carrying the local staff identifier in the employee's job title so a re-run re-links reliably. Until it ports, timesheet posting against a seeded organisation fails — the seed says so at the end of every run. Local staff rows keep their production employee link through the clear phase, deliberately, as the marker this phase reads. |
