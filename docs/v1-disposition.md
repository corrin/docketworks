# v1 operational asset disposition

Every operational asset v1 carries — scripts, management commands, fixtures,
runbooks and the E2E harness helpers — with one of three dispositions:

- **Ported.** The v2 path is named. Read that, not v1.
- **Dropped.** The fact that rejects it is stated. A future session that
  rediscovers the asset by name has the reason here and does not need to
  re-derive it.
- **Post-launch.** Described well enough to rebuild without reading v1.

This file assumes the v1 repository no longer exists. A post-launch entry that
only names an asset is a defect in this file: the description is the asset.

The facts here are frozen. v1 is frozen, so nothing in this inventory changes
except when a post-launch entry is built and becomes a ported one.

## The one asset the refresh flow still needs from v1

**`manage.py backport_data_backup` (with `apps/workflow/services/db_scrubber.py`)
is not ported, and the production hosts run v1.** It is the producer half of
[`restore-prod-to-nonprod.md`](restore-prod-to-nonprod.md):
`scripts/ops/pull_prod_backup.sh` invokes it over ssh on the production host, and
without it there is no scrubbed dump to pull. **Port it before v1's production
hosts are decommissioned.**

What it does, for the rebuild: it pipes `pg_dump` of the live database into a
temporary scrub database (the `scrub` connection alias, whose name must end in
`_scrub` or the scrubber refuses to run), anonymises the configured personally
identifying columns with Faker, deletes accounting records not linked to a job,
truncates the excluded tables, drops every database-backed external-system
credential, and re-dumps the scrubbed copy to `<BASE_DIR>/restore/` or a named
`--output` path. Raw production data never lands on disk on either host. The
consumer-side check of its output is already ported as
`scripts/ops/verify_scrubbed_backup.py`, which fails an archive that is
unreadable, predates the July 2026 migration squash, or still carries
credentials — that verifier is the specification the ported producer has to
satisfy.

## scripts/

