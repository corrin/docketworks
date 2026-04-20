# Schema

### Invoice
- job_id: integer (fk)
- online_url: string (nullable)
- _relations_: job: one(Job)

### InvoiceLineItem
- invoice_id: integer (fk)
- _relations_: invoice: one(Invoice)

### BillLineItem
- bill_id: integer (fk)
- _relations_: bill: one(Bill)

### CreditNoteLineItem
- credit_note_id: integer (fk)
- _relations_: credit_note: one(CreditNote)

### Quote
- id: uuid (pk, default)
- xero_id: uuid (unique)
- xero_tenant_id: string (nullable)
- job_id: integer (fk)
- client_id: integer (fk)
- date: date
- status: string (default)
- total_excl_tax: decimal
- total_incl_tax: decimal
- xero_last_modified: timestamp (nullable)
- xero_last_synced: timestamp (default)
- number: string (nullable)
- online_url: string (nullable)
- raw_json: json (nullable)
- _relations_: job: one(Job), client: one(Client)

### Client
- id: uuid (pk, default)
- xero_contact_id: string (unique, nullable)
- xero_tenant_id: string (nullable)
- name: string
- email: string (nullable)
- phone: string (nullable)
- address: string (nullable)
- is_account_customer: boolean (default)
- is_supplier: boolean (default)
- allow_jobs: boolean (default)
- xero_last_modified: timestamp
- raw_json: json (nullable)
- primary_contact_name: string (nullable)
- primary_contact_email: string (nullable)
- additional_contact_persons: json (nullable, default)
- all_phones: json (nullable, default)
- django_created_at: timestamp
- django_updated_at: timestamp
- xero_last_synced: timestamp (nullable, default)
- xero_archived: boolean (default)
- xero_merged_into_id: string (nullable)
- merged_into_id: integer (fk)
- _relations_: merged_into: one(self)

### ClientContact
- id: uuid (pk, default)
- client_id: integer (fk)
- name: string
- email: string (nullable)
- phone: string (nullable)
- position: string (nullable)
- is_primary: boolean (default)
- notes: string (nullable)
- is_active: boolean (default)
- _relations_: client: one(Client)

### SupplierPickupAddress
- id: uuid (pk, default)
- client_id: integer (fk)
- name: string
- street: string
- suburb: string (nullable)
- city: string
- state: string (nullable)
- postal_code: string (nullable)
- country: string (default)
- google_place_id: string (nullable)
- latitude: decimal (nullable)
- longitude: decimal (nullable)
- is_primary: boolean (default)
- notes: string (nullable)
- is_active: boolean (default)
- _relations_: client: one(Client)

### CostSet
- id: uuid (pk, default)
- job_id: integer (fk)
- kind: string
- rev: integer
- summary: json (default)
- created: timestamp
- _relations_: job: one(Job)

### CostLine
- id: uuid (pk, default)
- cost_set_id: integer (fk)
- kind: string
- desc: string
- quantity: decimal (default)
- unit_cost: decimal (default)
- unit_rev: decimal (default)
- ext_refs: json (default)
- meta: json (default)
- accounting_date: date
- xero_time_id: string (nullable)
- xero_expense_id: string (nullable)
- xero_last_modified: timestamp (nullable)
- xero_last_synced: timestamp (nullable, default)
- approved: boolean (default)
- xero_pay_item_id: integer (fk)
- _relations_: cost_set: one(CostSet), xero_pay_item: one(XeroPayItem)

### Job
- id: uuid (pk, default)
- name: string
- client_id: integer (fk)
- order_number: string (nullable)
- contact_id: integer (fk)
- job_number: integer (unique)
- description: string (nullable)
- delivery_date: date (nullable)
- completed_at: timestamp (nullable)
- rdti_type: string (nullable)
- pricing_methodology: string (default)
- price_cap: decimal (nullable)
- speed_quality_tradeoff: string (default)
- job_is_valid: boolean (default)
- charge_out_rate: decimal
- complex_job: boolean (default)
- notes: string (nullable)
- created_by_id: integer (fk)
- latest_estimate_id: integer (fk)
- latest_quote_id: integer (fk)
- latest_actual_id: integer (fk)
- priority: float (default)
- min_people: integer (default)
- max_people: integer (default)
- xero_project_id: string (unique, nullable)
- xero_default_task_id: string (nullable)
- xero_last_modified: timestamp (nullable)
- xero_last_synced: timestamp (nullable, default)
- default_xero_pay_item_id: integer (fk)
- _relations_: client: one(Client), contact: one(ClientContact), created_by: one(Staff), people: many(Staff), latest_estimate: one(CostSet), latest_quote: one(CostSet), latest_actual: one(CostSet), default_xero_pay_item: one(XeroPayItem)

