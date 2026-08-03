# Cutover checklist

Actions that must happen around the v1 → v2 switch, discovered as the rewrite
proceeds. Add to this file the moment a slice turns up an operational
prerequisite; do not rely on remembering it on the night.

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
      them after cutover. See `scripts/migrate_v1_data.sh`.

## Rehearsed mechanics (see the plan's Data migration section)

- [ ] `scripts/db_schema_diff.sh` green against the production restore.
- [ ] `scripts/migrate_v1_data.sh` load + row-count parity (71/71 business
      tables at the last rehearsal).
- [ ] **Sequences verified, not assumed.** The script now resets identity
      sequences via `pg_get_serial_sequence()` and FAILS if any is left behind
      its table. The original reset silently matched zero of twenty sequences
      (it used the serial-only `pg_depend.deptype = 'a'` idiom, while Django 6
      emits IDENTITY columns), so every insert after a load died with a
      duplicate key. Row-count checks cannot see this — only writing can.
- [ ] **Run the app against the loaded data**: `scripts/smoke_api.sh` (or the
      "Smoke API (real data)" VS Code task) must report no 5xx. This is what
      caught both the sequence bug and the `input_data` shape bug below;
      synthetic test fixtures produce only well-formed data.
- [ ] Full test suite and the ported E2E suite green against the loaded data.

## Environment

- [ ] `CACHES["shared"]` Redis reachable (PDF-refresh dedup, django-solo
      propagation) — v2 fails at commit time on `Job.save()` without it.
- [ ] Required env vars present per `.env.example` (settings validate
      fail-fast at boot, so a missing one stops the service immediately).

## Quoting slice (Phase 3c-3) — open decisions

Found while finishing the slice on 2026-08-03. All three need a decision
BEFORE cutover; none is a code defect introduced by v2.

- [ ] **Supplier-product LLM enrichment has never worked, in v1 or v2.**
      `populate_all_mappings_with_llm` never calls the model: the empty
      placeholder `create_mapping_record` reserves answers its own cache
      lookup in `parse_products_batch`, and `_save_mapping`'s `get_or_create`
      then returns that placeholder without applying `defaults`. Both causes
      are v1's, verbatim. Confirmed against the 2026-08-01 restore
      (`dw_v2_dataload`):

      ```sql
      SELECT count(*) AS mappings,
             count(*) FILTER (WHERE parser_version IS NOT NULL) AS parser_ran,
             count(*) FILTER (WHERE parser_version IS NULL)     AS never_parsed
      FROM quoting_productparsingmapping;
      -- 1203 | 644 | 559
      SELECT count(*) AS products,
             count(*) FILTER (WHERE parsed_item_code IS NOT NULL) AS with_data
      FROM quoting_supplierproduct;
      -- 7614 | 0
      ```

      The 559 never-parsed rows are exactly the 559 JSON-string-shaped rows
      that migration `quoting/0002` normalises — that shape is written only by
      `create_mapping_record`, i.e. only by the scraper path. The 644 that did
      parse are the stock-parser path, which works. So: **0 of 7,614 supplier
      products carry any parsed data, and the `/api/purchasing/product-mappings/`
      review screen ships with 559 permanently-empty rows in it.**

      DECISION NEEDED — the fix picks (a) which column means "the parser has
      run" (`parser_version` is honest; v1's `mapped_item_code__isnull` would
      re-parse forever any product the model gives no item code) and (b)
      whether filling a placeholder may overwrite a mapping an operator has
      already hand-validated. Regression tests are already written and
      currently `xfail(strict=True)` in
      `apps/quoting/tests/test_product_parser.py::TestScraperEndOfRunFillIsBroken`;
      they flip to passing when the fix lands.

- [ ] **Decide the fate of the 559 stale placeholder mappings**: leave them
      for the fixed fill to pick up, or clear them during the load.

- [ ] **No supplier price ingestion exists in v2.** v1's Selenium scraper
      (`apps/quoting/scrapers/steel_and_tube.py`, 509 lines) is deliberately
      not ported and `selenium` is not a v2 dependency — see the SELENIUM SEAM
      note in `apps/quoting/scrapers/base.py`. Everything above the browser IS
      ported and tested. Note the scrape appears DORMANT since **2026-02-22**
      (last completed `ScrapeJob`; last `SupplierProduct.last_scraped` is
      2026-02-23), after roughly weekly runs from 2025-07 to 2026-02. The
      config and credential rows are absent from the restore, but that is the
      backup anonymisation stripping portal secrets, not evidence of deletion.

      DECISION NEEDED — did the S&T scrape stop on purpose in February, or did
      their site change and nobody noticed? That determines whether porting
      the browser layer is a cutover blocker or a cleanup.

- [ ] **Beat wiring for the quoting endpoints.** `config/celery.py` has no
      `run_all_scrapers_task` entry (v1 seeded Sunday 15:00 NZT in
      `workflow/0003`) — correct while the scrapers are unported, but it must
      land with them. Separately, every entry in `config/celery.py` needs
      `"options": {"periodic_task_name": "<entry name>"}` or
      `/api/quoting/scheduled-task-executions/` and `last_run_at` stay
      permanently empty; see the module docstring in
      `apps/quoting/services/scheduled_task_service.py`.

- [ ] **Celery connection hygiene has four implementations** (ADR 0039):
      `apps/job/tasks.py` inlines the guarded form four times,
      `apps/purchasing/tasks.py` extracts it, `apps/quoting/tasks.py` was
      unguarded until 2026-08-03, and `apps/crm/tasks.py` still calls the
      unguarded `close_old_connections()` twice. Unguarded closes the caller's
      connection when the task runs inside a transaction. One home in
      `apps/core` is the fix; it spans three merged slices.
