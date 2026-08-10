# Cutover checklist

**Cutover: Saturday 15 August 2026.** The date is immovable; scope bends.

Actions that must happen around the v1 → v2 switch, discovered as the rewrite
proceeds. Add to this file the moment a slice turns up an operational
prerequisite; do not rely on remembering it on the night.

## The release gate

Go/no-go is two independent questions; either failing is grounds to reject
(see "Cutover" in [`rewrite-status.md`](rewrite-status.md#cutover-saturday-15-august-2026)
for the full reasoning, including why the fallback is abort-and-stay-on-v1,
never ship-anyway):

- [ ] **Does this replicate all the functionality the business needs?**
      **Every MUST-tier E2E spec passes** is the measurable proxy — a red
      MUST spec means no release, this outranks everything below because
      the rest of this file assumes a working application and only E2E
      establishes that. Tier ownership lives in
      [`rewrite-status.md`](rewrite-status.md); SHOULD work, including AI,
      does not block this gate, and DEFERRED specs are outside the release
      suite. Progress is counted in specs green, never in endpoints
      written. **22 of those 40 are blocked behind a single UI flow**
      (create-job), not behind their own endpoints — see the per-spec
      table in [`rewrite-status.md`](rewrite-status.md) before estimating
      any of them.
- [ ] **Is this materially better architecture and code — enough to
      justify the move?** Not proxied by a single gate; judged directly
      against v1. No known compromise ships on the strength of "not
      blocking a spec" — a discovered architecture defect is gated work
      before cutover, not a post-cutover note (ADR 0039).

Two notes for anyone answering a v1-contract question during cutover:
`frontend/schema.yml` and the parity diff are **deleted**, so read
`../docketworks` (the live v1 repo) instead of this one; and v2's API is not
required to match v1's except where an external party holds the URL.

## Data prerequisites (do these BEFORE the cutover window)

- [ ] **Staff wage rates.** v2 refuses to price time for a staff member whose
      `base_wage_rate` is unset (ADR 0015; user decision 2026-08-03 — v1
      silently substituted the company default or costed $0.00). A check of
      the 2026-08-01 production restore found **6 of 24 staff rows with no
      rate, all current**, two of which are non-human (`System Automation`,
      `Default Admin`) and never book time. Set rates for every staff member
      who books time, or they get a 400 naming them on their first entry.
      Query: `select id, first_name, last_name from accounts_staff
      where (base_wage_rate = 0 or base_wage_rate is null) and date_left is null;`
- [ ] **Supplier-scraper credentials must be CURRENT, not merely present.** The
      Steel & Tube scrape silently stopped in Feb 2026 because the portal
      password changed and production was never updated — eight months of no
      price ingestion with no alarm. Verify a live login before cutover, and
      treat a scraper that stops producing rows as an incident, not noise.
- [ ] **Formerly-encrypted credentials.** The five columns that were Fernet
      ciphertext in v1 (crm `PhoneProviderSettings.username/password`, quoting
      `SupplierCredential.username/password/api_key`) are plain text in v2:
      decrypt with v1's `FIELD_ENCRYPTION_KEY` during the load, or re-enter
      them after cutover. See `scripts/ops/migrate_v1_data.sh`.

## Rehearsed mechanics (see the plan's Data migration section)

- [ ] `scripts/ops/db_schema_diff.sh` green against the production restore.
- [ ] `scripts/ops/migrate_v1_data.sh` load + row-count parity. Rehearsed
      2026-08-05 in the documented order (migrate into an empty database,
      THEN restore) from a production restore carrying v1's repair
      migrations: 77 tables compared, every business table exact. The only
      differences were the five tables the dump deliberately excludes
      (`auth_permission`, `django_content_type`, `django_migrations`,
      `django_session`, celery results — v2 regenerates or owns these) and
      the four `django_celery_beat_*` tables v2 dropped when beat schedules
      moved into code.
- [ ] **Sequences verified, not assumed.** The script now resets identity
      sequences via `pg_get_serial_sequence()` and FAILS if any is left behind
      its table. The original reset silently matched zero of twenty sequences
      (it used the serial-only `pg_depend.deptype = 'a'` idiom, while Django 6
      emits IDENTITY columns), so every insert after a load died with a
      duplicate key. Row-count checks cannot see this — only writing can.
- [ ] **Rehearse in the DOCUMENTED order — `migrate` first, THEN restore.**
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
- [ ] **`uv run python -m scripts.ops.validate_restored_data`** — exits non-zero
      if the load contains a row v2 will refuse to save. Three sweeps:
      dangling foreign keys (which `pg_restore --disable-triggers` cannot
      catch, since FK checks are triggers), foreign keys the models declare
      required but the column left NULL, and `full_clean()` over every row.
      CHECK/NOT NULL/UNIQUE are deliberately not re-checked — Postgres
      enforced those during the restore, so a completed load is already
      proof. Expect ZERO once v1's `data-repair-for-v2-validation` migrations
      have been deployed and a fresh dump taken; before that it reports the
      31 rows those migrations fix.
- [ ] **Run the app against the loaded data**: `scripts/ops/smoke_api.sh` must
      report no 5xx. This is what caught both the sequence bug and the
      `input_data` shape bug below; synthetic test fixtures produce only
      well-formed data.
- [ ] Full test suite and `./scripts/ops/run_e2e.sh` green against the loaded data; confirm the
      command reports a successful database restore and leaves no managed services running.

## Environment

- [ ] `CACHES["shared"]` Redis reachable (PDF-refresh dedup, django-solo
      propagation) — v2 fails at commit time on `Job.save()` without it.
- [ ] Required env vars present per `.env.example` (settings validate
      fail-fast at boot, so a missing one stops the service immediately).
- [ ] **Serving model fixed before deploy: `gunicorn --worker-class gthread
      --workers 3 --threads 16`** (or the ASGI equivalent), replacing v1's
      inherited `--workers 3` sync template. MUST before cutover — see
      "Slice 3 — live updates done properly" in
      [`rewrite-status.md`](rewrite-status.md#slice-3--live-updates-done-properly-must-before-cutover),
      decided 2026-08-11. The current sync-worker template pins one worker
      per open kanban tab; 3 office staff against 3 workers is zero spare
      capacity, including the Xero webhook and CRM phone-ingestion endpoints
      that hold exact URLs.

## Quoting slice (Phase 3c-3) — open decisions

Found while finishing the slice on 2026-08-03. Most were resolved on
2026-08-03/04 (recorded here so the checklist tells the truth an operator
needs at cutover); one decision remains open.

- [x] ~~**Supplier-product LLM enrichment has never worked, in v1 or v2.**~~
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

- [x] ~~**Decide the fate of the 559 stale placeholder mappings.**~~
      **DECIDED 2026-08-03**: left in place — the fixed end-of-run fill is
      deliberately a global backlog fill, so the next scrape picks all 559 up
      (~6 LLM calls; the 644 already-parsed rows are not re-processed).

- [ ] **Supplier price ingestion (Selenium + Steel & Tube) IS ported** —
      `SeleniumScraper` and `SteelAndTubeScraper` in `apps/quoting/scrapers/`,
      tested against a fake WebDriver. LIVE-VERIFIED 2026-08-04, credential-free
      layer only: the real sitemap fetched (HTTP 200, 11.7MB), our parser
      extracted 3,677 product URLs — a 100% exact match with the restore's
      3,677 known URLs — and confirmed a single shard. What remains unverifiable
      without portal credentials is login + page selectors: **run
      `manage.py run_scrapers --supplier "Steel & Tube" --limit 2` against
      production credentials before cutover** (see the stale-selector list in
      `scrapers/steel_and_tube.py`). Note the scrape appears DORMANT since
      **2026-02-22** (last completed `ScrapeJob`; last
      `SupplierProduct.last_scraped` is 2026-02-23), after roughly weekly runs
      from 2025-07 to 2026-02. The config and credential rows are absent from
      the restore, but that is the backup anonymisation stripping portal
      secrets, not evidence of deletion.

      DECISION NEEDED — did the S&T scrape stop on purpose in February, or did
      their site change and nobody noticed? That determines how much the
      pre-cutover live-portal run is allowed to find broken.

- [x] ~~**Beat wiring for the quoting endpoints.**~~ **DONE**:
      `run_all_scrapers_weekly` is seeded in `config/celery.py`
      (Sunday 15:00 NZT, v1's workflow/0003 exactly), and
      `_with_periodic_task_headers` stamps every beat entry with its own name
      under `options.headers`, so `/api/quoting/scheduled-task-executions/`
      and `last_run_at` populate. Derived, not per-entry, so a new schedule
      cannot forget it.

- [ ] **Celery connection hygiene has four implementations** (ADR 0039):
      `apps/job/tasks.py` inlines the guarded form four times,
      `apps/purchasing/tasks.py` extracts it, `apps/quoting/tasks.py` was
      unguarded until 2026-08-03, and `apps/crm/tasks.py` still calls the
      unguarded `close_old_connections()` twice. Unguarded closes the caller's
      connection when the task runs inside a transaction. One home in
      `apps/core` is the fix; it spans three merged slices.
