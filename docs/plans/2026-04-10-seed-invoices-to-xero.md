# Seed Invoices to Xero on Dev Restore

## Context

When restoring a production database to dev, Invoice records come with `xero_id` values pointing at prod's Xero tenant. The `xero_id` field is NOT NULL, so we can't just clear it like we do with contacts/projects. The existing TODO at `seed_xero_from_database.py:435` acknowledges this gap.

**Goal:** Add an "invoices" phase to the seed command that:
1. Deletes Invoice records not linked to any Job (orphaned invoices from Xero sync)
2. Re-creates job-linked invoices in dev Xero using the stored financial data, then updates the local `xero_id` to point at the new dev invoice

## Plan

### Step 1: Add invoice cleanup/seed logic to `seed_xero_from_database.py`

**File:** `apps/workflow/management/commands/seed_xero_from_database.py`

Add `"invoices"` to `VALID_ENTITIES` and a new `process_invoices()` method. Run it **after** contacts (needs `xero_contact_id`) and **after** projects (optional but logical ordering).

#### `process_invoices(dry_run)`:

1. **Delete orphaned invoices** — `Invoice.objects.filter(job__isnull=True).delete()` plus their `InvoiceLineItem` cascade. Log count.

2. **Find job-linked invoices** — `Invoice.objects.filter(job__isnull=False)`. These need re-creating in dev Xero.

3. **For each invoice**, use the Xero API directly (not XeroInvoiceManager, which recalculates from CostSet):
   - Build a Xero invoice payload from stored fields: `number`, `date`, `due_date`, `total_excl_tax`, `tax`, `status`, client's `xero_contact_id`, line items from `InvoiceLineItem` records
   - Call `xero_api.create_invoices()` with the payload
   - Update the local Invoice's `xero_id` and `xero_tenant_id` with the response
   - Sleep 1s between API calls (rate limiting, matching existing pattern)

4. **Error handling**: `persist_app_error(exc)`, log failure, continue to next invoice (don't halt the whole seed for one bad invoice). Collect failed invoice numbers for summary.

### Step 2: Update `clear_production_xero_ids`

Replace the TODO comment at line 435 with a note that invoices are handled in `process_invoices` (orphans deleted, job-linked re-created with new xero_id).

### Step 3: Wire into `handle()`

Add the invoices phase between projects and stock in the execution order:
```
contacts → projects → invoices → stock → employees
```

Update the summary output to include invoice counts.

## Key files

- `apps/workflow/management/commands/seed_xero_from_database.py` — main changes
- `apps/accounting/models/invoice.py` — Invoice, InvoiceLineItem models (read-only reference)
- `apps/workflow/views/xero/xero_base_manager.py` — payload construction pattern reference
- `apps/workflow/views/xero/xero_helpers.py` — `clean_payload`, `convert_to_pascal_case`

## Verification

1. `--dry-run` should show orphaned invoice count and job-linked invoices that would be seeded
2. `--only invoices` should work in isolation (requires contacts already seeded)
3. After full run, `Invoice.objects.filter(job__isnull=True).count()` should be 0
4. Job-linked invoices should have valid dev `xero_id` values visible in Xero
