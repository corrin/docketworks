# Database

> **Navigation aid.** Schema shapes and field types extracted via AST. Read the actual schema source files before writing migrations or query logic.

**django** — 45 models

### Invoice

fk: job_id

- `job_id`: integer _(fk)_
- `online_url`: string _(nullable)_
- _relations_: job: one(Job)

### InvoiceLineItem

fk: invoice_id

- `invoice_id`: integer _(fk)_
- _relations_: invoice: one(Invoice)

### BillLineItem

fk: bill_id

- `bill_id`: integer _(fk)_
- _relations_: bill: one(Bill)

### CreditNoteLineItem

fk: credit_note_id

- `credit_note_id`: integer _(fk)_
- _relations_: credit_note: one(CreditNote)

### Quote

pk: `id` (uuid) · fk: job_id, client_id

- `id`: uuid _(pk, default)_
- `xero_id`: uuid _(unique)_
- `xero_tenant_id`: string _(nullable)_
- `job_id`: integer _(fk)_
- `client_id`: integer _(fk)_
- `date`: date
- `status`: string _(default)_
- `total_excl_tax`: decimal
- `total_incl_tax`: decimal
- `xero_last_modified`: timestamp _(nullable)_
- `xero_last_synced`: timestamp _(default)_
- `number`: string _(nullable)_
- `online_url`: string _(nullable)_
- `raw_json`: json _(nullable)_
- _relations_: job: one(Job), client: one(Client)

### Client

pk: `id` (uuid) · fk: merged_into_id

- `id`: uuid _(pk, default)_
- `xero_contact_id`: string _(unique, nullable)_
- `xero_tenant_id`: string _(nullable)_
- `name`: string
- `email`: string _(nullable)_
- `phone`: string _(nullable)_
- `address`: string _(nullable)_
- `is_account_customer`: boolean _(default)_
- `is_supplier`: boolean _(default)_
- `allow_jobs`: boolean _(default)_
- `xero_last_modified`: timestamp
- `raw_json`: json _(nullable)_
- `primary_contact_name`: string _(nullable)_
- `primary_contact_email`: string _(nullable)_
- `additional_contact_persons`: json _(nullable, default)_
- `all_phones`: json _(nullable, default)_
- `django_created_at`: timestamp
- `django_updated_at`: timestamp
- `xero_last_synced`: timestamp _(nullable, default)_
- `xero_archived`: boolean _(default)_
- `xero_merged_into_id`: string _(nullable)_
- `merged_into_id`: integer _(fk)_
- _relations_: merged_into: one(self)

### ClientContact

pk: `id` (uuid) · fk: client_id

- `id`: uuid _(pk, default)_
- `client_id`: integer _(fk)_
- `name`: string
- `email`: string _(nullable)_
- `phone`: string _(nullable)_
- `position`: string _(nullable)_
- `is_primary`: boolean _(default)_
- `notes`: string _(nullable)_
- `is_active`: boolean _(default)_
- _relations_: client: one(Client)

### SupplierPickupAddress

pk: `id` (uuid) · fk: client_id

- `id`: uuid _(pk, default)_
- `client_id`: integer _(fk)_
- `name`: string
- `street`: string
- `suburb`: string _(nullable)_
- `city`: string
- `state`: string _(nullable)_
- `postal_code`: string _(nullable)_
- `country`: string _(default)_
- `google_place_id`: string _(nullable)_
- `latitude`: decimal _(nullable)_
- `longitude`: decimal _(nullable)_
- `is_primary`: boolean _(default)_
- `notes`: string _(nullable)_
- `is_active`: boolean _(default)_
- _relations_: client: one(Client)

### CostSet

pk: `id` (uuid) · fk: job_id

- `id`: uuid _(pk, default)_
- `job_id`: integer _(fk)_
- `kind`: string
- `rev`: integer
- `summary`: json _(default)_
- `created`: timestamp
- _relations_: job: one(Job)

### CostLine

pk: `id` (uuid) · fk: cost_set_id, xero_pay_item_id