### JobDeltaRejection
- id: uuid (pk, default)
- job_id: integer (fk)
- staff_id: integer (fk)
- change_id: uuid (nullable)
- reason: string
- detail: string
- envelope: json
- checksum: string
- request_etag: string
- request_ip: string (nullable)
- resolved: boolean (default)
- resolved_by_id: integer (fk)
- resolved_timestamp: timestamp (nullable)
- _relations_: job: one(Job), staff: one(Staff), resolved_by: one(Staff)

### JobEvent
- id: uuid (pk, default)
- job_id: integer (fk)
- timestamp: timestamp (default)
- staff_id: integer (fk)
- event_type: string (default)
- description: string
- schema_version: integer (default)
- change_id: uuid (nullable)
- delta_before: json (nullable)
- delta_after: json (nullable)
- delta_meta: json (nullable)
- delta_checksum: string (default)
- dedup_hash: string (nullable)
- _relations_: job: one(Job), staff: one(Staff)

### JobFile
- id: uuid (pk, default)
- job_id: integer (fk)
- filename: string
- file_path: string
- mime_type: string
- uploaded_at: timestamp
- status: string (default)
- print_on_jobsheet: boolean (default)
- _relations_: job: one(Job)

### JobQuoteChat
- id: uuid (pk, default)
- job_id: integer (fk)
- message_id: string (unique)
- role: string
- content: string
- timestamp: timestamp
- metadata: json (default)
- _relations_: job: one(Job)

### QuoteSpreadsheet
- id: uuid (pk, default)
- sheet_id: string
- sheet_url: string (nullable)
- tab: string (nullable, default)
- job_id: integer (fk)
- _relations_: job: one(Job)

### AllocationBlock
- id: uuid (pk, default)
- scheduler_run_id: integer (fk)
- job_id: integer (fk)
- staff_id: integer (fk)
- allocation_date: date
- allocated_hours: float
- sequence: integer (default)
- _relations_: scheduler_run: one(SchedulerRun), job: one(Job), staff: one(Staff)

### JobProjection
- id: uuid (pk, default)
- scheduler_run_id: integer (fk)
- job_id: integer (fk)
- anticipated_start_date: date (nullable)
- anticipated_end_date: date (nullable)
- remaining_hours: float
- is_late: boolean (default)
- is_unscheduled: boolean (default)
- unscheduled_reason: string (nullable)
- _relations_: scheduler_run: one(SchedulerRun), job: one(Job)

### SchedulerRun
- id: uuid (pk, default)
- ran_at: timestamp (default)
- algorithm_version: string (default)
- succeeded: boolean (default)
- failure_reason: string (nullable)
- job_count: integer (default)
- unscheduled_count: integer (default)

### Form
- id: uuid (pk, default)
- document_type: string
- title: string
- document_number: string (nullable)
- tags: json (default)
- status: string (default)
- form_schema: json (default)

### FormEntry
- id: uuid (pk, default)
- form_id: integer (fk)
- job_id: integer (fk)
- entry_date: date
- staff_id: integer (fk)
- entered_by_id: integer (fk)
- data: json (default)
- is_active: boolean (default)
- _relations_: form: one(Form), job: one(Job), staff: one(Staff), entered_by: one(Staff)

### Procedure
- id: uuid (pk, default)
- document_type: string
- title: string
- document_number: string (nullable)
- site_location: string
- tags: json (default)
- status: string (default)
- job_id: integer (fk)
- google_doc_id: string
- google_doc_url: string
- _relations_: job: one(Job)

### PurchaseOrder
- id: uuid (pk, default)
- supplier_id: integer (fk)
- pickup_address_id: integer (fk)
- job_id: integer (fk)
- created_by_id: integer (fk)
- po_number: string (unique)
- reference: string (nullable)
- order_date: date (default)
- expected_delivery: date (nullable)
- xero_id: uuid (unique, nullable)
- xero_tenant_id: string (nullable)
- status: string (default)
- xero_last_modified: timestamp (nullable)
- xero_last_synced: timestamp (nullable, default)
- online_url: string (nullable)
- raw_json: json (nullable)
- _relations_: supplier: one(Client), pickup_address: one(SupplierPickupAddress), job: one(Job), created_by: one(Staff)

