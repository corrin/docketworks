# Cutover record

**The cutover ran the night of Saturday 29 August 2026** (moved from 15 August by the
2026-08-14 ruling, then from 22 August by the 2026-08-29 ruling). Production has run v2
since; the first production release is `prod-2026-08-30-bf82955f`, and
[`release-process.md`](release-process.md) is the steady-state procedure that replaced
this file.

**This is a record, not a to-do list.** It documents the procedure that was followed and
the facts that shaped it — the carry-over surface, the migration mechanics and the
environment contract — because every one of them applies again the next time an instance
is created or restored. Nothing here is work waiting to be done: what the cutover left
open moved to [`rewrite-status.md`](rewrite-status.md), which is the only place work
lives. The bullets below are therefore statements, not checkboxes; nobody ticked them on
the night and pretending otherwise would make this file lie in a new way.

## Carry-over inventory — the complete surface

Every category of v1 state and how it reaches v2. Verified 2026-08-30, so
this is the whole surface, not a running discovery log: if something a
cutover needs is not below, it is a genuine gap, not an oversight to patch
in silence.

| v1 state | Mechanism | Kind |
|---|---|---|
| All table data | `migrate_v1_data.sh` (data-only dump/restore into a freshly-migrated v2 DB; excludes infra tables; rewinds seed rows so pre-rename columns land; deletes UNIQUE-colliding seeds; replays data-normalising migrations; resets and verifies sequences) | automated |
| The 5 Fernet columns (phone username/password; supplier username/password/api_key) | Phase 0 `scripts/ops/extract_v1_credentials.py --output` (decrypts with v1's own key while v1 is up) → post-swap `scripts/ops/apply_v1_credentials.py` (called by `cutover-instance.sh` when the file exists). Fallback with no file: the migration NULLs them, the operator supplies `PHONE_PROVIDER_*` in the credentials file and re-enters suppliers via `manage.py set_supplier_credential` | automated (extracted) / manual (fallback) |
| `<instance>.company-defaults.json` (bootstrap; real `xero_tenant_id`) | Phase 0 `extract_v1_credentials.py --company-defaults` dumps v1's live singleton + shop company. On a cutover it is validated, not loaded — the real CompanyDefaults arrives with the table migration | automated |
| Xero OAuth tokens | Straight table migration — v1 stores them plaintext, the fixture loader preserves the migrated row. Reconnect at `/admin/xero` ONLY if absent or past Xero's refresh window (a scrubbed dump strips them; a real dump does not) | automated |
| Google Maps API key | `GOOGLE_MAPS_API_KEY` in the credentials file → `load_integration_settings` (ADR 0053; v1 held it in the environment, v2 in a DB row). This is the SOLE env→DB-row case — every other secret maps to a migrating table row | manual entry + automated load |
| On-disk bytes: `mediafiles/`, `phone-recordings/`, `gcp-credentials.json` | **In-place cutover: nothing to do — they persist.** v1 and v2 use the identical instance layout (`/opt/docketworks/instances/<instance>/…`) and the cutover reuses that directory. The phone-recording/media COPY steps below apply only to a fresh-host restore (a different machine loading a dump), never to the in-place flip — do not copy redundantly or raise a false alarm | in-place: none; fresh host: manual copy |
| Staff wage rates; supplier-cred currency; GCP key rotation; `JWT_SIGNING_KEY`; rclone team-drive | Operator actions with a mechanism; each has its own checklist item below | manual |

## The release gate, and how it was answered

Go/no-go was two independent questions, either failing being grounds to reject:

- **Does this replicate all the functionality the business needs?** Every MUST-tier E2E
  spec passing was the measurable proxy. All were green on `main` before the window.
- **Is this materially better architecture and code — enough to justify the move?**
  Judged directly rather than proxied by any gate, on the reasoning that v1 already
  proved the functionality worked, so the architecture was the rewrite's only reason to
  exist.

Both were answered yes and the flip proceeded. The fallback was abort-and-stay-on-v1 —
`rollback-instance.sh` plus the preserved v1-final database — and it was not used. The
tiering the gate referred to (MUST / SHOULD / DEFERRED) existed only to partition work
around this moment and no longer exists.

## Data prerequisites, and what they cost

These ran before the window. Each is a fact about migrating a live instance, so each
applies again on the next restore.

- **Staff wage rates.** v2 refuses to price time for a staff member whose
  `base_wage_rate` is unset (ADR 0015; user decision 2026-08-03 — v1
  silently substituted the company default or costed $0.00). A check of
  the 2026-08-01 production restore found **6 of 24 staff rows with no
  rate, all current**, two of which are non-human (`System Automation`,
  `Default Admin`) and never book time. Set rates for every staff member
  who books time, or they get a 400 naming them on their first entry.
  Query: `select id, first_name, last_name from accounts_staff
  where (base_wage_rate = 0 or base_wage_rate is null) and date_left is null;`
- **Archive v1 and take the permanent repository identity.** Done 2026-08-29
  (`83d604b`). The plan was to delete the v1 repository outright; what happened is
  that `corrin/docketworks_v1` was archived **private**, which ends the public
  exposure of the confidential leave batch v1 committed (the named staff rows its
  `create_leave_entries.py` carried — the ADR 0049 counterexample) while keeping the
  history the post-cutover ports still read. `corrin/docketworks` is now this
  history. The `blocked-by:<feature>` rows in `v1-disposition.md` are the reason the
  archive was kept rather than deleted: their v1 source lives only there.
- **Formerly-encrypted credentials — extract them in phase 0.** The five
  columns that were Fernet ciphertext in v1 (the phone provider's
  username/password, now `IntegrationSettings.phone_provider_*`, and
  quoting `SupplierCredential.username/password/api_key`) are plain text in
  v2. On a REAL cutover, decrypt them while v1 is still up — only v1's own
  `.env` holds the key:
  `python scripts/ops/extract_v1_credentials.py --env-file
  /opt/docketworks/instances/msm-prod/.env --output
  <state-dir>/v1-credentials.json`, where `<state-dir>` is the
  `/opt/docketworks/cutover-state/msm-prod-<ts>` directory
  `cutover-instance.sh` will create — or place the file there once it
  exists; `cutover-instance.sh` applies it on the live database after the
  swap and before the fixture load, so the phone group arrives configured
  and the fixture loader honours it. Without the file (a scrubbed restore,
  or no key), the migration's clearing stands: then `msm-prod.credentials.env`
  MUST carry `PHONE_PROVIDER_ENABLED=true` plus the full `PHONE_PROVIDER_*`
  group before the window (`instance.sh` refuses enabled-without-values,
  and a disabled group passes the verifier by design so a live integration
  would silently stay off), and supplier credentials are re-entered with
  `dw-run.sh <instance> python manage.py set_supplier_credential
  "<supplier>" "<label>"` (prompted, never argv) before a scraper runs.
  There is no in-database decrypt helper — the extract runs against v1.
- **Per-instance company-defaults file — generate it in phase 0.**
  `cutover-instance.sh` validates `<instance>.company-defaults.json` (a
  v1-format fixture carrying the real `xero_tenant_id`); on a cutover it is
  validated, not loaded — the live CompanyDefaults arrives with the data
  migration. There is no hand-curation: the same extract script builds it
  from v1's live singleton and shop company,
  `python scripts/ops/extract_v1_credentials.py --env-file
  /opt/docketworks/instances/msm-prod/.env --company-defaults
  /opt/docketworks/config/msm-prod.company-defaults.json` (then
  `chown root:root` + `chmod 600`). Re-run `instance.sh validate-config`
  until green.

## Migration mechanics, and the traps they encode

Rehearsed 2026-08-05 and run for real on the night. Every trap below was found the hard
way and is still live for any future restore.

- `scripts/ops/db_schema_diff.sh` green against the production restore.
- **Copy v1's recording archive into the instance BEFORE the data load.**
  Every `PhoneCallRecording` row points at a file under
  `PHONE_RECORDING_STORAGE_ROOT` by a path relative to that root
  (`YYYY/MM/DD/<provider id>.mp3`); v1's root is its own
  `PHONE_RECORDING_STORAGE_ROOT` on the v1 host, v2's is
  `/opt/docketworks/instances/<instance>/phone-recordings`
  (`env-instance.template`). Nothing else carries the files across: the
  dump is rows only, and a row whose file is absent 404s on play. The copy
  has to land before `migrate_v1_data.sh`, whose re-run of `crm/0003`
  measures each recording's length from the file and leaves the length
  NULL (no length in the player) for any file that is not there.
- `scripts/ops/migrate_v1_data.sh` load + row-count parity. Rehearsed
  2026-08-05 in the documented order (migrate into an empty database,
  THEN restore) from a production restore carrying v1's repair
  migrations: 77 tables compared, every business table exact. The only
  differences were the five tables the dump deliberately excludes
  (`auth_permission`, `django_content_type`, `django_migrations`,
  `django_session`, celery results — v2 regenerates or owns these) and
  the four `django_celery_beat_*` tables v2 dropped when beat schedules
  moved into code.
- **Sequences verified, not assumed.** The script now resets identity
  sequences via `pg_get_serial_sequence()` and FAILS if any is left behind
  its table. The original reset silently matched zero of twenty sequences
  (it used the serial-only `pg_depend.deptype = 'a'` idiom, while Django 6
  emits IDENTITY columns), so every insert after a load died with a
  duplicate key. Row-count checks cannot see this — only writing can.
- **Rehearse in the DOCUMENTED order — `migrate` first, THEN restore.**
  The seeds `manage.py migrate` writes for a fresh install (the system
  automation Staff row, the labour-subtype catalogue) are the same rows
  v1's dump carries, under different primary keys and on UNIQUE columns
  (`accounts_staff.email`, `job_laboursubtype.name`). The restore runs in
  a single transaction, so ONE collision rolls back the entire load.
  `migrate_v1_data.sh` now clears those rows immediately before restoring;
  `config/tests/test_data_migration_script.py` proves the collision and
  the fix against a real database, and fails if a new data-writing
  migration ships unclassified. Every rehearsal to date ran on a database
  whose seed migrations happened to be unapplied, which is why this never
  surfaced — same shape as the sequence bug above: silent until the night
  it isn't.
- **`uv run python -m scripts.ops.validate_restored_data`** — exits non-zero
  if the load contains a row v2 will refuse to save. Three sweeps:
  dangling foreign keys (the load defers foreign-key checks to the commit
  of its single transaction, and foreign keys Django declares
  `db_constraint=False` are never enforced by the database at all, so the
  sweep re-proves every reference in bulk), foreign keys the models declare
  required but the column left NULL, and `full_clean()` over every row.
  CHECK/NOT NULL/UNIQUE are deliberately not re-checked — Postgres
  enforced those during the restore, so a completed load is already
  proof. Expect ZERO once v1's `data-repair-for-v2-validation` migrations
  have been deployed and a fresh dump taken; before that it reports the
  31 rows those migrations fix.
- **Run the app against the loaded data**: `scripts/ops/smoke_api.sh` must
  report no 5xx. This is what caught both the sequence bug and the
  `input_data` shape bug below; synthetic test fixtures produce only
  well-formed data.
- Full test suite and `./scripts/ops/run_e2e.sh` green against the loaded data; confirm the
  command reports a successful database restore and leaves no managed services running.

## The environment contract

What an instance must be true of before it serves. `verify-instance.sh` now gates most of
it; the reasoning is here.

- Generate and provision a dedicated `JWT_SIGNING_KEY`, distinct from
  Django's `SECRET_KEY`, in every v2 environment. Do not copy the v1 key or
  configure a fallback: the architecture cutover deliberately requires one
  fresh login, then this key remains stable across ordinary releases.
- Confirm the internet edge's nginx/fail2ban policy covers both
  `POST /api/accounts/token/` and `POST /api/accounts/token/refresh/`.
  Expected app-level auth refusals intentionally do not write `AppError`
  rows or implement a second rate limiter.
- `CACHES["shared"]` Redis reachable (PDF-refresh dedup, django-solo
  propagation) — v2 fails at commit time on `Job.save()` without it.
- **The instance's rclone remote actually uploads, as the instance user.**
  Prod's per-instance config carried a bare service account (zero My-Drive
  quota, 403 every night since at least July 2026) while the real off-site
  sync rode a root cron with a personal OAuth token. v2 installs only the
  systemd backup units, so at cutover the per-instance `[gdrive]` remote
  must be a service account on a shared/team drive, proven by one green
  manual run of `backup-db-<instance>.service`; retire the root cron pair
  only after that run. A personal token is never the load-bearing path.