- `id`: uuid _(pk, default)_
- `cost_set_id`: integer _(fk)_
- `kind`: string
- `desc`: string
- `quantity`: decimal _(default)_
- `unit_cost`: decimal _(default)_
- `unit_rev`: decimal _(default)_
- `ext_refs`: json _(default)_
- `meta`: json _(default)_
- `accounting_date`: date
- `xero_time_id`: string _(nullable)_
- `xero_expense_id`: string _(nullable)_
- `xero_last_modified`: timestamp _(nullable)_
- `xero_last_synced`: timestamp _(nullable, default)_
- `approved`: boolean _(default)_
- `xero_pay_item_id`: integer _(fk)_
- _relations_: cost_set: one(CostSet), xero_pay_item: one(XeroPayItem)

### Job

pk: `id` (uuid) · fk: client_id, contact_id, created_by_id, latest_estimate_id, latest_quote_id, latest_actual_id, default_xero_pay_item_id

- `id`: uuid _(pk, default)_
- `name`: string
- `client_id`: integer _(fk)_
- `order_number`: string _(nullable)_
- `contact_id`: integer _(fk)_
- `job_number`: integer _(unique)_
- `description`: string _(nullable)_
- `delivery_date`: date _(nullable)_
- `completed_at`: timestamp _(nullable)_
- `rdti_type`: string _(nullable)_
- `pricing_methodology`: string _(default)_
- `price_cap`: decimal _(nullable)_
- `speed_quality_tradeoff`: string _(default)_
- `job_is_valid`: boolean _(default)_
- `charge_out_rate`: decimal
- `complex_job`: boolean _(default)_
- `notes`: string _(nullable)_
- `created_by_id`: integer _(fk)_
- `latest_estimate_id`: integer _(fk)_
- `latest_quote_id`: integer _(fk)_
- `latest_actual_id`: integer _(fk)_
- `priority`: float _(default)_
- `min_people`: integer _(default)_
- `max_people`: integer _(default)_
- `xero_project_id`: string _(unique, nullable)_
- `xero_default_task_id`: string _(nullable)_
- `xero_last_modified`: timestamp _(nullable)_
- `xero_last_synced`: timestamp _(nullable, default)_
- `default_xero_pay_item_id`: integer _(fk)_
- _relations_: client: one(Client), contact: one(ClientContact), created_by: one(Staff), people: many(Staff), latest_estimate: one(CostSet), latest_quote: one(CostSet), latest_actual: one(CostSet), default_xero_pay_item: one(XeroPayItem)

### JobDeltaRejection

pk: `id` (uuid) · fk: job_id, staff_id, resolved_by_id

- `id`: uuid _(pk, default)_
- `job_id`: integer _(fk)_
- `staff_id`: integer _(fk)_
- `change_id`: uuid _(nullable)_
- `reason`: string
- `detail`: string
- `envelope`: json
- `checksum`: string
- `request_etag`: string
- `request_ip`: string _(nullable)_
- `resolved`: boolean _(default)_
- `resolved_by_id`: integer _(fk)_
- `resolved_timestamp`: timestamp _(nullable)_
- _relations_: job: one(Job), staff: one(Staff), resolved_by: one(Staff)

### JobEvent

pk: `id` (uuid) · fk: job_id, staff_id

- `id`: uuid _(pk, default)_
- `job_id`: integer _(fk)_
- `timestamp`: timestamp _(default)_
- `staff_id`: integer _(fk)_
- `event_type`: string _(default)_
- `schema_version`: integer _(default)_
- `change_id`: uuid _(nullable)_
- `delta_before`: json _(nullable)_
- `delta_after`: json _(nullable)_
- `delta_meta`: json _(nullable)_
- `delta_checksum`: string _(default)_
- `detail`: json _(default)_
- `dedup_hash`: string _(nullable)_
- _relations_: job: one(Job), staff: one(Staff)

### JobFile

pk: `id` (uuid) · fk: job_id

- `id`: uuid _(pk, default)_
- `job_id`: integer _(fk)_
- `filename`: string
- `file_path`: string
- `mime_type`: string
- `uploaded_at`: timestamp
- `status`: string _(default)_
- `print_on_jobsheet`: boolean _(default)_
- _relations_: job: one(Job)

### JobQuoteChat

pk: `id` (uuid) · fk: job_id

