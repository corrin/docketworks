# frontend-jobs-manager — AI Context Map

> **Stack:** raw-http | none | vue | typescript

> 0 routes | 61 models | 181 components | 101 lib files | 15 env vars | 3 middleware | 7 events | 100% test coverage
> **Token savings:** this file is ~18,600 tokens. Without it, AI exploration would cost ~122,100 tokens. **Saves ~103,500 tokens per conversation.**

---

# Schema

### accounting_bill
- id: uuid (required)
- xero_id: uuid (required, fk)
- number: varchar (required)
- date: date (required)
- due_date: date
- status: varchar (required)
- total_excl_tax: numeric(10
- amount_due: numeric(10
- xero_last_modified: timestamp with time zone (required)
- raw_json: jsonb (required)
- client_id: uuid (required, fk)
- django_created_at: timestamp with time zone (required)
- django_updated_at: timestamp with time zone (required)
- tax: numeric(10
- total_incl_tax: numeric(10
- xero_last_synced: timestamp with time zone
- xero_tenant_id: character varying(255 (fk)

### accounting_billlineitem
- id: uuid (required)
- xero_line_id: uuid (required, fk)
- description: text (required)
- quantity: numeric(10
- unit_price: numeric(10
- line_amount_excl_tax: numeric(10
- line_amount_incl_tax: numeric(10
- tax_amount: numeric(10
- account_id: uuid (fk)
- bill_id: uuid (required, fk)

### accounting_creditnote
- id: uuid (required)
- xero_id: uuid (required, fk)
- xero_tenant_id: varchar (fk)
- number: varchar (required)
- date: date (required)
- due_date: date
- status: varchar (required)
- total_excl_tax: numeric(10
- tax: numeric(10
- total_incl_tax: numeric(10
- amount_due: numeric(10
- xero_last_modified: timestamp with time zone (required)
- xero_last_synced: timestamp with time zone
- raw_json: jsonb (required)
- django_created_at: timestamp with time zone (required)
- django_updated_at: timestamp with time zone (required)
- client_id: uuid (required, fk)

### accounting_creditnotelineitem
- id: uuid (required)
- xero_line_id: uuid (required, fk)
- description: text (required)
- quantity: numeric(10
- unit_price: numeric(10
- line_amount_excl_tax: numeric(10
- line_amount_incl_tax: numeric(10
- tax_amount: numeric(10
- account_id: uuid (fk)
- credit_note_id: uuid (required, fk)

### accounting_invoice
- id: uuid (required)
- xero_id: uuid (required, fk)
- number: varchar (required)
- date: date (required)
- due_date: date
- status: varchar (required)
- total_excl_tax: numeric(10
- amount_due: numeric(10
- xero_last_modified: timestamp with time zone (required)
- raw_json: jsonb (required)
- client_id: uuid (required, fk)
- django_created_at: timestamp with time zone (required)
- django_updated_at: timestamp with time zone (required)
- job_id: uuid (fk)
- online_url: varchar
- tax: numeric(10
- total_incl_tax: numeric(10
- xero_last_synced: timestamp with time zone
- xero_tenant_id: character varying(255 (fk)

### accounting_invoicelineitem
- id: uuid (required)
- xero_line_id: uuid (required, fk)
- description: text (required)
- quantity: numeric(10
- unit_price: numeric(10
- line_amount_excl_tax: numeric(10
- line_amount_incl_tax: numeric(10
- tax_amount: numeric(10
- account_id: uuid (fk)
- invoice_id: uuid (required, fk)

### accounting_quote
- id: uuid (required)
- xero_id: uuid (required, fk)
- xero_tenant_id: varchar (fk)
- date: date (required)
- status: varchar (required)
- total_excl_tax: numeric(10
- total_incl_tax: numeric(10
- xero_last_modified: timestamp with time zone
- xero_last_synced: timestamp with time zone (required)
- online_url: varchar
- raw_json: jsonb
- client_id: uuid (required, fk)
- job_id: uuid (fk)
- number: character varying(255

### accounts_historicalstaff
- password: varchar (required)
- last_login: timestamp with time zone
- is_superuser: boolean (required)
- id: uuid (required)
- icon: text
- password_needs_reset: boolean (required)
- email: varchar (required)
- first_name: varchar (required)
- last_name: varchar (required)
- preferred_name: varchar
- wage_rate: numeric(10
- is_office_staff: boolean (required)
- date_joined: timestamp with time zone (required)
- hours_mon: numeric(4
- hours_tue: numeric(4
- hours_wed: numeric(4
- hours_thu: numeric(4
- hours_fri: numeric(4
- hours_sat: numeric(4
- hours_sun: numeric(4
- history_id: integer (required, fk)
- history_date: timestamp with time zone (required)
- history_change_reason: varchar
- history_type: varchar (required)
- history_user_id: uuid (fk)
- date_left: date
- xero_user_id: varchar (fk)
- base_wage_rate: numeric(10

### accounts_staff
- password: varchar (required)
- last_login: timestamp with time zone
- is_superuser: boolean (required)
- id: uuid (required)
- icon: varchar
- password_needs_reset: boolean (required)
- email: varchar (required)
- first_name: varchar (required)
- last_name: varchar (required)
- preferred_name: varchar
- wage_rate: numeric(10
- is_office_staff: boolean (required)
- date_joined: timestamp with time zone (required)
- hours_mon: numeric(4
- hours_tue: numeric(4
- hours_wed: numeric(4
- hours_thu: numeric(4
- hours_fri: numeric(4
- hours_sat: numeric(4
- hours_sun: numeric(4
- date_left: date
- xero_user_id: varchar (fk)
- base_wage_rate: numeric(10

### accounts_staff_groups
- id: bigint (required)
- staff_id: uuid (required, fk)
- group_id: integer (required, fk)

### accounts_staff_user_permissions
- id: bigint (required)
- staff_id: uuid (required, fk)
- permission_id: integer (required, fk)

### auth_group
- id: integer (required)
- name: varchar (required)

### auth_group_permissions
- id: bigint (required)
- group_id: integer (required, fk)
- permission_id: integer (required, fk)

### auth_permission
- id: integer (required)
- name: varchar (required)
- content_type_id: integer (required, fk)
- codename: varchar (required)

### client_client
- id: uuid (required)
- xero_contact_id: varchar (fk)
- name: varchar (required)
- email: varchar
- phone: varchar
- address: text
- is_account_customer: boolean (required)
- raw_json: jsonb
- django_updated_at: timestamp with time zone (required)
- django_created_at: timestamp with time zone (required)
- xero_last_modified: timestamp with time zone (required)
- primary_contact_email: varchar
- primary_contact_name: varchar
- additional_contact_persons: jsonb
- all_phones: jsonb
- xero_last_synced: timestamp with time zone
- xero_tenant_id: varchar (fk)
- merged_into_id: uuid (fk)
- xero_archived: boolean (required)
- xero_merged_into_id: varchar (fk)
- is_supplier: boolean (required)

### client_clientcontact
- id: uuid (required)
- name: varchar (required)
- email: varchar
- phone: varchar
- position: varchar
- is_primary: boolean (required)
- notes: text
- client_id: uuid (required, fk)
- is_active: boolean (required)

### client_supplierpickupaddress
- id: uuid (required)
- name: varchar (required)
- street: varchar (required)
- city: varchar (required)
- state: varchar
- postal_code: varchar
- country: varchar (required)
- is_primary: boolean (required)
- notes: text
- is_active: boolean (required)
- client_id: uuid (required, fk)
- google_place_id: varchar (fk)
- latitude: numeric(10
- longitude: numeric(10
- suburb: character varying(100

### django_apscheduler_djangojob
- id: varchar (required)
- next_run_time: timestamp with time zone
- job_state: bytes (required)

### django_apscheduler_djangojobexecution
- id: bigint (required)
- status: varchar (required)
- run_time: timestamp with time zone (required)
- duration: numeric(15
- finished: numeric(15
- exception: varchar
- traceback: text
- job_id: varchar (required, fk)

### django_content_type
- id: integer (required)
- app_label: varchar (required)
- model: varchar (required)

### django_migrations
- id: bigint (required)
- app: varchar (required)
- name: varchar (required)
- applied: timestamp with time zone (required)

### django_session
- session_key: varchar (required)
- session_data: text (required)
- expire_date: timestamp with time zone (required)

### django_site
- id: integer (required)
- domain: varchar (required)
- name: varchar (required)

### job_costline
- id: uuid (required)
- kind: varchar (required)
- desc: varchar (required)
- quantity: numeric(10
- unit_cost: numeric(10
- unit_rev: numeric(10
- ext_refs: jsonb (required)
- meta: jsonb (required)
- cost_set_id: uuid (required, fk)
- xero_expense_id: varchar (fk)
- xero_last_modified: timestamp with time zone
- xero_last_synced: timestamp with time zone
- xero_time_id: varchar (fk)
- accounting_date: date (required)
- approved: boolean (required)
- xero_pay_item_id: uuid (fk)

### job_costset
- id: uuid (required)
- kind: varchar (required)
- rev: integer (required)
- summary: jsonb (required)
- created: timestamp with time zone (required)
- job_id: uuid (required, fk)

### job_historicaljob
- name: varchar (required)
- id: uuid (required)
- order_number: varchar
- job_number: integer (required)
- description: text
- quote_acceptance_date: timestamp with time zone
- delivery_date: date
- status: varchar (required)
- job_is_valid: boolean (required)
- collected: boolean (required)
- paid: boolean (required)
- charge_out_rate: numeric(10
- pricing_methodology: varchar (required)
- complex_job: boolean (required)
- notes: text
- history_id: integer (required, fk)
- history_date: timestamp with time zone (required)
- history_change_reason: varchar
- history_type: varchar (required)
- client_id: uuid (fk)
- created_by_id: uuid (fk)
- history_user_id: uuid (fk)
- priority: float8 (required)
- contact_id: uuid (fk)
- latest_actual_id: uuid (fk)
- latest_estimate_id: uuid (fk)
- latest_quote_id: uuid (fk)
- rejected_flag: boolean (required)
- xero_last_modified: timestamp with time zone
- xero_last_synced: timestamp with time zone
- xero_project_id: varchar (fk)
- fully_invoiced: boolean (required)
- xero_default_task_id: varchar (fk)
- speed_quality_tradeoff: varchar (required)
- price_cap: numeric(10
- default_xero_pay_item_id: character (fk)
- completed_at: timestamp with time zone
- rdti_type: character varying(20

### job_job
- name: varchar (required)
- id: uuid (required)
- order_number: varchar
- job_number: integer (required)
- description: text
- quote_acceptance_date: timestamp with time zone
- delivery_date: date
- status: varchar (required)
- job_is_valid: boolean (required)
- collected: boolean (required)
- paid: boolean (required)
- charge_out_rate: numeric(10
- pricing_methodology: varchar (required)
- complex_job: boolean (required)
- notes: text
- client_id: uuid (fk)
- created_by_id: uuid (fk)
- priority: float8 (required)
- contact_id: uuid (fk)
- latest_actual_id: uuid (fk)
- latest_estimate_id: uuid (fk)
- latest_quote_id: uuid (fk)
- rejected_flag: boolean (required)
- xero_last_modified: timestamp with time zone
- xero_last_synced: timestamp with time zone
- xero_project_id: varchar (fk)
- fully_invoiced: boolean (required)
- xero_default_task_id: varchar (fk)
- speed_quality_tradeoff: varchar (required)
- price_cap: numeric(10
- default_xero_pay_item_id: uuid (required, fk)
- completed_at: timestamp with time zone
- rdti_type: character varying(20

### job_job_people
- id: bigint (required)
- job_id: uuid (required, fk)
- staff_id: uuid (required, fk)

### job_jobdeltarejection
- id: uuid (required)
- change_id: uuid (fk)
- reason: varchar (required)
- detail: text (required)
- envelope: jsonb (required)
- request_etag: varchar (required)
- request_ip: inet
- job_id: uuid (fk)
- staff_id: uuid (fk)

### job_jobevent
- timestamp: timestamp with time zone (required)
- event_type: varchar (required)
- description: text (required)
- job_id: uuid (fk)
- staff_id: uuid (fk)
- id: uuid (required)
- dedup_hash: varchar
- schema_version: smallint (required)
- change_id: uuid (fk)
- delta_before: jsonb
- delta_after: jsonb
- delta_meta: jsonb
- delta_checksum: varchar (required)

### job_jobfile
- id: uuid (required)
- filename: varchar (required)
- file_path: varchar (required)
- mime_type: varchar (required)
- uploaded_at: timestamp with time zone (required)
- status: varchar (required)
- print_on_jobsheet: boolean (required)
- job_id: uuid (required, fk)

### job_jobquotechat
- id: uuid (required)
- message_id: varchar (required, fk)
- role: varchar (required)
- content: text (required)
- timestamp: timestamp with time zone (required)
- metadata: jsonb (required)
- job_id: uuid (required, fk)

### job_quotespreadsheet
- id: uuid (required)
- sheet_id: varchar (required, fk)
- sheet_url: varchar
- tab: varchar
- job_id: uuid (fk)

### process_form
- id: uuid (required)
- document_type: varchar (required)
- title: varchar (required)
- document_number: varchar
- tags: jsonb (required)
- status: varchar (required)
- form_schema: jsonb (required)

### process_formentry
- id: uuid (required)
- entry_date: date (required)
- data: jsonb (required)
- is_active: boolean (required)
- entered_by_id: uuid (fk)
- form_id: uuid (required, fk)
- job_id: uuid (fk)
- staff_id: uuid (fk)

### process_historicalform
- id: uuid (required)
- document_type: varchar (required)
- title: varchar (required)
- document_number: varchar
- tags: jsonb (required)
- status: varchar (required)
- form_schema: jsonb (required)
- history_id: integer (required, fk)
- history_date: timestamp with time zone (required)
- history_change_reason: varchar
- history_type: varchar (required)
- history_user_id: uuid (fk)

### process_historicalformentry
- id: uuid (required)
- entry_date: date (required)
- data: jsonb (required)
- is_active: boolean (required)
- history_id: integer (required, fk)
- history_date: timestamp with time zone (required)
- history_change_reason: varchar
- history_type: varchar (required)
- entered_by_id: uuid (fk)
- form_id: uuid (fk)
- history_user_id: uuid (fk)
- job_id: uuid (fk)
- staff_id: uuid (fk)

### process_historicalprocedure
- id: uuid (required)
- document_type: varchar (required)
- title: varchar (required)
- document_number: varchar
- site_location: varchar (required)
- tags: jsonb (required)
- status: varchar (required)
- google_doc_id: varchar (required, fk)
- google_doc_url: varchar (required)
- history_id: integer (required, fk)
- history_date: timestamp with time zone (required)
- history_change_reason: varchar
- history_type: varchar (required)
- history_user_id: uuid (fk)
- job_id: uuid (fk)

### process_procedure
- id: uuid (required)
- document_type: varchar (required)
- title: varchar (required)
- document_number: varchar
- site_location: varchar (required)
- tags: jsonb (required)
- status: varchar (required)
- google_doc_id: varchar (required, fk)
- google_doc_url: varchar (required)
- job_id: uuid (fk)

### purchasing_purchaseorder
- id: uuid (required)
- po_number: varchar (required)
- order_date: date (required)
- expected_delivery: date
- xero_id: uuid (fk)
- status: varchar (required)
- supplier_id: uuid (fk)
- xero_last_modified: timestamp with time zone
- xero_last_synced: timestamp with time zone
- online_url: varchar
- reference: varchar
- job_id: uuid (fk)
- xero_tenant_id: varchar (fk)
- raw_json: jsonb
- pickup_address_id: uuid (fk)
- created_by_id: uuid (fk)

### purchasing_purchaseorderevent
- id: uuid (required)
- timestamp: timestamp with time zone (required)
- description: text (required)
- purchase_order_id: uuid (required, fk)
- staff_id: uuid (required, fk)

### purchasing_purchaseorderline
- id: uuid (required)
- description: varchar (required)
- quantity: numeric(10
- unit_cost: numeric(10
- received_quantity: numeric(10
- purchase_order_id: uuid (required, fk)
- price_tbc: boolean (required)
- dimensions: varchar
- supplier_item_code: varchar
- raw_line_data: jsonb
- alloy: varchar
- job_id: uuid (fk)
- location: varchar
- metal_type: varchar
- specifics: varchar
- item_code: varchar
- xero_line_item_id: uuid (fk)

### purchasing_purchaseordersupplierquote
- id: uuid (required)
- filename: varchar (required)
- file_path: varchar (required)
- mime_type: varchar (required)
- uploaded_at: timestamp with time zone (required)
- extracted_data: jsonb
- status: varchar (required)
- purchase_order_id: uuid (required, fk)

### purchasing_stock
- id: uuid (required)
- description: varchar (required)
- quantity: numeric(10
- unit_cost: numeric(10
- date: timestamp with time zone (required)
- source: varchar (required)
- location: text (required)
- metal_type: varchar (required)
- alloy: varchar
- specifics: varchar
- is_active: boolean (required)
- job_id: uuid (fk)
- source_purchase_order_line_id: uuid (fk)
- source_parent_stock_id: uuid (fk)
- item_code: varchar
- xero_id: varchar (fk)
- xero_last_modified: timestamp with time zone
- raw_json: jsonb
- parsed_at: timestamp with time zone
- parser_confidence: numeric(3
- parser_version: varchar
- xero_inventory_tracked: boolean (required)
- unit_revenue: numeric(10
- active_source_purchase_order_line_id: uuid (fk)
- xero_last_synced: timestamp with time zone

### quoting_productparsingmapping
- id: uuid (required)
- input_hash: varchar (required)
- input_data: jsonb (required)
- mapped_item_code: varchar
- mapped_description: varchar
- mapped_metal_type: varchar
- mapped_alloy: varchar
- mapped_specifics: varchar
- mapped_dimensions: varchar
- mapped_unit_cost: numeric(10
- mapped_price_unit: varchar
- parser_version: varchar
- parser_confidence: numeric(3
- llm_response: jsonb
- is_validated: boolean (required)
- validated_at: timestamp with time zone
- validation_notes: text
- validated_by_id: uuid (fk)
- item_code_is_in_xero: boolean (required)
- derived_key: character varying(100

### quoting_scrapejob
- id: uuid (required)
- status: varchar (required)
- started_at: timestamp with time zone (required)
- completed_at: timestamp with time zone
- products_scraped: integer (required)
- products_failed: integer (required)
- error_message: text
- supplier_id: uuid (required, fk)

### quoting_supplierpricelist
- id: uuid (required)
- file_name: varchar (required)
- uploaded_at: timestamp with time zone (required)
- supplier_id: uuid (required, fk)

### quoting_supplierproduct
- id: uuid (required)
- product_name: varchar (required)
- item_no: varchar (required)
- description: text
- specifications: text
- variant_id: varchar (required, fk)
- variant_width: varchar
- variant_length: varchar
- variant_price: numeric(10
- price_unit: varchar
- variant_available_stock: integer
- url: varchar (required)
- supplier_id: uuid (required, fk)
- price_list_id: uuid (required, fk)
- parsed_alloy: varchar
- parsed_at: timestamp with time zone
- parsed_description: varchar
- parsed_dimensions: varchar
- parsed_item_code: varchar
- parsed_metal_type: varchar
- parsed_price_unit: varchar
- parsed_specifics: varchar
- parsed_unit_cost: numeric(10
- parser_confidence: numeric(3
- parser_version: varchar
- mapping_hash: varchar
- last_scraped: timestamp with time zone (required)
- is_discontinued: boolean (required)

### workflow_aiprovider
- id: bigint (required)
- name: varchar (required)
- api_key: varchar
- provider_type: varchar (required)
- default: boolean (required)
- model_name: varchar (required)

### workflow_apperror
- id: uuid (required)
- timestamp: timestamp with time zone (required)
- message: text (required)
- data: jsonb
- app: varchar
- file: varchar
- function: varchar
- job_id: uuid (fk)
- resolved: boolean (required)
- resolved_by_id: uuid (fk)
- resolved_timestamp: timestamp with time zone
- severity: integer (required)
- user_id: uuid (fk)

### workflow_companydefaults
- time_markup: numeric(5
- materials_markup: numeric(5
- charge_out_rate: numeric(6
- wage_rate: numeric(6
- mon_start: time without time zone (required)
- mon_end: time without time zone (required)
- tue_start: time without time zone (required)
- tue_end: time without time zone (required)
- wed_start: time without time zone (required)
- wed_end: time without time zone (required)
- thu_start: time without time zone (required)
- thu_end: time without time zone (required)
- fri_start: time without time zone (required)
- fri_end: time without time zone (required)
- company_name: varchar (required)
- last_xero_sync: timestamp with time zone
- last_xero_deep_sync: timestamp with time zone
- xero_tenant_id: varchar (fk)
- starting_po_number: integer (required)
- kpi_daily_billable_hours_amber: numeric(5
- kpi_daily_billable_hours_green: numeric(5
- kpi_daily_gp_target: numeric(10
- kpi_daily_shop_hours_percentage: numeric(5
- po_prefix: varchar (required)
- master_quote_template_url: varchar
- starting_job_number: integer (required)
- shop_client_name: varchar
- gdrive_quotes_folder_id: varchar (fk)
- gdrive_quotes_folder_url: varchar
- master_quote_template_id: varchar (fk)
- test_client_name: varchar
- address_line1: varchar
- address_line2: varchar
- city: varchar
- country: varchar (required)
- post_code: varchar
- suburb: varchar
- company_email: varchar
- company_url: varchar
- company_acronym: varchar
- xero_payroll_calendar_name: varchar (required)
- xero_shortcode: varchar
- xero_payroll_calendar_id: uuid (fk)
- annual_leave_loading: numeric(5
- financial_year_start_month: integer (required)
- kpi_job_gp_target_percentage: numeric(5
- kpi_daily_gp_amber: numeric(10
- kpi_daily_gp_green: numeric(10
- gdrive_how_we_work_folder_id: varchar (fk)
- gdrive_reference_library_folder_id: varchar (fk)
- gdrive_sops_folder_id: varchar (fk)
- google_shared_drive_id: varchar (fk)
- xero_payroll_start_date: date
- id: bigint (required)
- company_phone: varchar
- logo: varchar
- logo_wide: varchar
- enable_xero_sync: boolean (required)

### workflow_serviceapikey
- id: uuid (required)
- name: varchar (required)
- is_active: boolean (required)
- last_used: timestamp with time zone

### workflow_xeroaccount
- id: uuid (required)
- xero_id: uuid (required, fk)
- account_code: varchar
- account_name: varchar (required)
- description: text
- account_type: varchar
- tax_type: varchar
- enable_payments: boolean (required)
- xero_last_modified: timestamp with time zone (required)
- raw_json: jsonb (required)
- django_created_at: timestamp with time zone (required)
- django_updated_at: timestamp with time zone (required)
- xero_last_synced: timestamp with time zone
- xero_tenant_id: character varying(255 (fk)

### workflow_xeroerror
- apperror_ptr_id: uuid (required, fk)
- entity: varchar (required)
- reference_id: varchar (required, fk)
- kind: varchar (required)

### workflow_xerojournal
- id: uuid (required)
- xero_id: uuid (required, fk)
- journal_date: date (required)
- created_date_utc: timestamp with time zone (required)
- journal_number: integer (required)
- reference: varchar
- source_id: uuid (fk)
- source_type: varchar
- raw_json: jsonb (required)
- django_created_at: timestamp with time zone (required)
- django_updated_at: timestamp with time zone (required)
- xero_last_modified: timestamp with time zone (required)
- xero_last_synced: timestamp with time zone
- xero_tenant_id: character varying(255 (fk)

### workflow_xerojournallineitem
- id: uuid (required)
- xero_line_id: uuid (required, fk)
- description: text
- net_amount: numeric(10
- gross_amount: numeric(10
- tax_amount: numeric(10
- tax_type: varchar
- tax_name: varchar
- raw_json: jsonb (required)
- django_created_at: timestamp with time zone (required)
- django_updated_at: timestamp with time zone (required)
- account_id: uuid (fk)
- journal_id: uuid (required, fk)

### workflow_xeropayitem
- id: uuid (required)
- xero_id: varchar (fk)
- xero_tenant_id: varchar (fk)
- name: varchar (required)
- uses_leave_api: boolean (required)
- multiplier: numeric(4
- xero_last_modified: timestamp with time zone
- xero_last_synced: timestamp with time zone

### workflow_xeropayrun
- id: uuid (required)
- xero_id: uuid (required, fk)
- xero_tenant_id: varchar (required, fk)
- payroll_calendar_id: uuid (fk)
- period_start_date: date (required)
- period_end_date: date (required)
- payment_date: date (required)
- pay_run_status: varchar
- pay_run_type: varchar
- total_cost: numeric(12
- total_pay: numeric(12
- raw_json: jsonb (required)
- xero_last_modified: timestamp with time zone (required)
- xero_last_synced: timestamp with time zone
- django_created_at: timestamp with time zone (required)
- django_updated_at: timestamp with time zone (required)

### workflow_xeropayslip
- id: uuid (required)
- xero_id: uuid (required, fk)
- xero_tenant_id: varchar (required, fk)
- xero_employee_id: uuid (required, fk)
- employee_name: varchar
- gross_earnings: numeric(10
- tax_amount: numeric(10
- net_pay: numeric(10
- timesheet_hours: numeric(8
- leave_hours: numeric(8
- raw_json: jsonb (required)
- xero_last_modified: timestamp with time zone (required)
- xero_last_synced: timestamp with time zone
- django_created_at: timestamp with time zone (required)
- django_updated_at: timestamp with time zone (required)
- pay_run_id: uuid (required, fk)

### workflow_xerosynccursor
- id: bigint (required)
- entity_key: varchar (required)
- last_modified: timestamp with time zone (required)

### workflow_xerotoken
- id: bigint (required)
- tenant_id: varchar (required, fk)
- token_type: varchar (required)
- access_token: text (required)
- refresh_token: text (required)
- expires_at: timestamp with time zone (required)
- scope: text (required)

---

# Components

- **App** [client] — `src/App.vue`
- **AIProvidersDialog** [client] — props: providers — `src/components/AIProvidersDialog.vue`
- **AdvancedSearchDialog** [client] — `src/components/AdvancedSearchDialog.vue`
- **AppLayout** [client] — `src/components/AppLayout.vue`
- **AppNavbar** [client] — `src/components/AppNavbar.vue`
- **ClientDropdown** [client] — `src/components/ClientDropdown.vue`
- **ClientLookup** [client] — props: id, label, placeholder, required, modelValue, supplierLookup — `src/components/ClientLookup.vue`
- **CompanyDefaultsFormModal** [client] — props: defaults — `src/components/CompanyDefaultsFormModal.vue`
- **ConfirmModal** [client] — props: title, message — `src/components/ConfirmModal.vue`
- **ContactSelectionModal** [client] — props: isOpen, clientId, clientName, contacts, selectedContact, isLoading, newContactForm, editingContact, isEditing — `src/components/ContactSelectionModal.vue`
- **ContactSelector** [client] — props: id, label, placeholder, optional, clientId, clientName, modelValue, initialContactId — `src/components/ContactSelector.vue`
- **CreateClientModal** [client] — `src/components/CreateClientModal.vue`
- **DataTable** [client] — props: columns, data, pageSize, hideFooter, isLoading — `src/components/DataTable.vue`
- **ExecutionsModal** [client] — `src/components/ExecutionsModal.vue`
- **JobCard** [client] — props: job, isDragging, isStaffDragTarget, isMovementModeActive, isJobSelectedForMovement, mobileSelectedStaffId, enableTapAssign — `src/components/JobCard.vue`
- **JobFormModal** [client] — props: job — `src/components/JobFormModal.vue`
- **JobsModal** [client] — `src/components/JobsModal.vue`
- **KanbanColumn** [client] — `src/components/KanbanColumn.vue`
- **QuoteStatus** [client] — props: jobId, autoRefresh — `src/components/QuoteStatus.vue`
- **RichTextEditor** [client] — `src/components/RichTextEditor.vue`
- **SectionModal** [client] — props: section — `src/components/SectionModal.vue`
- **StaffAvatar** [client] — props: staff, size, isActive, isDragging — `src/components/StaffAvatar.vue`
- **StaffDropdown** [client] — `src/components/StaffDropdown.vue`
- **StaffFormModal** [client] — props: staff — `src/components/StaffFormModal.vue`
- **StaffPanel** [client] — `src/components/StaffPanel.vue`
- **StatusMultiSelect** [client] — `src/components/StatusMultiSelect.vue`
- **AIProviderFormModal** [client] — props: provider — `src/components/admin/AIProviderFormModal.vue`
- **MonthEndSummary** [client] — props: jobs, stockSummary, monthKey, selectedIds, isLoading — `src/components/admin/MonthEndSummary.vue`
- **ErrorDialog** [client] — props: error — `src/components/admin/errors/ErrorDialog.vue`
- **ErrorFilter** [client] — props: modelValue — `src/components/admin/errors/ErrorFilter.vue`
- **ErrorTable** [client] — props: headers, rows, id, occurredAt, message, entity, severity — `src/components/admin/errors/ErrorTable.vue`
- **ErrorTabs** [client] — props: modelValue — `src/components/admin/errors/ErrorTabs.vue`
- **JobErrorFilter** [client] — props: modelValue — `src/components/admin/errors/JobErrorFilter.vue`
- **SystemErrorFilter** [client] — props: modelValue — `src/components/admin/errors/SystemErrorFilter.vue`
- **ActiveJobCard** [client] — props: job — `src/components/board/ActiveJobCard.vue`
- **NoActiveJobPrompt** [client] — `src/components/board/NoActiveJobPrompt.vue`
- **WorkshopModeView** [client] — `src/components/board/WorkshopModeView.vue`
- **WorkshopOfficeToggle** [client] — `src/components/board/WorkshopOfficeToggle.vue`
- **McpToolDetails** [client] — `src/components/chat/McpToolDetails.vue`
- **ToolCallDisplay** [client] — `src/components/chat/ToolCallDisplay.vue`
- **IconCommunity** [client] — `src/components/icons/IconCommunity.vue`
- **IconDocumentation** [client] — `src/components/icons/IconDocumentation.vue`
- **IconEcosystem** [client] — `src/components/icons/IconEcosystem.vue`
- **IconSupport** [client] — `src/components/icons/IconSupport.vue`
- **IconTooling** [client] — `src/components/icons/IconTooling.vue`
- **CameraModal** [client] — `src/components/job/CameraModal.vue`
- **JobActualTab** [client] — props: jobId, jobNumber, pricingMethodology, quoted, fullyInvoiced, paid — `src/components/job/JobActualTab.vue`
- **JobAttachmentsTab** [client] — `src/components/job/JobAttachmentsTab.vue`
- **JobCostAnalysisTab** [client] — props: jobId, pricingMethodology — `src/components/job/JobCostAnalysisTab.vue`
- **JobEstimateTab** [client] — `src/components/job/JobEstimateTab.vue`
- **JobHistoryTab** [client] — `src/components/job/JobHistoryTab.vue`
- **JobPdfDialog** [client] — props: jobId, jobNumber, open — `src/components/job/JobPdfDialog.vue`
- **JobPdfTab** [client] — props: variant — `src/components/job/JobPdfTab.vue`
- **JobPricingGrids** [client] — `src/components/job/JobPricingGrids.vue`
- **JobQuoteTab** [client] — props: jobId, jobNumber, jobStatus, pricingMethodology, quoted, fullyInvoiced, quoteAcceptanceDate — `src/components/job/JobQuoteTab.vue`
- **JobQuotingChatTab** [client] — `src/components/job/JobQuotingChatTab.vue`
- **JobSafetyTab** [client] — `src/components/job/JobSafetyTab.vue`
- **JobSettingsTab** [client] — props: jobId, jobNumber, pricingMethodology, quoted, fullyInvoiced — `src/components/job/JobSettingsTab.vue`
- **JobViewTabs** [client] — props: activeTab, jobId, jobNumber, jobStatus, chargeOutRate, pricingMethodology, quoted, fullyInvoiced, paid, companyDefaults — `src/components/job/JobViewTabs.vue`
- **SimpleTotalTable** [client] — `src/components/job/SimpleTotalTable.vue`
- **WorkshopPdfViewer** [client] — props: jobId — `src/components/job/WorkshopPdfViewer.vue`
- **KanbanGridLayout** [client] — props: mode, visibleStatusChoices, getSortedJobsByStatus, isLoading, isDragging, getColumnHasMore, getColumnTotal, getColumnLoadedCount, isSearchActive, mobileAssignStaffId — `src/components/kanban/KanbanGridLayout.vue`
- **KanbanMobileLayout** [client] — props: visibleStatusChoices, getSortedJobsByStatus, isLoading, isDragging, getColumnHasMore, getColumnTotal, getColumnLoadedCount, isSearchActive, mobileAssignStaffId, enableTapAssign — `src/components/kanban/KanbanMobileLayout.vue`
- **StatusBadge** [client] — `src/components/kanban/StatusBadge.vue`
- **KPICalendar** [client] — props: calendarData, thresholds, year, month — `src/components/kpi/KPICalendar.vue`
- **KPICalendarDay** [client] — props: dayData, thresholds — `src/components/kpi/KPICalendarDay.vue`
- **KPICard** [client] — `src/components/kpi/KPICard.vue`
- **KPIDayDetailsModal** [client] — `src/components/kpi/KPIDayDetailsModal.vue`
- **KPILabourDetailsModal** [client] — props: monthlyData, calendarData, year, month, isOpen — `src/components/kpi/KPILabourDetailsModal.vue`
- **KPIMaterialsDetailsModal** [client] — props: calendarData, year, month, isOpen — `src/components/kpi/KPIMaterialsDetailsModal.vue`
- **KPIProfitDetailsModal** [client] — props: monthlyData, thresholds, calendarData, year, month, isOpen — `src/components/kpi/KPIProfitDetailsModal.vue`
- **MonthSelector** [client] — props: year, month — `src/components/kpi/MonthSelector.vue`
- **ChildRecordsTable** [client] — `src/components/process-documents/ChildRecordsTable.vue`
- **DynamicFormEntry** [client] — `src/components/process-documents/DynamicFormEntry.vue`
- **EntriesTable** [client] — `src/components/process-documents/EntriesTable.vue`
- **FillTemplateModal** [client] — `src/components/process-documents/FillTemplateModal.vue`
- **ProcessDocumentFilters** [client] — `src/components/process-documents/ProcessDocumentFilters.vue`
- **ProcessDocumentModal** [client] — `src/components/process-documents/ProcessDocumentModal.vue`
- **ProcessDocumentTable** [client] — `src/components/process-documents/ProcessDocumentTable.vue`
- **ControlsList** [client] — `src/components/process-documents/safety-wizard/ControlsList.vue`
- **HazardsList** [client] — `src/components/process-documents/safety-wizard/HazardsList.vue`
- **PPEEditor** [client] — `src/components/process-documents/safety-wizard/PPEEditor.vue`
- **SafetyWizardModal** [client] — `src/components/process-documents/safety-wizard/SafetyWizardModal.vue`
- **SideBySideEditor** [client] — `src/components/process-documents/safety-wizard/SideBySideEditor.vue`
- **AddressAutocompleteInput** [client] — props: modelValue, placeholder, debounceMs, autofocus — `src/components/purchasing/AddressAutocompleteInput.vue`
- **AllocationCellEditor** [client] — `src/components/purchasing/AllocationCellEditor.vue`
- **DragAndDropUploader** [client] — `src/components/purchasing/DragAndDropUploader.vue`
- **ExistingAllocationsDisplay** [client] — props: existingAllocations, lines — `src/components/purchasing/ExistingAllocationsDisplay.vue`
- **JobSelect** [client] — props: modelValue, jobs, placeholder, hasError, errorMessage, isLoading, disabled — `src/components/purchasing/JobSelect.vue`
- **PendingItemsTable** [client] — `src/components/purchasing/PendingItemsTable.vue`
- **PickupAddressSelectionModal** [client] — props: isOpen, supplierId, supplierName, addresses, selectedAddress, isLoading, newAddressForm, editingAddress, isEditing — `src/components/purchasing/PickupAddressSelectionModal.vue`
- **PickupAddressSelector** [client] — props: id, label, placeholder, optional, supplierId, supplierName, modelValue, initialAddressId, disabled — `src/components/purchasing/PickupAddressSelector.vue`
- **PoCommentsSection** [client] — props: poId — `src/components/purchasing/PoCommentsSection.vue`
- **PoLinesTable** [client] — `src/components/purchasing/PoLinesTable.vue`
- **PoPdfDialog** [client] — props: purchaseOrderId, poNumber, open — `src/components/purchasing/PoPdfDialog.vue`
- **PoPdfViewer** [client] — props: purchaseOrderId — `src/components/purchasing/PoPdfViewer.vue`
- **PoSummaryCard** [client] — props: po, isCreateMode, showActions, syncEnabled, supplierReadonly — `src/components/purchasing/PoSummaryCard.vue`
- **QuoteCostLinesGrid** [client] — props: costLines, isLoading — `src/components/quote/QuoteCostLinesGrid.vue`
- **CompactSummaryCard** [client] — props: title, summary, costLines, isLoading, revision — `src/components/shared/CompactSummaryCard.vue`
- **CostLinesGrid** [client] — props: costLines, isLoading, showActions — `src/components/shared/CostLinesGrid.vue`
- **CostSetSummaryCard** [client] — props: title, summary, costLines, isLoading, revision — `src/components/shared/CostSetSummaryCard.vue`
- **InlineEditClient** [client] — `src/components/shared/InlineEditClient.vue`
- **InlineEditSelect** [client] — `src/components/shared/InlineEditSelect.vue`
- **InlineEditText** [client] — `src/components/shared/InlineEditText.vue`
- **SmartCostLinesTable** [client] — props: lines, tabKind, readOnly, showItemColumn, showSourceColumn, sourceResolver, line — `src/components/shared/SmartCostLinesTable.vue`
- **BillablePercentageBadge** [client] — props: percentage — `src/components/timesheet/BillablePercentageBadge.vue`
- **MetricsModal** [client] — props: open, summary — `src/components/timesheet/MetricsModal.vue`
- **PayrollControlSection** [client] — `src/components/timesheet/PayrollControlSection.vue`
- **PayrollStaffRow** [client] — `src/components/timesheet/PayrollStaffRow.vue`
- **StaffDetailModal** [client] — `src/components/timesheet/StaffDetailModal.vue`
- **StaffRow** [client] — `src/components/timesheet/StaffRow.vue`
- **StaffWeekRow** [client] — `src/components/timesheet/StaffWeekRow.vue`
- **StatusBadge** [client] — `src/components/timesheet/StatusBadge.vue`
- **SummaryCard** [client] — props: title, value, subtitle, progress, icon, color — `src/components/timesheet/SummaryCard.vue`
- **SummaryDrawer** [client] — `src/components/timesheet/SummaryDrawer.vue`
- **TimesheetActionsCell** [client] — props: approved, canApprove, onApprove, onDelete — `src/components/timesheet/TimesheetActionsCell.vue`
- **WeekPickerModal** [client] — `src/components/timesheet/WeekPickerModal.vue`
- **WeeklyMetricsModal** [client] — `src/components/timesheet/WeeklyMetricsModal.vue`
- **WorkshopJobAttachmentsCard** [client] — `src/components/workshop/WorkshopJobAttachmentsCard.vue`
- **WorkshopJobDescriptionCard** [client] — `src/components/workshop/WorkshopJobDescriptionCard.vue`
- **WorkshopJobHeader** [client] — `src/components/workshop/WorkshopJobHeader.vue`
- **WorkshopJobKeyInfoCard** [client] — `src/components/workshop/WorkshopJobKeyInfoCard.vue`
- **WorkshopJobNotesCard** [client] — `src/components/workshop/WorkshopJobNotesCard.vue`
- **WorkshopJobPickerDrawer** [client] — `src/components/workshop/WorkshopJobPickerDrawer.vue`
- **WorkshopJobSummaryCard** [client] — `src/components/workshop/WorkshopJobSummaryCard.vue`
- **WorkshopMaterialsUsedTable** [client] — props: jobId — `src/components/workshop/WorkshopMaterialsUsedTable.vue`
- **WorkshopMyTimeHeader** [client] — `src/components/workshop/WorkshopMyTimeHeader.vue`
- **WorkshopStopwatch** [client] — props: jobId, jobName — `src/components/workshop/WorkshopStopwatch.vue`
- **WorkshopTimeUsedTable** [client] — props: jobId, workshopHours — `src/components/workshop/WorkshopTimeUsedTable.vue`
- **WorkshopTimesheetCalendar** [client] — `src/components/workshop/WorkshopTimesheetCalendar.vue`
- **WorkshopTimesheetEntryDrawer** [client] — `src/components/workshop/WorkshopTimesheetEntryDrawer.vue`
- **WorkshopTimesheetLegacyTable** [client] — `src/components/workshop/WorkshopTimesheetLegacyTable.vue`
- **WorkshopTimesheetSummaryCard** [client] — `src/components/workshop/WorkshopTimesheetSummaryCard.vue`
- **AboutView** [client] — `src/views/AboutView.vue`
- **AdminAIProvidersView** [client] — `src/views/AdminAIProvidersView.vue`
- **AdminArchiveJobsView** [client] — `src/views/AdminArchiveJobsView.vue`
- **AdminCompanyView** [client] — `src/views/AdminCompanyView.vue`
- **AdminDjangoJobsView** [client] — `src/views/AdminDjangoJobsView.vue`
- **AdminErrorView** [client] — `src/views/AdminErrorView.vue`
- **AdminMonthEnd** [client] — `src/views/AdminMonthEnd.vue`
- **AdminStaffView** [client] — `src/views/AdminStaffView.vue`
- **AdminView** [client] — `src/views/AdminView.vue`
- **ClientDetailView** [client] — `src/views/ClientDetailView.vue`
- **ClientsView** [client] — `src/views/ClientsView.vue`
- **DailyTimesheetView** [client] — `src/views/DailyTimesheetView.vue`
- **DataQualityArchivedJobsView** [client] — `src/views/DataQualityArchivedJobsView.vue`
- **FormEntriesView** [client] — `src/views/FormEntriesView.vue`
- **JobAgingReportView** [client] — `src/views/JobAgingReportView.vue`
- **JobCreateView** [client] — `src/views/JobCreateView.vue`
- **JobMovementReportView** [client] — props: title — `src/views/JobMovementReportView.vue`
- **JobProfitabilityReportView** [client] — `src/views/JobProfitabilityReportView.vue`
- **JobTable** [client] — props: columns, data, title, modelValue, isLoading — `src/views/JobTable.vue`
- **JobView** [client] — `src/views/JobView.vue`
- **JsaListView** [client] — `src/views/JsaListView.vue`
- **KPIReportsView** [client] — `src/views/KPIReportsView.vue`
- **KanbanView** [client] — `src/views/KanbanView.vue`
- **LoginView** [client] — `src/views/LoginView.vue`
- **PayrollReconciliationReportView** [client] — `src/views/PayrollReconciliationReportView.vue`
- **ProcessDocumentsView** [client] — `src/views/ProcessDocumentsView.vue`
- **ProfitLossReportView** [client] — `src/views/ProfitLossReportView.vue`
- **QuotingChatView** [client] — `src/views/QuotingChatView.vue`
- **RDTISpendReportView** [client] — `src/views/RDTISpendReportView.vue`
- **SalesForecastReportView** [client] — `src/views/SalesForecastReportView.vue`
- **StaffPerformanceReportView** [client] — `src/views/StaffPerformanceReportView.vue`
- **SwpListView** [client] — `src/views/SwpListView.vue`
- **TimesheetEntryView** [client] — `src/views/TimesheetEntryView.vue`
- **WIPReportView** [client] — `src/views/WIPReportView.vue`
- **WeeklyTimesheetView** [client] — `src/views/WeeklyTimesheetView.vue`
- **WorkshopJobView** [client] — `src/views/WorkshopJobView.vue`
- **WorkshopKanbanView** [client] — `src/views/WorkshopKanbanView.vue`
- **WorkshopMyTimeView** [client] — `src/views/WorkshopMyTimeView.vue`
- **WorkshopView** [client] — `src/views/WorkshopView.vue`
- **XeroView** [client] — `src/views/XeroView.vue`
- **CreateFromQuoteView** [client] — `src/views/purchasing/CreateFromQuoteView.vue`
- **ItemSelect** [client] — props: modelValue, disabled, showQuantity, lineKind, tabKind — `src/views/purchasing/ItemSelect.vue`
- **PoCreateView** [client] — `src/views/purchasing/PoCreateView.vue`
- **ProductMappingValidationView** [client] — `src/views/purchasing/ProductMappingValidationView.vue`
- **PurchaseOrderFormView** [client] — `src/views/purchasing/PurchaseOrderFormView.vue`
- **PurchaseOrderView** [client] — `src/views/purchasing/PurchaseOrderView.vue`
- **StockView** [client] — `src/views/purchasing/StockView.vue`
- **SupplierPricingUploadView** [client] — `src/views/purchasing/SupplierPricingUploadView.vue`

---

# Libraries

- `src/api/client.ts`
  - function setupETagManager: (manager) => void
  - function setupJobReloadManager: (manager) => void
  - function setupPoETagManager: (manager) => void
  - function setupPoReloadManager: (manager) => void
  - function getApi: () => InstanceType<typeof Zodios<typeof endpoints>>
  - const api
- `src/api/generated/api.ts`
  - function createApiClient: (baseUrl, options?) => void
  - const schemas
  - const api
- `src/composables/useActiveJob.ts` — function useActiveJob: () => void
- `src/composables/useAddEmptyCostLine.ts` — function useAddEmptyCostLine: (options) => void, interface UseAddEmptyCostLineOptions
- `src/composables/useAddMaterialCostLine.ts` — function useAddMaterialCostLine: (options) => void, interface UseAddMaterialCostLineOptions
- `src/composables/useAppLayout.ts` — function useAppLayout: () => void
- `src/composables/useBoardMode.ts` — function useBoardMode: () => void, type BoardMode
- `src/composables/useCamera.ts` — function useCamera: (options) => void
- `src/composables/useClientLookup.ts`
  - function useClientLookup: () => void
  - type Client
  - type ClientContact
- `src/composables/useConcurrencyEvents.ts` — function emitConcurrencyRetry: (jobId) => void, function onConcurrencyRetry: (jobId, handler) => void
- `src/composables/useContactManagement.ts` — function useContactManagement: () => void, type ContactFormData
- `src/composables/useCostLineAutosave.ts` — function useCostLineAutosave: (opts) => void, type SaveStatus
- `src/composables/useCostLineCalculations.ts`
  - function useCostLineCalculations: (options?) => void
  - interface LineDerivedValues
  - interface ValidationIssue
  - interface ValidationResult
  - interface ApplyResult
- `src/composables/useCostLinesActions.ts` — function useCostLinesActions: (options) => void, interface UseCostLinesActionsOptions
- `src/composables/useCostSummary.ts`
  - function useCostSummary: (options) => void
  - interface UseCostSummaryOptions
  - type CostSummary
- `src/composables/useCreateCostLineFromEmpty.ts` — function useCreateCostLineFromEmpty: (options) => void, interface UseCreateCostLineFromEmptyOptions
- `src/composables/useDashboard.ts` — function useDashboard: () => void
- `src/composables/useDeviceDetection.ts` — function useDeviceDetection: () => void
- `src/composables/useDragAndDrop.ts`
  - function useDragAndDrop: (onDragEvent?) => void
  - interface DragEventPayload
  - type DragEventHandler
- `src/composables/useErrorApi.ts` — function useErrorApi: () => void
- `src/composables/useFinancialYear.ts` — function useFinancialYear: () => void
- `src/composables/useGridKeyboardNav.ts` — function useGridKeyboardNav: (opts) => void, type EditIntent
- `src/composables/useJobAttachments.ts` — function useJobAttachments: (jobId) => void
- `src/composables/useJobAutoSync.ts` — function useJobAutoSync: (jobId, reloadFunction) => void
- `src/composables/useJobAutosave.ts`
  - function createJobAutosave: (opts) => JobAutosaveApi
  - type SaveResult
  - type RetryPolicy
  - type NormalizeFn
  - type IsEqualFn
  - type CanSaveFn
  - _...2 more_
- `src/composables/useJobCache.ts` — function useJobCache: () => void
- `src/composables/useJobCard.ts` — function useJobCard: (job, emit, job) => void
- `src/composables/useJobDelta.ts` — function useJobDeltaQueue: (jobId) => void, function buildJobDeltaEnvelope: (input) => Promise<JobDeltaEnvelope>
- `src/composables/useJobETags.ts` — function useJobETags: () => void
- `src/composables/useJobEvents.ts` — function useJobEvents: (jobId) => void
- `src/composables/useJobFiles.ts` — function useJobFiles: (jobId) => void
- `src/composables/useJobFinancials.ts` — function useJobFinancials: (jobId) => void
- `src/composables/useJobHeaderAutosave.ts` — function useJobHeaderAutosave: (headerRef) => void
- `src/composables/useJobNotifications.ts` — function useJobNotifications: () => void
- `src/composables/useJobTabs.ts` — function useJobTabs: (defaultTab) => void
- `src/composables/useLogin.ts` — function useLogin: () => void
- `src/composables/useMonthEnd.ts` — function fetchMonthEnd: () => Promise<, function runMonthEnd: (jobIds) => Promise<
- `src/composables/useOptimizedDragAndDrop.ts`
  - function useOptimizedDragAndDrop: (onDragEvent?) => void
  - interface OptimizedDragEventPayload
  - type OptimizedDragEventHandler
- `src/composables/useOptimizedKanban.ts` — function useOptimizedKanban: (onJobsLoaded?) => void
- `src/composables/usePickupAddressManagement.ts`
  - function usePickupAddressManagement: () => void
  - type AddressFormData
  - type AddressCandidate
- `src/composables/usePoConcurrencyEvents.ts` — function emitPoConcurrencyRetry: (poId) => void, function onPoConcurrencyRetry: (poId, handler) => void
- `src/composables/usePoETags.ts` — function usePoETags: () => void
- `src/composables/usePurchaseOrderGrid.ts` — function usePurchaseOrderGrid: (lines) => void
- `src/composables/useQuoteImport.ts` — function useQuoteImport: () => void
- `src/composables/useSettingsSchema.ts` — function useSettingsSchema: () => void
- `src/composables/useSmartCostLineDelete.ts` — function useSmartCostLineDelete: (options) => void, interface UseSmartCostLineDeleteOptions
- `src/composables/useStaffApi.ts` — function useStaffApi: () => void
- `src/composables/useTimesheetEntryCalculations.ts` — function useTimesheetEntryCalculations: (companyDefaults) => void
- `src/composables/useTimesheetEntryGrid.ts` — function useTimesheetEntryGrid: (companyDefaults, jobs, unknown>[]>, onSaveEntry) => void
- `src/composables/useTimesheetSummary.ts` — function useTimesheetSummary: () => void
- `src/composables/useWorkshopCalendarSync.ts` — function useWorkshopCalendarSync: (options) => void
- `src/composables/useWorkshopJob.ts` — function useWorkshopJob: (jobId) => void, type SpeedQuality
- `src/composables/useWorkshopJobBudgets.ts` — function useWorkshopJobBudgets: (selectedJobIds) => void, type JobBudgetMeta
- `src/composables/useWorkshopTimesheetDay.ts`
  - function formatDateKey: (date) => string
  - function parseDateKey: (key) => Date
  - function formatFullDate: (date) => string
  - function useWorkshopTimesheetDay: (selectedDate) => void
  - type WorkingDayStartKey
- `src/composables/useWorkshopTimesheetForm.ts` — function useWorkshopTimesheetForm: (options, silent?) => void
- `src/composables/useWorkshopTimesheetJobs.ts` — function useWorkshopTimesheetJobs: () => void
- `src/composables/useWorkshopTimesheetTimeUtils.ts`
  - function ensureTimeWithSeconds: (time) => string
  - function formatTimeInputValue: (time?) => string
  - function minutesFromTime: (time) => number
  - function minutesToTime: (minutes) => string
  - function normalizeTimeRange: (startTime, endTime, slotMinutes) => void
  - function combineDateTime: (dateKey, time) => Date
  - _...2 more_
- `src/composables/useXeroAuth.ts` — function useXeroAuth: () => void
- `src/constants/job-status.ts`
  - function getStatusChoice: (key) => StatusChoice | undefined
  - function getStatusLabel: (key) => string
  - type JobStatusKey
  - type StatusChoice
  - const JOB_STATUS_CHOICES
- `src/lib/utils.ts` — function cn: (...inputs) => void
- `src/plugins/axios.ts` — function getApiBaseUrl
- `src/schemas/mcp-tool-metadata.schema.ts`
  - function parseMetadata: (metadata) => ValidationResult<McpMetadata>
  - function hasToolCalls: (metadata) => boolean
  - function getToolCallCount: (metadata) => number
  - interface ValidationResult
  - type ToolCall
  - type ToolDefinition
  - _...4 more_
- `src/services/admin-company-defaults-service.ts`
  - function getCompanyDefaults: () => Promise<CompanyDefaults>
  - function updateCompanyDefaults: (payload) => Promise<CompanyDefaults>
  - function uploadLogo: (fieldName, file) => Promise<CompanyDefaults>
  - function deleteLogo: (fieldName) => Promise<CompanyDefaults>
  - type CompanyDefaults
  - type PatchedCompanyDefaults
  - _...1 more_
- `src/services/aiProviderService.ts`
  - class AIProviderService
  - type AIProvider
  - type AIProviderCreateUpdate
  - const aiProviderService
- `src/services/clientService.ts`
  - class ClientService
  - type Client
  - type CreateClientData
  - const clientService
- `src/services/costing.service.ts` — function fetchCostSet
- `src/services/costline.service.ts`
  - function getTimesheetEntries
  - function createCostLine
  - function updateCostLine
  - function approveCostLine
  - function deleteCostLine
  - type TimesheetEntriesResponse
  - _...1 more_
- `src/services/daily-timesheet.service.ts`
  - function getDailyTimesheetSummary
  - function getStaffDailyDetail
  - function formatHours
  - function formatCurrency
  - function getStatusVariant
  - type DailyTimesheetSummary
  - _...1 more_
- `src/services/date.service.ts`
  - function today
  - function getCurrentWeekStart
  - function getWeekRange
  - function getCurrentWeekRange
  - function navigateWeek
  - function navigateDay
  - _...12 more_
- `src/services/delta.service.ts` — function submitJobDelta: (jobId, envelope) => Promise<
- `src/services/django-jobs-service.ts`
  - function getDjangoJobs: () => Promise<DjangoJob[]>
  - function createDjangoJob: (data) => Promise<DjangoJob>
  - function updateDjangoJob: (id, data) => Promise<DjangoJob>
  - function deleteDjangoJob: (id) => Promise<void>
  - function getDjangoJobExecutions: (search?) => Promise<DjangoJobExecution[]>
  - type DjangoJob
  - _...1 more_
- `src/services/feature-flags.service.ts` — class FeatureFlagsService, const featureFlags
- `src/services/job-aging-report.service.ts`
  - class JobAgingReportService
  - interface JobAgingData
  - interface JobAgingReportResponse
  - interface JobAgingReportParams
  - const jobAgingReportService
- `src/services/kanban-categorization.service.ts` — class KanbanCategorizationService
- `src/services/payroll-reconciliation-report.service.ts`
  - function fetchAlignedDateRange: (startDate, endDate) => void
  - function fetchPayrollReconciliation: (startDate, endDate) => Promise<PayrollReconciliationResponse>
  - function exportPayrollReconciliationCsv: (data) => void
  - type PayrollReconciliationResponse
- `src/services/payroll.service.ts`
  - function createPayRun: (weekStartDate) => Promise<CreatePayRunResponse>
  - function postStaffWeek: (staffIds, weekStartDate, callbacks?) => Promise<PostStaffWeekDoneEvent>
  - function fetchAllPayRuns: () => Promise<PayRunListResponse>
  - function refreshPayRuns: () => Promise<PayRunSyncResult>
  - interface PostStaffWeekStartEvent
  - interface PostStaffWeekProgressEvent
  - _...8 more_
- `src/services/quote-chat.service.ts` — class QuoteChatService, const quoteChatService
- `src/services/staff-performance-report.service.ts` — class StaffPerformanceReportService, const staffPerformanceReportService
- `src/services/timesheet.service.ts` — class TimesheetService
- `src/services/weekly-timesheet.service.ts`
  - function fetchWeeklyOverview: (startDate?) => Promise<WeeklyTimesheetData>
  - function getCurrentWeekRange: () => void
  - function getWeekRange: (date) => void
  - function formatDateRange: (startDate, endDate) => string
  - function formatHours: (hours) => string
  - function formatPercentage: (percentage) => string
- `src/services/wip-report.service.ts`
  - class WIPReportService
  - interface WIPJobData
  - interface WIPSummaryByStatus
  - interface WIPSummary
  - interface WIPReportResponse
  - interface WIPReportParams
  - _...1 more_
- `src/types/concurrency.ts`
  - function isConcurrencyError: (error) => error is ConcurrencyError
  - function extractJobId: (url) => string | null
  - function isJobEndpoint: (url) => boolean
  - function isJobMutationEndpoint: (url) => boolean
  - function extractPoId: (url) => string | null
  - function isPoEndpoint: (url) => boolean
  - _...4 more_
- `src/utils/contractValidation.ts` — function validateFields: (data, requiredFields) => void
- `src/utils/costLineMeta.ts`
  - function getJobEstimatedHours: (job) => number
  - function getJobActualHours: (job) => number
  - function getCostSetHoursSafe: (costSet?) => number
- `src/utils/csrf.ts` — function getCookie: (name) => string | null, function getCsrfToken: () => string | null
- `src/utils/dateUtils.ts`
  - function toLocalDateString: (date) => void
  - function toDateValue: (date) => DateValue | undefined
  - function fromDateValue: (dateValue) => Date | null
- `src/utils/debug.ts` — function debugLog: (...args) => void, const isDebugEnabled
- `src/utils/delivery-receipt.ts`
  - function transformDeliveryReceiptForAPI: (purchaseOrderId, uiAllocations, DeliveryAllocation[]>) => DeliveryReceiptRequest
  - function initializeEmptyAllocations: (lineIds) => Record<string, DeliveryAllocation[]>
  - type DeliveryAllocation
- `src/utils/deltaChecksum.ts`
  - function canonicaliseValue: (value) => string
  - function serialiseForChecksum: (jobId, before, unknown>, fields?) => string
  - function sha256Hex: (input) => Promise<string>
  - function computeJobDeltaChecksum: (jobId, before, unknown>, fields?) => Promise<string>
  - const deltaChecksumUtils
- `src/utils/deviceType.ts`
  - function setDevicePreference: (preference) => void
  - const isComputer
  - const isTouchscreen
  - const detectedDeviceType
- `src/utils/email.ts` — function openGmailCompose: ({...}, subject, body }) => void, interface EmailComposeOptions
- `src/utils/embeddedComponentRegistry.ts`
  - function getEmbeddedComponents: (sectionKey) => Component[]
  - function hasEmbeddedComponents: (sectionKey) => boolean
  - const SECTION_EMBEDDED_COMPONENTS: Record<string, Component[]>
- `src/utils/error-handler.ts`
  - function extractErrorMessage: (error) => string
  - function extractQuoteErrorMessage: (error) => string
  - function logError: (context, error, additionalData?, unknown>) => void
- `src/utils/errorHandler.ts`
  - function extractErrorMessage: (error, fallbackMessage) => string
  - function createErrorToast: () => void
  - function isAuthenticationError: (error) => boolean
- `src/utils/iconRegistry.ts`
  - function resolveIcon: (iconName) => Component
  - function getSectionIcon: (sectionKey) => Component
  - function getFieldIcon: (fieldKey) => Component
  - function hasIcon: (iconName) => boolean
- `src/utils/metalType.ts`
  - function formatMetalType: (metalType) => string
  - function getMetalTypeValue: (label) => string
  - const metalTypeOptions: Array<{ value: MetalType; label: string }>
- `src/utils/number.ts` — function roundToDecimalPlaces: (value, decimalPlaces) => number, function normalizeOptionalDecimal: (value, options?) => number | null | undefined
- `src/utils/safetyUtils.ts`
  - function createSafeDate: (dateValue) => Date
  - function getSafeNumber: (value, defaultValue) => number
  - function getSafeString: (value, defaultValue) => string
- `src/utils/sanitize.ts` — function trimStringsDeep: (input) => T, function normalizeOptionalString: (value) => string | undefined
- `src/utils/statusUtils.ts` — function getStatusVariant: (status) => string, function getJobColor: (jobId) => string
- `src/utils/string-formatting.ts`
  - function formatEventType: (snakeCaseString) => string
  - function formatFileSize: (bytes) => string
  - function formatDate: (dateString) => string
  - function truncateText: (text, maxLength) => string
  - function capitalize: (str) => string
  - function formatCurrency: (value, {...}) => string
  - _...5 more_

---

# Config

## Environment Variables

- `APP_URL` **required** — scripts/capture_metrics.cjs
- `BASE_URL` **required** — src/router/index.ts
- `CI` **required** — playwright.config.ts
- `DEBUG` **required** — tests/fixtures/auth.ts
- `DJANGO_PASSWORD` **required** — scripts/capture_metrics.cjs
- `DJANGO_USER` **required** — scripts/capture_metrics.cjs
- `E2E_TEST_PASSWORD` (has default) — .env.example
- `E2E_TEST_USERNAME` (has default) — .env.example
- `MODE` **required** — src/utils/debug.ts
- `PLAYWRIGHT_BROWSER_CHANNEL` **required** — tests/scripts/xero-login.ts
- `VITE_APP_NAME` (has default) — .env
- `VITE_UAT_URL` (has default) — .env.example
- `VITE_WEEKEND_TIMESHEETS_ENABLED` (has default) — .env.example
- `XERO_PASSWORD` (has default) — .env.example
- `XERO_USERNAME` (has default) — .env.example

## Config Files

- `.env.example`
- `tsconfig.json`
- `vite.config.ts`

## Key Dependencies

- tailwindcss: ^4.2.2
- vue: ^3.5.13
- zod: ^3.25.55

---

# Middleware

## custom
- e2e_testing_strategy — `docs/e2e_testing_strategy.md`

## auth
- auth — `src/stores/auth.ts`
- auth — `tests/fixtures/auth.ts`

---

# Dependency Graph

## Most Imported Files (change these carefully)

- `src/api/generated/api.ts` — imported by **75** files
- `src/utils/debug.ts` — imported by **51** files
- `src/api/client.ts` — imported by **40** files
- `tests/fixtures/auth.ts` — imported by **27** files
- `tests/fixtures/helpers.ts` — imported by **19** files
- `src/plugins/axios.ts` — imported by **14** files
- `src/utils/string-formatting.ts` — imported by **14** files
- `src/utils/dateUtils.ts` — imported by **13** files
- `src/stores/auth.ts` — imported by **7** files
- `src/stores/jobs.ts` — imported by **6** files
- `src/services/job.service.ts` — imported by **6** files
- `tests/scripts/db-backup-utils.ts` — imported by **5** files
- `src/constants/timesheet.ts` — imported by **4** files
- `src/services/costline.service.ts` — imported by **3** files
- `src/stores/companyDefaults.ts` — imported by **3** files
- `src/composables/useJobETags.ts` — imported by **3** files
- `src/composables/useJobDelta.ts` — imported by **3** files
- `src/constants/advanced-filters.ts` — imported by **3** files
- `src/composables/useConcurrencyEvents.ts` — imported by **2** files
- `src/composables/usePoConcurrencyEvents.ts` — imported by **2** files

## Import Map (who imports what)

- `src/api/generated/api.ts` ← `src/api/client.ts`, `src/components/purchasing/PurchaseOrderJobCellEditor.ts`, `src/components/timesheet/TimesheetEntryJobCellEditor.ts`, `src/composables/useActiveJob.ts`, `src/composables/useAddEmptyCostLine.ts` +70 more
- `src/utils/debug.ts` ← `src/api/client.ts`, `src/components/purchasing/PurchaseOrderJobCellEditor.ts`, `src/components/timesheet/TimesheetEntryJobCellEditor.ts`, `src/composables/useAppLayout.ts`, `src/composables/useCamera.ts` +46 more
- `src/api/client.ts` ← `src/composables/useClientLookup.ts`, `src/composables/useContactManagement.ts`, `src/composables/useErrorApi.ts`, `src/composables/useJobEvents.ts`, `src/composables/useJobFinancials.ts` +35 more
- `tests/fixtures/auth.ts` ← `tests/company-defaults.spec.ts`, `tests/example.spec.ts`, `tests/job/create-estimate-entry.spec.ts`, `tests/job/create-job-with-new-client.spec.ts`, `tests/job/create-job.spec.ts` +22 more
- `tests/fixtures/helpers.ts` ← `tests/fixtures/auth.ts`, `tests/job/create-estimate-entry.spec.ts`, `tests/job/create-job-with-new-client.spec.ts`, `tests/job/job-attachments.spec.ts`, `tests/job/job-header.spec.ts` +14 more
- `src/plugins/axios.ts` ← `src/composables/useJobAttachments.ts`, `src/composables/useWorkshopTimesheetForm.ts`, `src/composables/useXeroAuth.ts`, `src/services/job-aging-report.service.ts`, `src/services/job-movement-report.service.ts` +9 more
- `src/utils/string-formatting.ts` ← `src/composables/usePurchaseOrderGrid.ts`, `src/composables/useTimesheetEntryGrid.ts`, `src/composables/useWorkshopCalendarSync.ts`, `src/composables/useWorkshopJob.ts`, `src/composables/useWorkshopTimesheetTimeUtils.ts` +9 more
- `src/utils/dateUtils.ts` ← `src/composables/useAddMaterialCostLine.ts`, `src/composables/useCreateCostLineFromEmpty.ts`, `src/composables/useFinancialYear.ts`, `src/composables/useStaffApi.ts`, `src/composables/useTimesheetEntryGrid.ts` +8 more
- `src/stores/auth.ts` ← `src/composables/useAppLayout.ts`, `src/composables/useDashboard.ts`, `src/composables/useJobHeaderAutosave.ts`, `src/composables/useLogin.ts`, `src/plugins/axios.ts` +2 more
- `src/stores/jobs.ts` ← `src/composables/useCreateCostLineFromEmpty.ts`, `src/composables/useJobFiles.ts`, `src/composables/useJobHeaderAutosave.ts`, `src/composables/useOptimizedKanban.ts`, `src/composables/useTimesheetEntryCalculations.ts` +1 more

---

# Events & Queues

- `uncaughtException` [event] — `playwright-report/trace/assets/defaultSettingsView-BEpdCv1S.js`
- `mode` [event] — `playwright-report/trace/assets/defaultSettingsView-BEpdCv1S.js`
- `readOnly` [event] — `playwright-report/trace/assets/defaultSettingsView-BEpdCv1S.js`
- `lineNumbers` [event] — `playwright-report/trace/assets/defaultSettingsView-BEpdCv1S.js`
- `lineWrapping` [event] — `playwright-report/trace/assets/defaultSettingsView-BEpdCv1S.js`
- `placeholder` [event] — `playwright-report/trace/assets/defaultSettingsView-BEpdCv1S.js`
- `change` [event] — `playwright-report/trace/assets/defaultSettingsView-BEpdCv1S.js`

---

# Test Coverage

> **100%** of routes and models are covered by tests
> 50 test files found

## Covered Models

- accounting_bill
- accounting_billlineitem
- accounting_creditnote
- accounting_creditnotelineitem
- accounting_invoice
- accounting_invoicelineitem
- accounting_quote
- accounts_historicalstaff
- accounts_staff
- accounts_staff_groups
- accounts_staff_user_permissions
- auth_group
- auth_group_permissions
- auth_permission
- client_client
- client_clientcontact
- client_supplierpickupaddress
- django_apscheduler_djangojob
- django_apscheduler_djangojobexecution
- django_content_type
- django_migrations
- django_session
- django_site
- job_costline
- job_costset
- job_historicaljob
- job_job
- job_job_people
- job_jobdeltarejection
- job_jobevent
- job_jobfile
- job_jobquotechat
- job_quotespreadsheet
- process_form
- process_formentry
- process_historicalform
- process_historicalformentry
- process_historicalprocedure
- process_procedure
- purchasing_purchaseorder
- purchasing_purchaseorderevent
- purchasing_purchaseorderline
- purchasing_purchaseordersupplierquote
- purchasing_stock
- quoting_productparsingmapping
- quoting_scrapejob
- quoting_supplierpricelist
- quoting_supplierproduct
- workflow_aiprovider
- workflow_apperror
- workflow_companydefaults
- workflow_serviceapikey
- workflow_xeroaccount
- workflow_xeroerror
- workflow_xerojournal
- workflow_xerojournallineitem
- workflow_xeropayitem
- workflow_xeropayrun
- workflow_xeropayslip
- workflow_xerosynccursor
- workflow_xerotoken

---

_Generated by [codesight](https://github.com/Houseofmvps/codesight) — see your codebase clearly_