| v1 asset | disposition | note |
|---|---|---|
| `analyze_company_people.py` | dropped | One-shot survey of duplicate and empty person names feeding a manual merge pass; the repair tool it fed is ported as the `merge_companies` command. |
| `backup_db.sh` | ported | `scripts/backup_db.sh` |
| `backup_instance_files.sh` | ported | `scripts/backup_instance_files.sh` |
| `check_mypy.sh` | dropped | Ran mypy against `mypy-baseline.txt` and failed only on new errors. v2 runs mypy strict with a zero baseline as a pre-commit hook, so there is nothing for a baseline-tolerant wrapper to do. |
| `check_naive_local_dates.py` | post-launch | AST gate forbidding `timezone.now().date()` and its aliases: `timezone.now()` is UTC-aware, so `.date()` gives the UTC calendar date, which is the wrong day for any "what day is it here" question. The fix it enforces is `django.utils.timezone.localdate()`. v2's code uses `localdate()` throughout and ruff's DTZ rules do not cover this Django-specific shape, so the gate is unwritten rather than unnecessary. |
| `check_requirements.sh`, `generate_requirements.sh` | dropped | Exported and verified `requirements.txt` against `poetry.lock` for an external analysis tool. v2 uses uv and `uv.lock`; deptry gates dependency hygiene. |
| `cleanup_backups.py`, `cleanup_backups.sh` | ported | `scripts/cleanup_backups.py`, `scripts/cleanup_backups.sh` |
| `copy_material_lines.py` | dropped | One-shot move of material cost lines between two named jobs, run through `manage.py shell`. |
| `create_master_template.py` | post-launch | Part of the Google Docs/Drive authoring toolchain below. |
| `debug_xero_fetch.py` | dropped | Live probe that the rate-limited Xero REST client honours a 429. v2 pins that behaviour in unit tests (`apps/xero/tests/test_sync_quota_gates.py`), which run on every push instead of on an operator's memory. |
| `detect_fstrings_without_placeholder.py` | ported | Ruff `F541` (the `F` rule set is selected in `pyproject.toml`). |
| `dump_settings.py` | post-launch | Prints a sanitised JSON snapshot of the running configuration — versions, database, cache, channels, security headers and selected environment variables — for diagnosing an instance whose behaviour does not match its expected settings. |
| `explore_google_drive.py`, `read_google_doc.py`, `write_google_doc.py`, `set_doc_screenshot.py`, `get_gapi_token.py`, `google_doc_manifest.json`, `create_master_template.py` | post-launch | The Google Docs/Drive authoring toolchain: list the Shared Drives and folder trees visible to the delegated service account, read a document as Markdown, write Markdown back as a document (headings, bold, lists, tables and `{{screenshot:<id>}}` markers survive) with a revision-id safety net held in the manifest, replace a screenshot marker with an uploaded image, and mint an access token from `GCP_CREDENTIALS` for manual API calls. They author the Google-Doc-backed `Procedure` records the process app links to. |
| `find_duplicates.py` | ported | `scripts/checks/find_duplicates.py`, wired as a pre-commit hook. |
| `find_late_imports.py` | ported | Ruff `PLC0415` (import outside top level), which v2 suppresses individually where a cycle makes a late import correct. |
| `find_wrapper_candidates.py` | dropped | Found short functions with few callers to drive a wrapper-deletion campaign against v1's accumulated indirection. v2's standing equivalents are the find-duplicates hook and the generated `docs/code-quality.md` metrics. |
| `fix_test_company.py` | ported | `scripts/ops/fix_test_company.py` |
| `fix_welding_stock_cost.py` | dropped | One-shot repair of a single stock item's unit cost, already applied to production data. |
| `generate_url_docs.py` | dropped | Generated per-app Markdown URL listings. v2's route inventory is the exported OpenAPI schema, regenerated and gated by `scripts/checks/export_openapi.py`. |
| `geocode_addresses.py` | post-launch | Backfill sweep: find pickup addresses with no latitude/longitude and geocode them through the Google Address Validation API, with a dry-run mode. v2 geocodes on write in `apps/company/services/geocoding_service.py`; only the sweep over existing rows is unported. |
| `migrate_to_snapshot.py` | post-launch | Applies migrations up to the state recorded in the `migrations.json` snapshot that `backport_data_backup` ships inside a backup archive, so a dump can be migrated to exactly the graph it came from rather than to the current tip. |
| `move_time_between_jobs.py` | post-launch | Operator correction: move every actual timesheet time entry from one job number to another, dry-run by default. The recurring need is a job booked against the wrong number. |
| `payroll_reconciliation.py` | ported | Its draft functions became `apps/accounting/services/payroll_reconciliation_service.py`. |
| `poc_phone_provider_scraper.py` | post-launch | Diagnostic that lists the phone provider's call-detail rows and downloads recording samples, for investigating ingestion gaps. Deliberately not a Beat harness: provider-side deletion must be exercised through the real Celery Beat task, never through this script. |
| `populate_product_mappings.py` | ported | Batch parsing of supplier products into product-parsing mappings is the scraper's end-of-run fill in `apps/quoting`. |
| `production_data_fixer.py` | dropped | A menu of idempotent repairs for known v1 data defects. The defects it addressed were repaired in production by v1's data-repair release, and `scripts/ops/validate_restored_data.py` is v2's standing check that a load holds no row the models reject. |
| `pull_prod_backup.sh` | ported | `scripts/ops/pull_prod_backup.sh` |
| `pull_prod_files.sh` | post-launch | Rsyncs a production instance's mutable file directories (`mediafiles/`, `phone-recordings/`, `session-replays/`) into the local storage roots over sudo-rsync — the file-side companion to the database pull. Blocked on v2 having no session-replay storage setting, and not needed by the E2E suite (the job-attachments spec uploads its own fixture). `scripts/ops/recreate_jobfiles.py` covers the gap it would otherwise fill: job-file rows restored without their bytes. |
| `predeploy_backup.sh` | ported | `scripts/predeploy_backup.sh` |
| `push_companies_to_xero.py` | ported | Superseded by the contacts phase of `apps/xero/seeding.py`, driven by `manage.py seed_xero_from_database`. |
| `recreate_jobfiles.py` | ported | `scripts/ops/recreate_jobfiles.py` |
| `regen_golden_pdfs.py` | ported | `scripts/generate/regen_golden_pdfs.py` |
| `regen_openapi_schema.sh`, `update_schema.sh` | ported | `scripts/checks/export_openapi.py` (regenerates on drift, gated on push) plus `npm run gen:api` for the client. |
| `rollback.sh` | ported | `scripts/rollback.sh` |
| `setup_database.sh` | dropped | Created or reset the PostgreSQL database and role as the postgres user. Dev database creation is documented directly in [`initial_install.md`](initial_install.md); instance databases and roles are created by `scripts/server/instance.sh`. |
| `setup_demo_payroll.py` | post-launch | Sets payroll details (tax code, KiwiSaver, bank account, pay template) on employees that already exist in the demo Xero organisation, so posted timesheets are accepted. Blocked behind the same unported payroll employee API as the seed's employees phase. |
| `setup_dev_logins.py` | ported | `scripts/ops/setup_dev_logins.py` |
| `test_chat_conversation.py`, `test_full_quote_conversation.py` | post-launch | Command-line harnesses for the quoting chat: drive a conversation without the frontend, optionally attaching a file, and exercise a realistic multi-turn flow across calculation and clarification modes. Useful because the chat's failures are conversational rather than structural. |
| `test_kpi_service.py` | dropped | Command-line harness for the KPI calendar service. v2's `apps/accounting/services/kpi_service.py` has unit tests. |
| `test_login_logging.py` | dropped | Drove real login attempts with Selenium to prove failures reach `auth.log` with client IPs. v2 has no Selenium dependency, and the log shapes that matter are pinned by the fail2ban filter tests in `scripts/server/test_server_templates.sh`. |
| `test_quote_import.py` | post-launch | Runs the spreadsheet quote import against a real `.xlsx`, against a given job or in preview mode. Quote import is unported, so this is a harness for a feature that must arrive first. |
| `test_xero_payroll.py` | post-launch | Diagnostic for Xero Payroll NZ 403s: walks the payroll endpoints one at a time to show which scope or subscription is missing, rather than leaving one opaque refusal. |
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
| `verify_xero_batch_order.py` | post-launch | Small live probe: submit a batch of distinctively named contacts to Xero's create-contacts endpoint and assert the response comes back in submission order, because the seeding path maps responses to local rows by position. v2's runtime defence is the name-mismatch tripwire in `apps/xero/seeding.py`, which aborts the run rather than mislinking; the runbook substitutes a small first live batch for the probe. |
| `verify_xero_client_quote_contract.py` | post-launch | End-to-end contract check that the public app API and Xero agree on company and quote contact data: writes through the configured public app URL, reads back with the Xero SDK, and creates real records in both. An operator-run check for incident investigation, never part of the test suite. |
| `README.md` | dropped | Its content — these scripts mutate real external systems and are not part of the default suite — is stated in the entries above. |