- `id`: uuid _(pk, default)_
- `job_id`: integer _(fk)_
- `message_id`: string _(unique)_
- `role`: string
- `content`: string
- `timestamp`: timestamp
- `metadata`: json _(default)_
- _relations_: job: one(Job)

### QuoteSpreadsheet

pk: `id` (uuid) · fk: job_id

- `id`: uuid _(pk, default)_
- `sheet_id`: string
- `sheet_url`: string _(nullable)_
- `tab`: string _(nullable, default)_
- `job_id`: integer _(fk)_
- _relations_: job: one(Job)

### AllocationBlock

pk: `id` (uuid) · fk: scheduler_run_id, job_id, staff_id

- `id`: uuid _(pk, default)_
- `scheduler_run_id`: integer _(fk)_
- `job_id`: integer _(fk)_
- `staff_id`: integer _(fk)_
- `allocation_date`: date
- `allocated_hours`: float
- `sequence`: integer _(default)_
- _relations_: scheduler_run: one(SchedulerRun), job: one(Job), staff: one(Staff)

### JobProjection

pk: `id` (uuid) · fk: scheduler_run_id, job_id

- `id`: uuid _(pk, default)_
- `scheduler_run_id`: integer _(fk)_
- `job_id`: integer _(fk)_
- `anticipated_start_date`: date _(nullable)_
- `anticipated_end_date`: date _(nullable)_
- `remaining_hours`: float
- `is_late`: boolean _(default)_
- `is_unscheduled`: boolean _(default)_
- `unscheduled_reason`: string _(nullable)_
- _relations_: scheduler_run: one(SchedulerRun), job: one(Job)

### SchedulerRun

pk: `id` (uuid)

- `id`: uuid _(pk, default)_
- `ran_at`: timestamp _(default)_
- `algorithm_version`: string _(default)_
- `succeeded`: boolean _(default)_
- `failure_reason`: string _(nullable)_
- `job_count`: integer _(default)_
- `unscheduled_count`: integer _(default)_

### Form

pk: `id` (uuid)

- `id`: uuid _(pk, default)_
- `document_type`: string
- `title`: string
- `document_number`: string _(nullable)_
- `tags`: json _(default)_
- `status`: string _(default)_
- `form_schema`: json _(default)_

### FormEntry

pk: `id` (uuid) · fk: form_id, job_id, staff_id, entered_by_id

- `id`: uuid _(pk, default)_
- `form_id`: integer _(fk)_
- `job_id`: integer _(fk)_
- `entry_date`: date
- `staff_id`: integer _(fk)_
- `entered_by_id`: integer _(fk)_
- `data`: json _(default)_
- `is_active`: boolean _(default)_
- _relations_: form: one(Form), job: one(Job), staff: one(Staff), entered_by: one(Staff)

### Procedure

pk: `id` (uuid) · fk: job_id

- `id`: uuid _(pk, default)_
- `document_type`: string
- `title`: string
- `document_number`: string _(nullable)_
- `site_location`: string
- `tags`: json _(default)_
- `status`: string _(default)_
- `job_id`: integer _(fk)_
- `google_doc_id`: string
- `google_doc_url`: string
- _relations_: job: one(Job)

### PurchaseOrder

pk: `id` (uuid) · fk: supplier_id, pickup_address_id, job_id, created_by_id

- `id`: uuid _(pk, default)_
- `supplier_id`: integer _(fk)_
- `pickup_address_id`: integer _(fk)_
- `job_id`: integer _(fk)_
- `created_by_id`: integer _(fk)_
- `po_number`: string _(unique)_
- `reference`: string _(nullable)_
- `order_date`: date _(default)_
- `expected_delivery`: date _(nullable)_
- `xero_id`: uuid _(unique, nullable)_
- `xero_tenant_id`: string _(nullable)_
- `status`: string _(default)_
- `xero_last_modified`: timestamp _(nullable)_
- `xero_last_synced`: timestamp _(nullable, default)_
- `online_url`: string _(nullable)_
- `raw_json`: json _(nullable)_
- _relations_: supplier: one(Client), pickup_address: one(SupplierPickupAddress), job: one(Job), created_by: one(Staff)

### PurchaseOrderLine