- Required env vars present per `.env.example` (settings validate
  fail-fast at boot, so a missing one stops the service immediately).
- **Install-level credentials are database rows, not env** (ADR 0053).
  `GOOGLE_MAPS_API_KEY` is required in the per-instance credentials file
  because v1 held it only in its runtime environment. After the data
  migration, `instance.sh` loads the Maps and complete phone groups from
  that file. `verify-instance.sh` then runs the live Address Validation and
  enabled-phone probes; each run makes a real, billable Maps request.
  `shared.env` is gone and no process environment carries the key.
- **Prove Xero token continuity; do not assume re-consent.** A real v1 dump
  carries the plaintext `workflow_xeroapp` token row and the fixture loader
  preserves it, so Admin > Xero should remain connected after cutover.
  Reconnect there only when the token is absent or past Xero's refresh
  window. A scrubbed non-production dump deliberately removes the row and
  therefore does require OAuth before its Xero checks.
- **The hosts run the ASGI serving model.**
  `scripts/server/templates/gunicorn-instance.service.template` renders
  `gunicorn -k uvicorn_worker.UvicornWorker --workers 4 --timeout 180
  config.asgi:application` on the instance's unix socket (gated by
  `scripts/server/test_server_templates.sh`; the contract is ADR 0047).
  A sync-worker template pins one worker per open kanban tab, and the
  arbiter watchdog SIGKILLs a sync worker mid-stream, which is why this
  item blocks the release. It checks off when that template is what the
  live hosts run.
