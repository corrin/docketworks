---
status: draft
---

# Prod → Dev DB refresh via prod-side scrubbed pg_dump

## Context

Both prod and dev now run Postgres. The current prod→dev refresh path uses Django `dumpdata` with in-memory Faker anonymisation (`apps/workflow/management/commands/backport_data_backup.py`), writes a gzipped JSON plus a schema-only `pg_dump`, and the dev restore uses `loaddata` via a 23-step manual runbook (`docs/restore-prod-to-nonprod.md`). `loaddata` deserialises every row through the ORM, which is slow, fragile as the schema grows, and already flaky enough that the runbook has accreted numerous workarounds.

Goal: replace the JSON round-trip with a native `pg_dump` / `pg_restore` cycle that is 10–100× faster, while keeping the invariant that **unanonymised prod data never leaves the prod host**. We achieve that by restoring into a sibling scrubbing DB on the prod cluster, running anonymisation there, then re-dumping the scrubbed DB as the artifact shipped to dev.

Outcome: one `manage.py backport_data_backup` command on prod produces `scrubbed_<env>_<ts>.dump` (custom-format). On dev, a short runbook restores it. The 23-step runbook collapses to ~7 steps, and dev refreshes stop taking minutes-per-thousand-rows.

## Shape

**One management command (same name as today, rewritten internals)** rather than a new command + shell scripts. Anonymisation SQL lives in a service module so it's unit-testable. Dev side is runbook-only — no wrapper command — because `pg_restore` + migrate + two fixture loads + xero reauth + validators is already a checklist people run by hand.

## Current state (brief)

- **Entry point being rewritten:** `apps/workflow/management/commands/backport_data_backup.py` — currently does `dumpdata` + Faker + `pg_dump --schema-only` + zip. Will become: `pg_dump` (raw) → `pg_restore` into scrub DB → call `db_scrubber.scrub()` → `pg_dump` (scrubbed) → cleanup raw.
- **Anonymisation logic worth reusing:** `apps/accounts/staff_anonymization.py` (coherent name/email profiles via `NAME_PROFILES`). Moves unchanged; `db_scrubber` calls into it for the staff table.
- **Existing shop/test-client allow-list** in `backport_data_backup.py` — migrates into `db_scrubber`.
- **Restore runbook:** `docs/restore-prod-to-nonprod.md` — 23 manual steps today.
- **Post-restore validators:** `scripts/restore_checks/` (13 scripts) — reuse as-is.
- **Prod backup tooling already Postgres-native:** `scripts/backup_db.sh`, `scripts/predeploy_backup.sh`, `scripts/predeploy_rollback.sh`, `scripts/cleanup_backups.py` use `pg_dump` / `pg_restore`. The pattern and env-loading are known to the ops side — reuse them via subprocess calls from the management command.
- **Constraint:** the Django DB user has no `CREATEDB` privilege (per `feedback_db_reset_method.md`); the scrub DB is pre-provisioned and the script uses `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` between runs.

## Proposed workflow

### Prod side (one command)

`manage.py backport_data_backup` orchestrates (all steps inside one Django command so error persistence via `persist_app_error` works; no shell scripts):

```
1. subprocess: pg_dump -Fc $DB_NAME                            → /tmp/raw_$TS.dump
2. subprocess: psql $SCRUB_DB_NAME -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
3. subprocess: pg_restore -d $SCRUB_DB_NAME /tmp/raw_$TS.dump
4. Django ORM on 'scrub' DB alias: db_scrubber.scrub()          # see Scrub operations
5. subprocess: pg_dump -Fc $SCRUB_DB_NAME                       → restore/scrubbed_<env>_$TS.dump
6. subprocess: psql $SCRUB_DB_NAME -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
7. rm /tmp/raw_$TS.dump
8. subprocess: rclone copy restore/scrubbed_<env>_$TS.dump <gdrive-target>
```

- `SCRUB_DB_NAME` = `dw_<client>_scrub`, pre-created once by ops alongside `dw_<client>_prod`.
- Step 4 uses a second Django DATABASES alias `scrub` (added to `settings.py`) that reads `SCRUB_DB_NAME` from env — nothing else in the app uses it. Anonymisation updates run with `.using("scrub")` inside a single transaction. Hard-fail if `settings.DATABASES["scrub"]["NAME"]` does not end in `_scrub`.
- Step 7 deletes the raw dump immediately after step 5 succeeds; raw PII is never written outside the prod host.
- Every step wrapped in try/except with `persist_app_error(exc)` + re-raise, per project convention.

### Dev side (runbook, no wrapper)

Rewritten `docs/restore-prod-to-nonprod.md`:

```
1. rclone copy <gdrive>/scrubbed_<env>_<ts>.dump ./restore/
2. psql $DB_NAME -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
3. pg_restore --no-owner --no-privileges -d $DB_NAME ./restore/scrubbed_<env>_<ts>.dump
4. .venv/bin/python manage.py migrate
5. .venv/bin/python manage.py loaddata apps/workflow/fixtures/company_defaults.json
   .venv/bin/python manage.py loaddata apps/workflow/fixtures/ai_providers.json
6. .venv/bin/python manage.py <xero reauth command>   # carry over from current runbook
7. .venv/bin/python scripts/restore_checks/run_all.py
```

- `loaddata` survives only for the two static fixtures that are deliberately absent from prod dumps (`company_defaults`, `ai_providers`).
- Step 4 handles the common case where dev migrations are ahead of the prod dump.

## Scrub operations (`apps/workflow/services/db_scrubber.py`)

Single `scrub()` entry point. All operations run via Django ORM on the `scrub` DB alias, in one transaction, fail-fast on any error (`persist_app_error` + re-raise):

| Target | Operation |
|---|---|
| `accounts_staff` + `accounts_historicalstaff` | Overwrite `first_name`, `last_name`, `preferred_name`, `email` with coherent profiles from `staff_anonymization.py`. Reset `password` to a known unusable placeholder. Set `xero_user_id = NULL`. |
| `client_client` | Replace `name` (except shop/test clients — allow-list migrates from current `backport_data_backup.py`), `email`, `phone`, `address`, `primary_contact_name`, `primary_contact_email` with Faker. Rewrite `additional_contact_persons` and `all_phones` JSON entries element-by-element. Set `raw_json = '{}'`. |
| `client_clientcontact` | Faker for `name`, `email`, `phone`, `position`. Blank `notes`. |
| `client_supplierpickupaddress` | Faker for address fields. Blank `notes`. |
| `job_job` + `job_historicalrecord` | Blank `notes`, `description`. Null out Xero IDs. |
| `job_costline` | Rewrite `meta` JSON: null out `meta->>'note'` and `meta->>'comments'`; keep `staff_id`, `is_billable`, `kind`-specific structure. Blank `desc` for entries whose description could leak PII (material lines referencing client names). |
| `job_jobevent` | **Leave untouched.** Not scrubbed until we audit the table and identify specific PII-bearing fields. See deferred decisions. |
| `purchasing_purchaseorder` | Set `raw_json = '{}'`. Null Xero IDs. |
| `purchasing_stock` | Set `raw_json = '{}'`. Null `xero_id`. |
| `accounting_invoice` / `bill` / `creditnote` + line items | Set `raw_json = '{}'`. Blank line `description`. Amounts left intact (commercial data in scope for dev — see deferred decisions). |
| `workflow_xerotoken` | `TRUNCATE` — tokens re-seeded manually on dev. |
| `workflow_serviceapikey` | `TRUNCATE` — re-seeded from fixtures. |
| Any other `*_historical*` table | `TRUNCATE` — keep schema, drop history. |

## Implementation tasks

Ordered, each a commit-sized unit:

1. **Ops: provision `dw_<client>_scrub` on prod.** Manual one-off: `createdb dw_<client>_scrub -O dw_<client>_prod` by the postgres admin. Record in the runbook's "first-time setup" section.
2. **Add `scrub` DB alias to `settings.py`.** Reads `SCRUB_DB_NAME` from env; same user/host/port as default. Present in every environment (dev fills it with a throwaway local DB name) so settings loading is not conditional.
3. **New `apps/workflow/services/db_scrubber.py`.** Implements the table-by-table operations in the matrix above. Exposes one public `scrub()` function. Fails fast, persists errors, runs in a single transaction. Imports `apps/accounts/staff_anonymization.py` unchanged.
4. **Rewrite `apps/workflow/management/commands/backport_data_backup.py`.** Replaces the current dumpdata/Faker/zip logic with the 8-step prod flow above. Produces `restore/scrubbed_<env>_<ts>.dump` (custom format). Removes JSON and schema.sql outputs.
5. **Rewrite `docs/restore-prod-to-nonprod.md`** for the new 7-step dev flow. Retain the old runbook as an appendix labeled "legacy JSON path" for one release cycle.
6. **Extend `scripts/cleanup_backups.py`** to include `scrubbed_*.dump` in its retention logic (30 days, same as predeploy backups).
7. **Tests:** unit tests for `db_scrubber.scrub()` against a fixture-loaded scrub DB, asserting no pre-scrub values survive in scrubbed columns. Integration test hitting the full command in a UAT-like local setup.

## Critical files

**Create:**
- `apps/workflow/services/db_scrubber.py`
- `apps/workflow/tests/services/test_db_scrubber.py`