pk: `id` (uuid) · fk: purchase_order_id, job_id

- `id`: uuid _(pk, default)_
- `purchase_order_id`: integer _(fk)_
- `job_id`: integer _(fk)_
- `description`: string
- `quantity`: decimal
- `dimensions`: string _(nullable)_
- `unit_cost`: decimal _(nullable)_
- `price_tbc`: boolean _(default)_
- `supplier_item_code`: string _(nullable)_
- `item_code`: string _(nullable)_
- `received_quantity`: decimal _(default)_
- `metal_type`: string _(default, nullable)_
- `alloy`: string _(nullable)_
- `specifics`: string _(nullable)_
- `location`: string _(nullable)_
- `raw_line_data`: json _(nullable)_
- `xero_line_item_id`: uuid _(nullable)_
- _relations_: purchase_order: one(PurchaseOrder), job: one(Job)

### PurchaseOrderSupplierQuote

pk: `id` (uuid) · fk: purchase_order_id

- `id`: uuid _(pk, default)_
- `purchase_order_id`: integer _(fk)_
- `filename`: string
- `file_path`: string
- `mime_type`: string
- `uploaded_at`: timestamp
- `extracted_data`: json _(nullable)_
- `status`: string _(default)_
- _relations_: purchase_order: one(PurchaseOrder)

### Stock

pk: `id` (uuid) · fk: job_id, source_purchase_order_line_id, source_parent_stock_id

- `id`: uuid _(pk, default)_
- `job_id`: integer _(fk)_
- `item_code`: string _(nullable, unique)_
- `description`: string
- `quantity`: decimal
- `unit_cost`: decimal
- `unit_revenue`: decimal _(nullable)_
- `date`: timestamp _(default)_
- `source`: string
- `source_purchase_order_line_id`: integer _(fk)_
- `active_source_purchase_order_line_id`: uuid _(nullable)_
- `source_parent_stock_id`: integer _(fk)_
- `location`: string
- `metal_type`: string _(default)_
- `alloy`: string _(nullable)_
- `specifics`: string _(nullable)_
- `is_active`: boolean _(default)_
- `xero_id`: string _(unique, nullable)_
- `xero_last_modified`: timestamp _(nullable)_
- `xero_last_synced`: timestamp _(nullable)_
- `raw_json`: json _(nullable)_
- `xero_inventory_tracked`: boolean _(default)_
- `parsed_at`: timestamp _(nullable)_
- `parser_version`: string _(nullable)_
- `parser_confidence`: decimal _(nullable)_
- _relations_: job: one(Job), source_purchase_order_line: one(PurchaseOrderLine), source_parent_stock: one(self)

### PurchaseOrderEvent

pk: `id` (uuid) · fk: purchase_order_id, staff_id

- `id`: uuid _(pk, default)_
- `purchase_order_id`: integer _(fk)_
- `timestamp`: timestamp _(default)_
- `staff_id`: integer _(fk)_
- `description`: string
- _relations_: purchase_order: one(PurchaseOrder), staff: one(Staff)

### SupplierProduct

pk: `id` (uuid) · fk: supplier_id, price_list_id

- `id`: uuid _(pk, default)_
- `supplier_id`: integer _(fk)_
- `price_list_id`: integer _(fk)_
- `product_name`: string
- `item_no`: string
- `description`: string _(nullable)_
- `specifications`: string _(nullable)_
- `variant_id`: string
- `variant_width`: string _(nullable)_
- `variant_length`: string _(nullable)_
- `variant_price`: decimal _(nullable)_
- `price_unit`: string _(nullable)_
- `variant_available_stock`: integer _(nullable)_
- `url`: string
- `is_discontinued`: boolean _(default)_
- `last_scraped`: timestamp
- `parsed_item_code`: string _(nullable)_
- `parsed_description`: string _(nullable)_
- `parsed_metal_type`: string _(nullable)_
- `parsed_alloy`: string _(nullable)_
- `parsed_specifics`: string _(nullable)_
- `parsed_dimensions`: string _(nullable)_
- `parsed_unit_cost`: decimal _(nullable)_
- `parsed_price_unit`: string _(nullable)_
- `parsed_at`: timestamp _(nullable)_
- `parser_version`: string _(nullable)_
- `parser_confidence`: decimal _(nullable)_
- `mapping_hash`: string _(nullable)_
- _relations_: supplier: one(Client), price_list: one(SupplierPriceList)