### PurchaseOrderLine
- id: uuid (pk, default)
- purchase_order_id: integer (fk)
- job_id: integer (fk)
- description: string
- quantity: decimal
- dimensions: string (nullable)
- unit_cost: decimal (nullable)
- price_tbc: boolean (default)
- supplier_item_code: string (nullable)
- item_code: string (nullable)
- received_quantity: decimal (default)
- metal_type: string (default, nullable)
- alloy: string (nullable)
- specifics: string (nullable)
- location: string (nullable)
- raw_line_data: json (nullable)
- xero_line_item_id: uuid (nullable)
- _relations_: purchase_order: one(PurchaseOrder), job: one(Job)

### PurchaseOrderSupplierQuote
- id: uuid (pk, default)
- purchase_order_id: integer (fk)
- filename: string
- file_path: string
- mime_type: string
- uploaded_at: timestamp
- extracted_data: json (nullable)
- status: string (default)
- _relations_: purchase_order: one(PurchaseOrder)

### Stock
- id: uuid (pk, default)
- job_id: integer (fk)
- item_code: string (nullable, unique)
- description: string
- quantity: decimal
- unit_cost: decimal
- unit_revenue: decimal (nullable)
- date: timestamp (default)
- source: string
- source_purchase_order_line_id: integer (fk)
- active_source_purchase_order_line_id: uuid (nullable)
- source_parent_stock_id: integer (fk)
- location: string
- metal_type: string (default)
- alloy: string (nullable)
- specifics: string (nullable)
- is_active: boolean (default)
- xero_id: string (unique, nullable)
- xero_last_modified: timestamp (nullable)
- xero_last_synced: timestamp (nullable)
- raw_json: json (nullable)
- xero_inventory_tracked: boolean (default)
- parsed_at: timestamp (nullable)
- parser_version: string (nullable)
- parser_confidence: decimal (nullable)
- _relations_: job: one(Job), source_purchase_order_line: one(PurchaseOrderLine), source_parent_stock: one(self)

### PurchaseOrderEvent
- id: uuid (pk, default)
- purchase_order_id: integer (fk)
- timestamp: timestamp (default)
- staff_id: integer (fk)
- description: string
- _relations_: purchase_order: one(PurchaseOrder), staff: one(Staff)

### SupplierProduct
- id: uuid (pk, default)
- supplier_id: integer (fk)
- price_list_id: integer (fk)
- product_name: string
- item_no: string
- description: string (nullable)
- specifications: string (nullable)
- variant_id: string
- variant_width: string (nullable)
- variant_length: string (nullable)
- variant_price: decimal (nullable)
- price_unit: string (nullable)
- variant_available_stock: integer (nullable)
- url: string
- is_discontinued: boolean (default)
- last_scraped: timestamp
- parsed_item_code: string (nullable)
- parsed_description: string (nullable)
- parsed_metal_type: string (nullable)
- parsed_alloy: string (nullable)
- parsed_specifics: string (nullable)
- parsed_dimensions: string (nullable)
- parsed_unit_cost: decimal (nullable)
- parsed_price_unit: string (nullable)
- parsed_at: timestamp (nullable)
- parser_version: string (nullable)
- parser_confidence: decimal (nullable)
- mapping_hash: string (nullable)
- _relations_: supplier: one(Client), price_list: one(SupplierPriceList)

### SupplierPriceList
- id: uuid (pk, default)
- supplier_id: integer (fk)
- file_name: string
- uploaded_at: timestamp
- _relations_: supplier: one(Client)

### ScrapeJob
- id: uuid (pk, default)
- supplier_id: integer (fk)
- status: string (default)
- started_at: timestamp (default)
- completed_at: timestamp (nullable)
- products_scraped: integer (default)
- products_failed: integer (default)
- error_message: string (nullable)
- _relations_: supplier: one(Client)

### ProductParsingMapping
- id: uuid (pk, default)
- input_hash: string (unique)
- input_data: json
- derived_key: string (nullable)
- mapped_item_code: string (nullable)
- mapped_description: string (nullable)
- mapped_metal_type: string (nullable)
- mapped_alloy: string (nullable)
- mapped_specifics: string (nullable)
- mapped_dimensions: string (nullable)
- mapped_unit_cost: decimal (nullable)
- mapped_price_unit: string (nullable)
- parser_version: string (nullable)
- parser_confidence: decimal (nullable)
- llm_response: json (nullable)
- is_validated: boolean (default)
- validated_by_id: integer (fk)
- validated_at: timestamp (nullable)
- validation_notes: string (nullable)
- item_code_is_in_xero: boolean (default)
- _relations_: validated_by: one(Staff)