**Modify:**
- `apps/workflow/management/commands/backport_data_backup.py` — full rewrite of internals; same command name
- `docketworks/settings.py` — add `scrub` DB alias
- `docs/restore-prod-to-nonprod.md` — full rewrite for new flow
- `scripts/cleanup_backups.py` — extend retention for `scrubbed_*.dump`
- `.env.example` — document `SCRUB_DB_NAME`

**Reuse unchanged:**
- `apps/accounts/staff_anonymization.py` — coherent staff profiles
- `scripts/restore_checks/*` — post-restore validators
- `scripts/backup_db.sh` — referenced pattern, not modified

## Verification

End-to-end before merging:
1. **Unit:** `test_db_scrubber.py` loads a fixture containing representative rows from each scrubbed table, runs `scrub()`, asserts via ORM queries that `email`, `name`, `notes`, `raw_json`, `meta->>'note'` etc. contain no pre-scrub values on every row.
2. **Integration:** on UAT (not prod), run `manage.py backport_data_backup` end-to-end; restore the resulting dump to the dev box via the new runbook; run `scripts/restore_checks/run_all.py`.
3. **Timing:** record wall-clock on a real-sized dataset; target at least 5× faster end-to-end than the current JSON path.
4. **Leak check:** `pg_restore -a -f - scrubbed_*.dump | grep -iE '<known prod client name>|<known staff email domain>'` must return nothing.

## Deferred decisions

1. **Commercial data in scope?** Plan leaves wage rates, charge-out rates, supplier pricing, invoice totals intact. If dev should get noised commercial data too, that's a scoped extension to `db_scrubber.py`.
2. **JobEvent audit.** Plan leaves `job_jobevent` unchanged. Before shipping the first scrubbed dump to dev, audit a representative sample of `description`, `delta_before`, `delta_after`, and `detail` contents against the PII categories (staff names/emails, client names, addresses, phone numbers). If specific PII-bearing patterns are found, add targeted scrub rules to `db_scrubber` — do not reflexively truncate.
3. **Rename the command?** `backport_data_backup` is misleading in the new world (it's a refresh-dump, not a backup). Renaming is optional and can be a follow-up; doing it here saves a separate touch but expands the PR surface.
4. **Scrub DB lifecycle** — plan keeps `dw_<client>_scrub` pre-provisioned with its public schema dropped between runs. Alternative would require granting `CREATEDB` to the prod DB user, which conflicts with `feedback_db_reset_method.md`.

## Trello ticket (draft — not yet created)

**Board:** Jobs Manager: Next 2 weeks
**Target list:** Improvements Requested (unrefined) — `68b4da6ff642f4bc1d6749e5`
**Suggested labels:** Tech Debt (blue), Requested by Corrin (orange)

**Name:** Rewrite backport_data_backup to use pg_dump/pg_restore with prod-side scrub DB

**Description:**

> **Why**
>
> Current dev refresh uses Django `dumpdata` + Faker + `loaddata`. It's slow (ORM per-row), fragile against schema churn, and the 23-step manual runbook (`docs/restore-prod-to-nonprod.md`) reflects accumulated workarounds. Now that both prod and dev run Postgres we can use native `pg_dump`/`pg_restore` for a 10–100× speedup.
>
> **What**
>
> Rewrite the internals of `manage.py backport_data_backup` (keep the command name). Introduce a prod-side *scrubbing DB* (`dw_<client>_scrub`). The command: `pg_dump` prod → `pg_restore` into scrub DB → call new `db_scrubber` service to anonymise in place → `pg_dump` the scrub DB → ship that `.dump` to dev. Raw PII never leaves the prod host. The dev runbook collapses to ~7 steps.
>
> **Deliverables**
> - [ ] Ops: `createdb dw_<client>_scrub` on prod cluster (one-off)
> - [ ] `apps/workflow/services/db_scrubber.py` (reuses `apps/accounts/staff_anonymization.py`)
> - [ ] Unit tests: `apps/workflow/tests/services/test_db_scrubber.py`
> - [ ] Rewrite internals of `apps/workflow/management/commands/backport_data_backup.py`
> - [ ] Add `scrub` DB alias to `docketworks/settings.py` + document `SCRUB_DB_NAME` in `.env.example`
> - [ ] Rewrite `docs/restore-prod-to-nonprod.md`
> - [ ] Extend `scripts/cleanup_backups.py` retention for `scrubbed_*.dump`
>
> **Out of scope**
> - Anonymising commercial data (wage rates, invoice totals)
> - Scrubbing `job_jobevent` (leave untouched until a PII audit identifies specific fields)
> - Renaming the command (deferred — see plan)
>
> **Plan:** `docs/plans/2026-04-22-prod-to-dev-scrubbed-dump.md`