### SupplierPriceList

pk: `id` (uuid) · fk: supplier_id

- `id`: uuid _(pk, default)_
- `supplier_id`: integer _(fk)_
- `file_name`: string
- `uploaded_at`: timestamp
- _relations_: supplier: one(Client)

### ScrapeJob

pk: `id` (uuid) · fk: supplier_id

- `id`: uuid _(pk, default)_
- `supplier_id`: integer _(fk)_
- `status`: string _(default)_
- `started_at`: timestamp _(default)_
- `completed_at`: timestamp _(nullable)_
- `products_scraped`: integer _(default)_
- `products_failed`: integer _(default)_
- `error_message`: string _(nullable)_
- _relations_: supplier: one(Client)

### ProductParsingMapping

pk: `id` (uuid) · fk: validated_by_id

- `id`: uuid _(pk, default)_
- `input_hash`: string _(unique)_
- `input_data`: json
- `derived_key`: string _(nullable)_
- `mapped_item_code`: string _(nullable)_
- `mapped_description`: string _(nullable)_
- `mapped_metal_type`: string _(nullable)_
- `mapped_alloy`: string _(nullable)_
- `mapped_specifics`: string _(nullable)_
- `mapped_dimensions`: string _(nullable)_
- `mapped_unit_cost`: decimal _(nullable)_
- `mapped_price_unit`: string _(nullable)_
- `parser_version`: string _(nullable)_
- `parser_confidence`: decimal _(nullable)_
- `llm_response`: json _(nullable)_
- `is_validated`: boolean _(default)_
- `validated_by_id`: integer _(fk)_
- `validated_at`: timestamp _(nullable)_
- `validation_notes`: string _(nullable)_
- `item_code_is_in_xero`: boolean _(default)_
- _relations_: validated_by: one(Staff)

### AIProvider

- `name`: string
- `api_key`: string _(nullable)_
- `default`: boolean _(default)_
- `model_name`: string
- `provider_type`: string

### AppError

pk: `id` (uuid) · fk: resolved_by_id

- `id`: uuid _(pk, default)_
- `timestamp`: timestamp
- `message`: string
- `data`: json _(nullable)_
- `app`: string _(nullable)_
- `file`: string _(nullable)_
- `function`: string _(nullable)_
- `severity`: integer _(default)_
- `job_id`: uuid _(nullable)_
- `user_id`: uuid _(nullable)_
- `resolved`: boolean _(default)_
- `resolved_by_id`: integer _(fk)_
- `resolved_timestamp`: timestamp _(nullable)_
- _relations_: resolved_by: one(Staff)

### XeroError

- `entity`: string
- `reference_id`: string
- `kind`: string

### CacheState

pk: `id` (integer)

- `id`: integer _(pk, default)_
- `disabled_until`: timestamp _(nullable)_

### ServiceAPIKey

pk: `id` (uuid)

- `id`: uuid _(pk, default)_
- `name`: string
- `key`: string _(unique)_
- `is_active`: boolean _(default)_
- `last_used`: timestamp _(nullable)_

### XeroAccount

pk: `id` (uuid)

- `id`: uuid _(pk, default)_
- `xero_id`: uuid _(unique)_
- `xero_tenant_id`: string _(nullable)_
- `account_code`: string _(nullable)_
- `account_name`: string _(unique)_
- `description`: string _(nullable)_
- `account_type`: string _(nullable)_
- `tax_type`: string _(nullable)_
- `enable_payments`: boolean _(default)_
- `xero_last_modified`: timestamp
- `xero_last_synced`: timestamp _(nullable, default)_
- `raw_json`: json
- `django_created_at`: timestamp
- `django_updated_at`: timestamp

### XeroApp

pk: `id` (uuid)