- **Re-render and install the updated unit and nginx templates on every
  host.** Both changed in the live-updates slice (the nginx config gained
  an exact-match `/api/data-versions/stream/` location carrying
  `proxy_http_version 1.1`, an empty `Connection` header, unbuffered
  proxying and hour-long timeouts, which `/api/` deliberately does not
  inherit), and editing a template changes the server-setup hash
  `scripts/server/deploy.sh` compares, so the next deploy re-converges
  every host. Expect that convergence rather than treating it as drift.
- **Boot verification over the socket, not the port**: `curl
  --unix-socket /opt/docketworks/instances/<instance>/gunicorn.sock` a
  cheap endpoint on each host after the deploy, which proves an HTTP
  responder is on the socket independently of nginx — and nothing more, so
  pair it with `systemctl is-active gunicorn-<instance>` and `systemctl
  show -p ExecStart gunicorn-<instance>`, checking that the loaded unit's
  command carries `-k uvicorn_worker.UvicornWorker` and
  `config.asgi:application`. A host still running the previous unit answers
  that curl exactly as happily, and the serving model is the thing being
  verified.
- **Two-browser live-update smoke.** Sign in to the kanban board in two
  browsers, move a card in one, and confirm it appears in the other
  without a reload — that exercises the whole push path (signal, commit
  hook, Redis fan-out, stream, client reconcile) in one action, and it is
  the only check that fails visibly when the Redis pub/sub listener is
  dead while streams stay connected.