## scripts/server/

The server provisioning suite ported wholesale into `scripts/server/`:
`common.sh`, `server-setup.sh`, `instance.sh`, `deploy.sh`, `dw-run.sh`,
`release-utils.sh`, the `certbot-dreamhost-auth.sh` and
`certbot-dreamhost-cleanup.sh` DNS-01 hooks, `test_server_templates.sh` and
every instance template. v2 adds `verify-instance.sh`, the `cutover/` scripts,
the fail2ban filters and jail, the nginx rate-limit configuration, and the
company-defaults templates that replace v1's fixture files.

| v1 asset | disposition | note |
|---|---|---|
| `migrate-test-role.sh` | dropped | One-off migration for instances created before per-tenant pytest roles existed: it gave one tenant its own `dw_<instance>_test` role and database in place of the shared cluster-wide `dw_test` role. v2 instances are created with per-tenant test roles from the start, so there is no pre-change instance to migrate. |

## Management commands

| v1 asset | disposition | note |
|---|---|---|
| `workflow/backport_data_backup.py` | post-launch, blocking | See the flagged section at the top of this file. |
| `workflow/xero.py` | ported | `apps/xero/management/commands/xero.py`, carrying `--setup`, `--seed-xero` and `--configure-payroll`. The other flags are listed under "Deferred Xero capability" below. |
| `workflow/seed_xero_from_database.py` | ported | `apps/xero/management/commands/seed_xero_from_database.py`, with the accounts, contacts, invoices, quotes and stock phases. |
| `workflow/start_xero_sync.py` | ported | `apps/xero/management/commands/start_xero_sync.py`, which additionally holds the shared sync lock so an inline run cannot interleave with a beat-dispatched one. |
| `workflow/e2e_cleanup.py` | ported | `apps/diagnostics/management/commands/e2e_cleanup.py` |
| `workflow/inspect_xero_quote_pdf.py` | ported | `apps/accounting/management/commands/inspect_xero_quote_pdf.py` |
| `workflow/rollback_migrations.py` | ported | `apps/core/management/commands/rollback_migrations.py` |
| `workflow/sync_sequences.py` | ported | `apps/core/management/commands/sync_sequences.py` |
| `company/merge_companies.py` | ported | `apps/company/management/commands/merge_companies.py` |
| `quoting/run_scrapers.py` | ported | `apps/quoting/management/commands/run_scrapers.py` |
| `workflow/create_service_api_key.py` | post-launch | Mints a named `ServiceApiKey` row for service-level authentication (the chatbot's MCP access), printing the key once. v2 has the model in `apps/core/models.py`; only the minting command is unported. |
| `workflow/finalize_instance_onboarding.py` | post-launch | The post-OAuth onboarding sequence for a FRESH instance: import or create staff from the connected Xero organisation, sync pay items, then enable sync. Deliberately not used by a restore, which re-points an existing dataset instead — the restore path is `xero --setup`, `--configure-payroll` and `seed_xero_from_database`. |
| `workflow/export_dev_demo_dump.py` | post-launch | Produces a lightly scrubbed `pg_dump` of a development database for a trusted external data-warehouse demonstration, defaulting to `<BASE_DIR>/restore/dev_demo_<db>_<timestamp>.dump`. Its scrubber is separate from and lighter than the production one: the audience is trusted, so it removes credentials and direct identifiers rather than anonymising everything. |
| `workflow/backfill_kanban_search_telemetry.py` | dropped | Backfilled legacy `kanban_search.log` lines into search telemetry rows. v2 writes telemetry from the search path itself and no v2 instance has that log. |
| `accounts/flag_weak_passwords.py` | post-launch | Marks every user as requiring a password reset at next login. The need is a credential incident or a policy change, not a routine one. |
| `job/create_shop_jobs.py` | post-launch | Creates the internal shop jobs — the overhead jobs time is booked against when it is not billable to a customer — each with a fixed name and description: business development, bench work, worker admin, office admin, and one job per leave type (annual, sick, bereavement). The E2E timesheet specs depend on the annual leave job being findable by name, so a restored dataset carries them and only a fresh instance needs this. |
| `job/set_paid_flag_jobs.py` | post-launch | Sweep that sets the paid flag on completed jobs whose invoices are paid, with dry-run and verbose modes. Reconciliation for jobs whose invoices were settled outside the normal path. |
| `job/test_gemini_chat.py` | post-launch | Command-line harness for the AI quoting chat against the configured model. |
| `process/import_dropbox_hs_documents.py` | post-launch | Walks a Dropbox health-and-safety folder tree, finds `.doc`/`.docx` files following the `Doc.NNN` naming convention, and creates procedure or form records with the type, tags and metadata implied by their location. A one-per-client import, not a sync. |
| `timesheet/create_leave_entries.py` | post-launch | Backfills leave entries to match what Xero payroll shows, for staff who took leave without logging it. Xero is the system of record for payroll; this exists so management reporting matches it. |
| `timesheet/create_overtime_entries.py` | post-launch | Creates overtime and then ordinary-time entries to close the gap between local hours and Xero payroll hours for a staff week, overtime first up to the overtime headroom. |
| `timesheet/reclassify_overtime_entries.py` | post-launch | The companion case: the week's totals already agree but too few hours are classified as overtime, so existing standard-rate lines on shop or special jobs are reclassified rather than new entries created. |
| `timesheet/create_special_job.py` | post-launch | Creates a special (overhead) job mirroring the structure of the existing ones, with a dry-run mode. |
| `timesheet/reassign_time_entries.py` | post-launch | Moves time entries from one staff member to another, updating the unit cost to the new person's wage rate and the description. The recurring need is time logged under the wrong person. |

## Fixtures

| v1 asset | disposition | note |
|---|---|---|
| `apps/workflow/fixtures/ai_providers.json` (+ `.example`) | ported | `scripts/server/templates/ai-providers.json.template`, rendered per instance by `instance.sh` into the instance's private fixture directory. |
| `apps/workflow/fixtures/xero_apps.json` (+ `.example`) | ported | `scripts/server/templates/xero-apps.json.template`, same mechanism. |
| `apps/workflow/fixtures/company_defaults.json` | ported | `scripts/server/templates/company-defaults.json.template` |
| `apps/workflow/fixtures/company_defaults_prospect.json` | ported | `scripts/server/templates/company-defaults-prospect.json.template` |
| `apps/workflow/fixtures/initial_data.json` | post-launch | The demo staff fixture: dummy staff rows plus the phone endpoints they answer, loaded by v1's `instance.sh` when an instance was created seeded. v2's `--seed` selects the seeded company-defaults template and stops there, so a v2 demo instance comes up with no staff beyond the first login. |

## docs/

| v1 asset | disposition | note |
|---|---|---|
| `README.md` | ported | `docs/README.md` |
| `restore-prod-to-nonprod.md` | ported | [`restore-prod-to-nonprod.md`](restore-prod-to-nonprod.md), rewritten around v2's load path. |
| `development_session.md` | ported | `docs/development_session.md` |
| `initial_install.md` | ported | `docs/initial_install.md` |
| `ngrok_setup.md` | ported | `docs/ngrok_setup.md` |
| `server_setup.md` | ported | `docs/server_setup.md` |
| `adr/` | ported | `docs/adr/`, numbering continuous with v1 — the v1 records themselves live on in v2. |
| `architecture.md` | dropped | A narrative description of the system's layers and flows. v2 states its architecture in `CLAUDE.md`'s layout and standards sections and in the ADRs, both of which are read before non-trivial work; a second narrative would drift from them without anything noticing. |
| `updating.md` | dropped | v1's deploy runbook plus a caveat about pre-squash dumps. Deploy is `server_setup.md`'s Part D and `scripts/server/README.md`. The caveat does not transfer: a dump predating v1's July 2026 migration squash needs a pre-squash v1 checkout to migrate, `scripts/ops/verify_scrubbed_backup.py` refuses such an archive outright, and v2's load path takes data only and never v1's migration ledger. |
| `client_onboarding.md` | post-launch | The onboarding specialist's handoff, from signed contract to running instance, in seven ordered phases: collect from the client (company details, pricing and rates, staff list, standard operating procedures, quote template, supplier integrations); Xero (the client configures the organisation, you create the developer app); Google Cloud (service account, Workspace delegation or direct Drive folder access, shared drive for documents, Maps API key); AI providers and where their keys come from; email; create the instance with `instance.sh`; and the in-app configuration that follows, starting with the Xero connection. |
| `instance-setup-demo.md` | post-launch | The demo variant of instance creation: an instance seeded with dummy staff and connected to a Xero Demo Company rather than a real organisation. The provisioning half is `server_setup.md` Part C; what is unwritten is the demo-specific sequence, including the demo staff fixture above and the fact that a Xero demo organisation is recreated roughly monthly with a new tenant id. |
| `instance-setup-production.md` | post-launch | The production variant: one client, their real Xero organisation, and the prerequisite that the payroll calendar, pay items and invoice branding theme already exist there before the instance is created — `xero --setup` validates rather than creates them against a production organisation. |
| `xero_setup.md` | post-launch | Configuring the Xero side before an instance connects: the earnings rates, leave types and payroll calendar the organisation must hold under Payroll Settings, named as the application expects to find them, and then registering the Xero developer app and its OAuth callback so the tokens `workflow_xeroapp` holds can be issued. |
| `restore-prod-to-hotfix.md` | post-launch | The hotfix checkout's refresh: a second working copy whose database is restored from production and which is served on its own ngrok domain, used to reproduce and verify a production fix without disturbing the main development environment. Same load sequence as the non-production runbook, differing only in which checkout, domain and database it targets. |
| `jira-usage.md`, `jira.md` | dropped | The Jira project, board states, labels and definition of done. v2's work is tracked in the approved plan, `rewrite-status.md` and the cutover checklist. |
| `urls/` | dropped | Generated per-app URL listings, the output of `generate_url_docs.py`. The exported OpenAPI schema is v2's route inventory. |
| `function_character_counts.tsv`, `function_under_80_review.tsv` | dropped | Snapshots of a one-off function-length review. v2's `docs/code-quality.md` is generated, committed and gated, so its numbers move in the diff that moves them. |
| `.codesight/KNOWLEDGE.md` | dropped | A knowledge map generated by an external analysis tool over v1's history: decisions, notes and open questions extracted from commits and sessions. Its durable content is the ADRs, which v2 carries forward with continuous numbering. |
| `plans/`, `superpowers/`, `test_plans/`, `test_pdfs/` | dropped | Session planning documents, agent skill and spec directories, a single feature test plan, and price-list PDFs used as parser fixtures. v2 keeps its own `docs/plans/` and `docs/superpowers/`, and its parser fixtures live with the tests that read them. |

## Frontend E2E harness

| v1 asset | disposition | note |
|---|---|---|
| `global-setup.ts`, `global-teardown.ts`, `e2e-reset.ts`, `e2e-sync-windows.ts`, `db-backup-utils.ts` | ported | `frontend/tests/scripts/`, including the database restore and the preservation and re-injection of the Xero token material across it. |
| `xero-login.ts` | post-launch | Playwright automation of the Xero OAuth consent: signs in with the default admin credentials, starts the authorisation flow and completes Xero's consent screens, leaving the instance connected. The manual equivalent is the consent step in the restore runbook, which must be started on the instance's ngrok domain because that is where the registered callback points. |
| `analyze-e2e-rolling.ts`, `analyze-e2e-trends.ts`, `analyze-network.ts`, `analyze-timing.ts`, `extract-trace-timing.ts`, `history-reporter.ts`, `backfill-e2e-git-metadata.ts` | post-launch | The E2E history and analysis family: record each run's results with its git metadata, then report rolling pass rates, per-spec trends, per-test timing extracted from Playwright traces, and network waterfalls, so a flaky or slowing spec is visible as a trend rather than as one bad afternoon. v2 records run results through `process-result.ts` but has none of the reporting over them. |
| `backup-db.sh`, `restore-db.sh` | ported | Their behaviour lives in `frontend/tests/scripts/db-backup-utils.ts`. |

## Deferred Xero capability

v1's `xero` command carried fifteen flags; three are ported. The rest are
recorded here rather than in the command, which names only its own supported
actions.

| v1 flag | disposition | note |
|---|---|---|
| `--tenant` | post-launch | Lists the connected organisations with their tenant ids and names. The ported `--setup` binds to the first connection and prints it, so this is an inspector rather than a capability. |
| `--users` | post-launch | Lists Xero users from the Projects API. Xero Projects is unported. |
| `--payroll-employees`, `--payroll-rates`, `--payroll-calendars`, `--payroll-leave-types`, `--payroll-pay-runs` | post-launch | Read-only listings of the payroll objects, one flag each, for checking what a Xero organisation actually holds when a payroll operation refuses. Calendars, earnings rates and leave types are already readable from `apps/xero/payroll_setup.py` and `apps/xero/payroll_sync.py`; only the operator-facing print is missing. Employees and pay runs need the unported payroll employee API. |
| `--link-staff`, `--link-staff-emails`, `--link-staff-dry-run` | post-launch | Links local staff to existing Xero payroll employees by matching email address, optionally limited to a named list, with a preview mode. |
| `--create-staff`, `--create-staff-emails`, `--create-staff-dry-run` | post-launch | Creates Xero payroll employees for unlinked staff, required to be given an explicit email list, with a preview mode. |
| `--import-staff`, `--import-staff-dry-run`, `--import-staff-password` | post-launch | The prospect-instance direction: create local staff from the organisation's payroll employees, with an initial password. Refuses when staff already exist unless forced. |
| `--no-set` | post-launch | Reports the tenant without writing it to company defaults. |
| `--force` | post-launch | Bypasses the safety check on the staff-import path. |
| `--raw-api` | post-launch | Fetches payroll employees over plain HTTP instead of through the Xero SDK, keeping only employee id, name and email, and skipping employees with no date of birth. It exists because a Xero demo organisation's contractor records have no date of birth and the SDK's model raises on them; without it, listing employees against a demo organisation fails outright. Rebuild it only alongside the payroll employee port, and only for non-production use. |
| `seed_xero_from_database --only projects` | post-launch | Creates a Xero project per job and stores its id. Xero Projects is unported; v2's jobs carry no project id. |
| `seed_xero_from_database --only employees` | post-launch | Links or creates a payroll employee per active staff member, carrying the local staff identifier in the employee's job title so a re-run can re-link reliably. Until it ports, timesheet posting against a seeded organisation fails — the seed says so at the end of every run. Local staff rows keep their production employee link through the clear phase, deliberately, as the marker this phase reads. |