- `id`: uuid _(pk, default)_
- `label`: string
- `client_id`: string _(unique)_
- `client_secret`: string
- `redirect_uri`: string
- `is_active`: boolean _(default)_
- `tenant_id`: string _(nullable)_
- `token_type`: string _(nullable)_
- `access_token`: string _(nullable)_
- `refresh_token`: string _(nullable)_
- `expires_at`: timestamp _(nullable)_
- `scope`: string _(nullable)_
- `day_remaining`: integer _(nullable)_
- `minute_remaining`: integer _(nullable)_
- `snapshot_at`: timestamp _(nullable)_
- `last_429_at`: timestamp _(nullable)_

### XeroJournal

pk: `id` (uuid)

- `id`: uuid _(pk, default)_
- `xero_id`: uuid _(unique)_
- `xero_tenant_id`: string _(nullable)_
- `journal_date`: date
- `created_date_utc`: timestamp
- `journal_number`: integer _(unique)_
- `reference`: string _(nullable)_
- `source_id`: uuid _(nullable)_
- `source_type`: string _(nullable)_
- `raw_json`: json
- `xero_last_modified`: timestamp
- `django_created_at`: timestamp
- `django_updated_at`: timestamp
- `xero_last_synced`: timestamp _(nullable, default)_

### XeroJournalLineItem

pk: `id` (uuid) · fk: journal_id, account_id

- `id`: uuid _(pk, default)_
- `journal_id`: integer _(fk)_
- `xero_line_id`: uuid _(unique)_
- `account_id`: integer _(fk)_
- `description`: string _(nullable)_
- `net_amount`: decimal
- `gross_amount`: decimal
- `tax_amount`: decimal
- `tax_type`: string _(nullable)_
- `tax_name`: string _(nullable)_
- `raw_json`: json
- `django_created_at`: timestamp
- `django_updated_at`: timestamp
- _relations_: journal: one(XeroJournal), account: one(XeroAccount)

### XeroPayItem

pk: `id` (uuid)

- `id`: uuid _(pk, default)_
- `xero_id`: string _(unique, nullable)_
- `xero_tenant_id`: string _(nullable)_
- `name`: string
- `uses_leave_api`: boolean
- `multiplier`: decimal _(nullable)_
- `xero_last_modified`: timestamp _(nullable)_
- `xero_last_synced`: timestamp _(nullable, default)_

### XeroPayRun

pk: `id` (uuid)

- `id`: uuid _(pk, default)_
- `xero_id`: uuid _(unique)_
- `xero_tenant_id`: string
- `payroll_calendar_id`: uuid _(nullable)_
- `period_start_date`: date
- `period_end_date`: date
- `payment_date`: date
- `pay_run_status`: string _(nullable)_
- `pay_run_type`: string _(nullable)_
- `total_cost`: decimal _(nullable)_
- `total_pay`: decimal _(nullable)_
- `raw_json`: json
- `xero_last_modified`: timestamp
- `xero_last_synced`: timestamp _(nullable, default)_
- `django_created_at`: timestamp
- `django_updated_at`: timestamp

### XeroPaySlip

pk: `id` (uuid) · fk: pay_run_id

- `id`: uuid _(pk, default)_
- `xero_id`: uuid _(unique)_
- `xero_tenant_id`: string
- `pay_run_id`: integer _(fk)_
- `xero_employee_id`: uuid
- `employee_name`: string _(nullable)_
- `gross_earnings`: decimal _(default)_
- `tax_amount`: decimal _(default)_
- `net_pay`: decimal _(default)_
- `timesheet_hours`: decimal _(default)_
- `leave_hours`: decimal _(default)_
- `raw_json`: json
- `xero_last_modified`: timestamp
- `xero_last_synced`: timestamp _(nullable, default)_
- `django_created_at`: timestamp
- `django_updated_at`: timestamp
- _relations_: pay_run: one(XeroPayRun)

### XeroSyncCursor

- `entity_key`: string _(unique)_
- `last_modified`: timestamp

### XeroToken

- `tenant_id`: string _(unique)_
- `token_type`: string
- `access_token`: string
- `refresh_token`: string
- `expires_at`: timestamp
- `scope`: string _(default)_

## Schema Source Files

Read and edit these files when adding columns, creating migrations, or changing relations:

- `frontend/tests/scripts/db-backup-utils.ts` — imported by **4** files
- `/models.py` — imported by **3** files

---
_Back to [overview.md](./overview.md)_