### AIProvider
- name: string
- api_key: string (nullable)
- default: boolean (default)
- model_name: string
- provider_type: string

### AppError
- id: uuid (pk, default)
- timestamp: timestamp
- message: string
- data: json (nullable)
- app: string (nullable)
- file: string (nullable)
- function: string (nullable)
- severity: integer (default)
- job_id: uuid (nullable)
- user_id: uuid (nullable)
- resolved: boolean (default)
- resolved_by_id: integer (fk)
- resolved_timestamp: timestamp (nullable)
- _relations_: resolved_by: one(Staff)

### XeroError
- entity: string
- reference_id: string
- kind: string

### ServiceAPIKey
- id: uuid (pk, default)
- name: string
- key: string (unique)
- is_active: boolean (default)
- last_used: timestamp (nullable)

### XeroAccount
- id: uuid (pk, default)
- xero_id: uuid (unique)
- xero_tenant_id: string (nullable)
- account_code: string (nullable)
- account_name: string (unique)
- description: string (nullable)
- account_type: string (nullable)
- tax_type: string (nullable)
- enable_payments: boolean (default)
- xero_last_modified: timestamp
- xero_last_synced: timestamp (nullable, default)
- raw_json: json
- django_created_at: timestamp
- django_updated_at: timestamp

### XeroJournal
- id: uuid (pk, default)
- xero_id: uuid (unique)
- xero_tenant_id: string (nullable)
- journal_date: date
- created_date_utc: timestamp
- journal_number: integer (unique)
- reference: string (nullable)
- source_id: uuid (nullable)
- source_type: string (nullable)
- raw_json: json
- xero_last_modified: timestamp
- django_created_at: timestamp
- django_updated_at: timestamp
- xero_last_synced: timestamp (nullable, default)

### XeroJournalLineItem
- id: uuid (pk, default)
- journal_id: integer (fk)
- xero_line_id: uuid (unique)
- account_id: integer (fk)
- description: string (nullable)
- net_amount: decimal
- gross_amount: decimal
- tax_amount: decimal
- tax_type: string (nullable)
- tax_name: string (nullable)
- raw_json: json
- django_created_at: timestamp
- django_updated_at: timestamp
- _relations_: journal: one(XeroJournal), account: one(XeroAccount)

### XeroPayItem
- id: uuid (pk, default)
- xero_id: string (unique, nullable)
- xero_tenant_id: string (nullable)
- name: string
- uses_leave_api: boolean
- multiplier: decimal (nullable)
- xero_last_modified: timestamp (nullable)
- xero_last_synced: timestamp (nullable, default)

### XeroPayRun
- id: uuid (pk, default)
- xero_id: uuid (unique)
- xero_tenant_id: string
- payroll_calendar_id: uuid (nullable)
- period_start_date: date
- period_end_date: date
- payment_date: date
- pay_run_status: string (nullable)
- pay_run_type: string (nullable)
- total_cost: decimal (nullable)
- total_pay: decimal (nullable)
- raw_json: json
- xero_last_modified: timestamp
- xero_last_synced: timestamp (nullable, default)
- django_created_at: timestamp
- django_updated_at: timestamp

### XeroPaySlip
- id: uuid (pk, default)
- xero_id: uuid (unique)
- xero_tenant_id: string
- pay_run_id: integer (fk)
- xero_employee_id: uuid
- employee_name: string (nullable)
- gross_earnings: decimal (default)
- tax_amount: decimal (default)
- net_pay: decimal (default)
- timesheet_hours: decimal (default)
- leave_hours: decimal (default)
- raw_json: json
- xero_last_modified: timestamp
- xero_last_synced: timestamp (nullable, default)
- django_created_at: timestamp
- django_updated_at: timestamp
- _relations_: pay_run: one(XeroPayRun)

### XeroSyncCursor
- entity_key: string (unique)
- last_modified: timestamp

### XeroToken
- tenant_id: string (unique)
- token_type: string
- access_token: string
- refresh_token: string
- expires_at: timestamp
- scope: string (default)