- **Rollback still addresses the right unit.** Confirm the rollback and
  sudoers scripts name `gunicorn-<instance>`, which the serving-model
  change deliberately left untouched; a renamed unit breaks rollback
  silently rather than loudly.
- **Run [`restore-prod-to-nonprod.md`](restore-prod-to-nonprod.md) against
  the dev database before the go/no-go full-suite pass** — a recreated Xero
  demo organisation leaves the mirror tables holding a dead org's entity
  ids, and the sync then creates duplicate companies that break the
  company-lookup specs. See "Environment facts worth knowing" in
  [`development_session.md`](development_session.md) for the diagnosis and repair.

## Quoting slice — decisions taken while porting

- ~~**Supplier-product LLM enrichment has never worked, in v1 or v2.**~~
  **FIXED 2026-08-03** (still broken in v1). Both causes — the placeholder
  answering its own cache lookup, and `_save_mapping` discarding
  `defaults` — are gone: `AUTHORITATIVE_MAPPING` (parser_version at the
  current version, or operator-validated) is the single predicate behind
  the cache and the fill's work list. Regression-tested in
  `apps/quoting/tests/test_product_parser.py::TestScraperEndOfRunFill`.
  The 2026-08-01 restore showed 559 of 1,203 mappings never parsed and
  0 of 7,614 products enriched; full detail in the parity ledger.
  **RUN FOR REAL 2026-08-04** against live Gemini and the loaded dev DB:
  all 559 placeholders filled in ~10 min (6 batches), zero AppErrors,
  back-flowed onto 2,043 of 7,614 products; every parser_confidence within
  numeric(3,2). The eight-months-broken code path now demonstrably works
  end to end.

- ~~**Decide the fate of the 559 stale placeholder mappings.**~~
  **DECIDED 2026-08-03**: left in place — the fixed end-of-run fill is
  deliberately a global backlog fill, so the next scrape picks all 559 up
  (~6 LLM calls; the 644 already-parsed rows are not re-processed).

- ~~**Beat wiring for the quoting endpoints.**~~
  `run_all_scrapers_weekly` is seeded in `config/celery.py`
  (Sunday 15:00 NZT, v1's workflow/0003 exactly), and
  `_with_periodic_task_headers` stamps every beat entry with its own name
  under `options.headers`, so `/api/quoting/scheduled-task-executions/`
  and `last_run_at` populate. Derived, not per-entry, so a new schedule
  cannot forget it.

