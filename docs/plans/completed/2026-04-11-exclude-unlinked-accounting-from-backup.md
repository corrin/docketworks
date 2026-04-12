# Exclude Unlinked Accounting Records from Backup, Seed Quotes to Dev Xero

## Context

The prod-to-nonprod backup currently dumps all invoices, bills, credit notes, and quotes regardless of whether they're linked to jobs. Bills and credit notes have no job FK at all -- they're pure accounting data that gets synced inbound from Xero. Orphaned invoices (no job link) are already deleted during seed step 18, but we're wasting backup/restore time serializing them. Quotes with no job link serve no purpose in dev either.

This change makes the backup only include job-relevant financial records, and adds quote seeding to the restore pipeline (matching the existing invoice seeding pattern).

No Journal model exists in the codebase -- confirmed.

## Changes

### 1. Backup filtering (`apps/workflow/management/commands/backport_data_backup.py`)

No changes to EXCLUDE_MODELS. Models without job links are excluded implicitly by the filtering logic below -- if a future model adds a job FK to Bill or CreditNote, the filtering will automatically start including linked records.

**Add post-parse filtering** before anonymization:

After `data = json.loads(result.stdout)` (line 143) and before the anonymization loop, call a new `_filter_unlinked_accounting_records(data)` method that:
1. Collects PKs of invoices where `fields.job` is not null
2. Removes invoices where job is null
3. Removes invoice line items whose `fields.invoice` FK is not in the kept set
4. Removes quotes where `fields.job` is null
5. Removes all bills and bill line items (no job FK exists on model)
6. Removes all credit notes and credit note line items (no job FK exists on model)
7. Logs counts of what was filtered

The PII_CONFIG entries for `accounting.bill` and `accounting.creditnote` become unreachable but are left in place as documentation of which fields contain PII on those models.

### 2. Quote seeding (`apps/workflow/management/commands/seed_xero_from_database.py`)

Add quotes as a new entity in the seed pipeline, slotted after invoices and before stock.

**Imports to add:**
- `from apps.accounting.models import Quote`
- `from xero_python.accounting.models import Quote as XeroQuote` (same import as `xero_quote_manager.py:10`)

**Changes to `handle()`:**
- Add `"quotes"` to `VALID_ENTITIES`
- Add `quotes_result` tracking dict
- Add quote sync phase between invoices and stock
- Add quotes to summary output

**New `process_quotes(dry_run)` method** -- mirrors `process_invoices()`:
- Delete orphaned quotes (defensive, backup should exclude these now)
- Find job-linked quotes, skip those whose client has no `xero_contact_id`
- Call `_seed_single_quote()` for each, with rate limiting

**New `_seed_single_quote(quote, xero_api, xero_tenant_id)` method:**
- Build `XeroContact` from `quote.client.xero_contact_id`
- Create single `LineItem` from quote totals (Quote has no stored line items)
- Build `XeroQuote` with contact, line items, date, status=DRAFT, currency=NZD
- Call `xero_api.create_quotes()` (exists at `xero_base_manager.py:199`)
- Save new `xero_id` and `xero_tenant_id` back to local Quote record
- Quote `xero_id` is NOT NULL (`UUIDField(unique=True)`, no `null=True`), same constraint as Invoice -- overwrite rather than clear

**Add comment to `clear_production_xero_ids()`** (after the invoice comment block around line 696):
- Note that quotes are handled by `process_quotes()` same as invoices (xero_id is NOT NULL, can't be cleared)

### 3. Documentation (`docs/restore-prod-to-nonprod.md`)

Update Step 18's "What this does" list to mention:
- Bills, credit notes, and orphaned invoices/quotes are excluded from the backup
- Quote seeding (delete orphaned, recreate job-linked in dev Xero)

Update `check_xero_seed.py` expected output if it checks quote counts.

## Files to modify

| File | Change |
|------|--------|
| `apps/workflow/management/commands/backport_data_backup.py` | Add filtering method (no EXCLUDE_MODELS changes) |
| `apps/workflow/management/commands/seed_xero_from_database.py` | Add quotes entity, process_quotes, _seed_single_quote |
| `docs/restore-prod-to-nonprod.md` | Update step 18 description |

## Verification

1. Run backup on dev: `python manage.py backport_data_backup` -- check logged filter counts, verify output JSON contains no bills/credit notes/orphaned invoices/orphaned quotes
2. `zcat restore/*.json.gz | python -c "import json,sys; data=json.load(sys.stdin); models=set(d['model'] for d in data); print(sorted(models))"` -- confirm no `accounting.bill`, `accounting.billlineitem`, `accounting.creditnote`, `accounting.creditnotelineitem`
3. Run seed with `--dry-run --only quotes` to verify quote discovery logic
4. Full restore test on dev environment
