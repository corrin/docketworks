# Fix e2e_cleanup: handle remaining PROTECT FKs pointing at Job

> Filename note: the auto-generated plan name doesn't follow the `YYYY-MM-DD-description.md` convention. Rename to `2026-04-19-e2e-cleanup-protect-fks.md` before merging.

## Context

`apps/workflow/management/commands/e2e_cleanup.py` already unwinds two PROTECT FKs before deleting test jobs and test clients:
- `Invoice.job` (line 142)
- `PurchaseOrder.supplier` (line 147)

But three more `on_delete=PROTECT` FKs also point at `Job` and aren't handled. On the current DB, a `--confirm` run crashes with `ProtectedError` citing 3 Quotes (jobs 96369, 96117, 95431) and 2 PurchaseOrderLines. `QuoteSpreadsheet` has the same exposure — no rows hit it on this DB, but the gap is real.

The fix extends the existing pattern in the same file. `on_delete=PROTECT` stays on the models — it's the correct production behavior. The cleanup command is the right place to explicitly unwind protected references in test data.

Note: the referring bug report called the third model `JobSpreadsheet`. The actual class is `QuoteSpreadsheet` (defined in `apps/job/models/spreadsheet.py:6`, exported from `apps.job.models`). The plan uses the correct name.

## Files to modify

- `apps/workflow/management/commands/e2e_cleanup.py` — only file changed.

## PROTECT FKs pointing at Job (verified exhaustively)

| Model | Field | Definition | Handled before? |
|---|---|---|---|
| `Invoice` | `job` | `apps/accounting/models/invoice.py:106-111` | Yes |
| `Quote` | `job` (OneToOne) | `apps/accounting/models/quote.py:15-17` | **No — fix needed** |
| `PurchaseOrderLine` | `job` | `apps/purchasing/models.py:234-241` | **No — fix needed** |
| `QuoteSpreadsheet` | `job` (OneToOne) | `apps/job/models/spreadsheet.py:48-54` | **No — fix needed** |

All other `Job` FKs use CASCADE or SET_NULL (verified by grepping `job = models.(OneToOneField|ForeignKey)(` across `apps/`).

## Changes

### 1. New imports (top of file, alongside existing imports)

```python
from django.db import transaction

from apps.accounting.models import Invoice, Quote
from apps.job.models import Job, QuoteSpreadsheet
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
```

(Merges with the existing `Invoice`/`Job`/`PurchaseOrder` imports — don't duplicate.)

### 2. After `all_jobs_to_delete` is computed (currently line 112-114), collect the new protected dependents alongside the existing `linked_invoices`

```python
linked_invoices = Invoice.objects.filter(job__in=all_jobs_to_delete)
linked_quotes = Quote.objects.filter(job__in=all_jobs_to_delete)
linked_po_lines = PurchaseOrderLine.objects.filter(job__in=all_jobs_to_delete)
linked_quote_sheets = QuoteSpreadsheet.objects.filter(job__in=all_jobs_to_delete)
```

### 3. Report them in the same dry-run report block (currently lines 118-123)

Report each via `_report_queryset`, same pattern as `linked_invoices`:

```python
if linked_invoices.exists():
    self._report_queryset("Invoices linked to test jobs (will be deleted)", linked_invoices, "number")
if linked_quotes.exists():
    self._report_queryset("Quotes linked to test jobs (will be deleted)", linked_quotes, "number")
if linked_po_lines.exists():
    self._report_queryset("PO lines linked to test jobs (will be deleted)", linked_po_lines, "description")
if linked_quote_sheets.exists():
    self._report_queryset("Quote spreadsheets linked to test jobs (will be deleted)", linked_quote_sheets, "sheet_id")
```

(`number` is nullable on `Quote` — `_report_queryset` orders by and prints the field verbatim; `None` values render as `None`, which matches existing behaviour for other nullable reporting fields. No special handling needed.)

### 4. Delete them inside the deletion block, before `test_client_jobs.delete()` (line 152)

The existing deletion order is PROTECTED dependents first, then the protected parent. Extend the same principle: the three new querysets must be deleted before any job delete runs (test_client_jobs, legacy_client_jobs, test_jobs).

Insert **after** the existing Invoice/PO deletes (lines 142-149) and **before** `test_client_jobs.delete()`:

```python
count, details = linked_quotes.delete()
if count:
    self.stdout.write(f"  Quotes: {count} objects ({details})")

count, details = linked_po_lines.delete()
if count:
    self.stdout.write(f"  PO lines: {count} objects ({details})")

count, details = linked_quote_sheets.delete()
if count:
    self.stdout.write(f"  Quote spreadsheets: {count} objects ({details})")
```

### 5. Wrap the whole deletion block in `transaction.atomic()`

Starting at line 138 (`# Delete in correct order` comment) through line 178 (the last `test_clients.delete()`), wrap with:

```python
with transaction.atomic():
    # existing deletion block (all nine delete() calls)
    ...
```

This makes rollback-on-failure explicit rather than relying on Django's implicit transaction handling around management commands. The `sync_sequences` call (lines 105-109) stays **outside** the atomic block — it commits deliberately.

## Verification

1. Dry run listed the rows to delete:
   ```
   python manage.py e2e_cleanup
   ```
   Expected: report section now includes `Quotes linked to test jobs (will be deleted)` with the 3 rows (jobs 96369, 96117, 95431), and `PO lines linked to test jobs (will be deleted)` with the 2 rows. (`Quote spreadsheets` section absent if none exist — that's fine.)

2. Confirmed run completes without `ProtectedError`:
   ```
   python manage.py e2e_cleanup --confirm
   ```
   Expected: "Done." with no traceback. The delete counters show the quotes/PO lines/quote sheets being removed in the new output lines, then the usual cascade output for the jobs.

3. Re-running the confirmed command produces "No test data found. Database is clean." (idempotency sanity check).

4. Full E2E run still works end-to-end (exercises cleanup against a fresh DB after a test run):
   ```
   cd frontend && npm run test:e2e
   ```
   Expected: suite passes; teardown cleanup completes cleanly.

## Out of scope

- Changing any `on_delete=PROTECT` to `CASCADE`. PROTECT is correct production behavior; this is a test-harness gap only.
- Other PROTECT FKs pointing at `Client` from `quoting` models (`ScrapedProduct`, `PriceList`, `SupplierScrapeJob`). E2E tests don't populate these, and extending cleanup there would be speculative. Revisit if a future test run fails on one of those.
