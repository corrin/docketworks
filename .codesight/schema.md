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
