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
