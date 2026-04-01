# Rename all non-standard database tables to Django defaults

## Context

Moving from MySQL to PostgreSQL. Since no production Postgres data exists yet, this is the clean window to rename 30 tables from their legacy `workflow_*` names to Django's standard `appname_modelname` convention. Removes all explicit `db_table` overrides so Django controls table names going forward.

## Tables to rename (30)

### accounting (7)
| Current | New |
|---|---|
| workflow_invoice | accounting_invoice |
| workflow_bill | accounting_bill |
| workflow_creditnote | accounting_creditnote |
| workflow_invoicelineitem | accounting_invoicelineitem |
| workflow_billlineitem | accounting_billlineitem |
| workflow_creditnotelineitem | accounting_creditnotelineitem |
| workflow_quote | accounting_quote |

### accounts (4)
| Current | New |
|---|---|
| workflow_staff | accounts_staff |
| workflow_historicalstaff | accounts_historicalstaff |
| workflow_staff_groups | accounts_staff_groups |
| workflow_staff_user_permissions | accounts_staff_user_permissions |

### client (3)
| Current | New |
|---|---|
| workflow_client | client_client |
| client_contact | client_clientcontact |
| client_supplier_pickup_address | client_supplierpickupaddress |

### job (6)
| Current | New |
|---|---|
| workflow_job | job_job |
| workflow_historicaljob | job_historicaljob |
| workflow_jobevent | job_jobevent |
| workflow_jobfile | job_jobfile |
| job_quote_chat | job_jobquotechat |
| workflow_job_people | job_job_people |

### purchasing (5)
| Current | New |
|---|---|
| workflow_purchaseorder | purchasing_purchaseorder |
| workflow_purchaseorderline | purchasing_purchaseorderline |
| workflow_purchaseordersupplierquote | purchasing_purchaseordersupplierquote |
| workflow_stock | purchasing_stock |
| workflow_purchaseorderevent | purchasing_purchaseorderevent |

### process (1)
| Current | New |
|---|---|
| process_form_entry | process_formentry |

### workflow (3)
| Current | New |
|---|---|
| workflow_app_error | workflow_apperror |
| workflow_xero_error | workflow_xeroerror |
| workflow_service_api_key | workflow_serviceapikey |

Note: `process_form`, `process_procedure`, `workflow_aiprovider`, `workflow_xeropayitem`, `workflow_xeropayrun`, `workflow_xeropayslip`, `job_jobdeltarejection` already match defaults — just remove their redundant `db_table` overrides.

## Implementation steps

### Step 1: Create Django migrations (one per app)

For each app, create a migration with `AlterModelTable` operations. PostgreSQL handles FK constraint updates automatically on `ALTER TABLE ... RENAME TO`. Order matters — rename parent tables before dependents.

**Files to create:**
- `apps/accounting/migrations/NNNN_rename_tables_to_defaults.py`
- `apps/accounts/migrations/NNNN_rename_tables_to_defaults.py`
- `apps/client/migrations/NNNN_rename_tables_to_defaults.py`
- `apps/job/migrations/NNNN_rename_tables_to_defaults.py`
- `apps/purchasing/migrations/NNNN_rename_tables_to_defaults.py`
- `apps/process/migrations/NNNN_rename_tables_to_defaults.py`
- `apps/workflow/migrations/NNNN_rename_tables_to_defaults.py`

Each migration uses `AlterModelTable` for regular models and raw SQL for SimpleHistory and M2M tables that Django's `AlterModelTable` doesn't cover.

### Step 2: Remove `db_table` overrides from model Meta

Remove explicit `db_table` from all model Meta classes listed above. For models that already match the default, also remove the redundant override.

**Files to modify:**
- `apps/accounting/models/invoice.py` — Invoice, Bill, CreditNote, InvoiceLineItem, BillLineItem, CreditNoteLineItem
- `apps/accounting/models/quote.py` — Quote
- `apps/accounts/models.py` — Staff
- `apps/client/models.py` — Client, ClientContact, SupplierPickupAddress. Add `db_table = "client_client"` to Supplier proxy.
- `apps/job/models/job.py` — Job, HistoricalRecords table_name
- `apps/job/models/job_event.py` — JobEvent
- `apps/job/models/job_file.py` — JobFile
- `apps/job/models/job_quote_chat.py` — JobQuoteChat
- `apps/job/models/job_delta_rejection.py` — remove redundant db_table
- `apps/purchasing/models.py` — PurchaseOrder, PurchaseOrderLine, PurchaseOrderSupplierQuote, Stock, PurchaseOrderEvent
- `apps/process/models/form.py` — remove redundant db_table + HistoricalRecords table_name
- `apps/process/models/form_entry.py` — FormEntry + HistoricalRecords table_name
- `apps/process/models/procedure.py` — remove redundant db_table + HistoricalRecords table_name
- `apps/workflow/models/app_error.py` — AppError, XeroError
- `apps/workflow/models/service_api_key.py` — ServiceAPIKey
- `apps/workflow/models/ai_provider.py` — remove redundant db_table
- `apps/workflow/models/xero_pay_item.py` — remove redundant db_table
- `apps/workflow/models/xero_payroll.py` — remove redundant db_table

### Step 3: Update raw SQL references

**E2E test scripts:**
- `frontend/tests/scripts/global-teardown.ts` — `workflow_xerotoken` (stays the same, already default)
- `frontend/tests/scripts/db-backup-utils.ts` — `workflow_job` -> `job_job`, `client_contact` -> `client_clientcontact`, `workflow_client` -> `client_client`

**Management commands:**
- `apps/workflow/management/commands/seed_xero_from_database.py` — update all table references: `workflow_client` -> `client_client`, `workflow_stock` -> `purchasing_stock`, `workflow_xeropayitem` (stays same), `accounting_invoice`/`accounting_bill`/`accounting_quote` (already correct), `purchasing_purchaseorder` (already correct)
- `apps/workflow/management/commands/e2e_cleanup.py` — `workflow_historicaljob_history_id_seq` -> `job_historicaljob_history_id_seq`, `workflow_historicaljob` -> `job_historicaljob`

**Old migrations:** Leave alone. They've already run and won't run again.

### Step 4: Regenerate `__init__.py` files

Run `python scripts/update_init.py` after changes.

## Verification

1. `python manage.py makemigrations --check` — should detect no further changes
2. `python manage.py migrate` — apply the rename migrations
3. `python manage.py test` — Django unit tests pass
4. `cd frontend && npx playwright test tests/job/create-estimate-entry.spec.ts` — E2E tests pass (exercises job creation, cost lines, DB backup/restore)
5. Verify table names: `python -c "from django.apps import apps; [print(m._meta.db_table) for m in apps.get_models() if m._meta.db_table != f'{m._meta.app_label}_{m._meta.model_name}' and not m._meta.db_table.startswith('django_') and not m._meta.db_table.startswith('auth_')]"` — should only show the Supplier proxy
