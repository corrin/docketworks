# Database

> **Navigation aid.** Schema shapes and field types extracted via AST. Read the actual schema source files before writing migrations or query logic.

**unknown** — 61 models

### accounting_bill

fk: xero_id, client_id, xero_tenant_id

- `id`: uuid _(required)_
- `xero_id`: uuid _(required, fk)_
- `number`: varchar _(required)_
- `date`: date _(required)_
- `due_date`: date
- `status`: varchar _(required)_
- `total_excl_tax`: numeric(10
- `amount_due`: numeric(10
- `xero_last_modified`: timestamp with time zone _(required)_
- `raw_json`: jsonb _(required)_
- `client_id`: uuid _(required, fk)_
- `django_created_at`: timestamp with time zone _(required)_
- `django_updated_at`: timestamp with time zone _(required)_
- `tax`: numeric(10
- `total_incl_tax`: numeric(10
- `xero_last_synced`: timestamp with time zone
- `xero_tenant_id`: character varying(255 _(fk)_

### accounting_billlineitem

fk: xero_line_id, account_id, bill_id

- `id`: uuid _(required)_
- `xero_line_id`: uuid _(required, fk)_
- `description`: text _(required)_
- `quantity`: numeric(10
- `unit_price`: numeric(10
- `line_amount_excl_tax`: numeric(10
- `line_amount_incl_tax`: numeric(10
- `tax_amount`: numeric(10
- `account_id`: uuid _(fk)_
- `bill_id`: uuid _(required, fk)_

### accounting_creditnote

fk: xero_id, xero_tenant_id, client_id

- `id`: uuid _(required)_
- `xero_id`: uuid _(required, fk)_
- `xero_tenant_id`: varchar _(fk)_
- `number`: varchar _(required)_
- `date`: date _(required)_
- `due_date`: date
- `status`: varchar _(required)_
- `total_excl_tax`: numeric(10
- `tax`: numeric(10
- `total_incl_tax`: numeric(10
- `amount_due`: numeric(10
- `xero_last_modified`: timestamp with time zone _(required)_
- `xero_last_synced`: timestamp with time zone
- `raw_json`: jsonb _(required)_
- `django_created_at`: timestamp with time zone _(required)_
- `django_updated_at`: timestamp with time zone _(required)_
- `client_id`: uuid _(required, fk)_

### accounting_creditnotelineitem

fk: xero_line_id, account_id, credit_note_id

- `id`: uuid _(required)_
- `xero_line_id`: uuid _(required, fk)_
- `description`: text _(required)_
- `quantity`: numeric(10
- `unit_price`: numeric(10
- `line_amount_excl_tax`: numeric(10
- `line_amount_incl_tax`: numeric(10
- `tax_amount`: numeric(10
- `account_id`: uuid _(fk)_
- `credit_note_id`: uuid _(required, fk)_

### accounting_invoice

fk: xero_id, client_id, job_id, xero_tenant_id

- `id`: uuid _(required)_
- `xero_id`: uuid _(required, fk)_
- `number`: varchar _(required)_
- `date`: date _(required)_
- `due_date`: date
- `status`: varchar _(required)_
- `total_excl_tax`: numeric(10
- `amount_due`: numeric(10
- `xero_last_modified`: timestamp with time zone _(required)_
- `raw_json`: jsonb _(required)_
- `client_id`: uuid _(required, fk)_
- `django_created_at`: timestamp with time zone _(required)_
- `django_updated_at`: timestamp with time zone _(required)_
- `job_id`: uuid _(fk)_
- `online_url`: varchar
- `tax`: numeric(10
- `total_incl_tax`: numeric(10
- `xero_last_synced`: timestamp with time zone
- `xero_tenant_id`: character varying(255 _(fk)_

### accounting_invoicelineitem

fk: xero_line_id, account_id, invoice_id

- `id`: uuid _(required)_
- `xero_line_id`: uuid _(required, fk)_
- `description`: text _(required)_
- `quantity`: numeric(10
- `unit_price`: numeric(10
- `line_amount_excl_tax`: numeric(10
- `line_amount_incl_tax`: numeric(10
- `tax_amount`: numeric(10
- `account_id`: uuid _(fk)_
- `invoice_id`: uuid _(required, fk)_

### accounting_quote

fk: xero_id, xero_tenant_id, client_id, job_id

- `id`: uuid _(required)_
- `xero_id`: uuid _(required, fk)_
- `xero_tenant_id`: varchar _(fk)_
- `date`: date _(required)_
- `status`: varchar _(required)_
- `total_excl_tax`: numeric(10
- `total_incl_tax`: numeric(10
- `xero_last_modified`: timestamp with time zone
- `xero_last_synced`: timestamp with time zone _(required)_
- `online_url`: varchar
- `raw_json`: jsonb
- `client_id`: uuid _(required, fk)_
- `job_id`: uuid _(fk)_
- `number`: character varying(255

### accounts_historicalstaff

fk: history_id, history_user_id, xero_user_id

- `password`: varchar _(required)_
- `last_login`: timestamp with time zone
- `is_superuser`: boolean _(required)_
- `id`: uuid _(required)_
- `icon`: text
- `password_needs_reset`: boolean _(required)_
- `email`: varchar _(required)_
- `first_name`: varchar _(required)_
- `last_name`: varchar _(required)_
- `preferred_name`: varchar
- `wage_rate`: numeric(10
- `is_office_staff`: boolean _(required)_
- `date_joined`: timestamp with time zone _(required)_
- `hours_mon`: numeric(4
- `hours_tue`: numeric(4
- `hours_wed`: numeric(4
- `hours_thu`: numeric(4
- `hours_fri`: numeric(4
- `hours_sat`: numeric(4
- `hours_sun`: numeric(4
- `history_id`: integer _(required, fk)_
- `history_date`: timestamp with time zone _(required)_
- `history_change_reason`: varchar
- `history_type`: varchar _(required)_
- `history_user_id`: uuid _(fk)_
- `date_left`: date
- `xero_user_id`: varchar _(fk)_
- `base_wage_rate`: numeric(10

### accounts_staff

fk: xero_user_id

- `password`: varchar _(required)_
- `last_login`: timestamp with time zone
- `is_superuser`: boolean _(required)_
- `id`: uuid _(required)_
- `icon`: varchar
- `password_needs_reset`: boolean _(required)_
- `email`: varchar _(required)_
- `first_name`: varchar _(required)_
- `last_name`: varchar _(required)_
- `preferred_name`: varchar
- `wage_rate`: numeric(10
- `is_office_staff`: boolean _(required)_
- `date_joined`: timestamp with time zone _(required)_
- `hours_mon`: numeric(4
- `hours_tue`: numeric(4
- `hours_wed`: numeric(4
- `hours_thu`: numeric(4
- `hours_fri`: numeric(4
- `hours_sat`: numeric(4
- `hours_sun`: numeric(4
- `date_left`: date
- `xero_user_id`: varchar _(fk)_
- `base_wage_rate`: numeric(10

### accounts_staff_groups

fk: staff_id, group_id

- `id`: bigint _(required)_
- `staff_id`: uuid _(required, fk)_
- `group_id`: integer _(required, fk)_

### accounts_staff_user_permissions

fk: staff_id, permission_id

- `id`: bigint _(required)_
- `staff_id`: uuid _(required, fk)_
- `permission_id`: integer _(required, fk)_

### auth_group

- `id`: integer _(required)_
- `name`: varchar _(required)_

### auth_group_permissions

fk: group_id, permission_id

- `id`: bigint _(required)_
- `group_id`: integer _(required, fk)_
- `permission_id`: integer _(required, fk)_

### auth_permission

fk: content_type_id

- `id`: integer _(required)_
- `name`: varchar _(required)_
- `content_type_id`: integer _(required, fk)_
- `codename`: varchar _(required)_

### client_client

fk: xero_contact_id, xero_tenant_id, merged_into_id, xero_merged_into_id

- `id`: uuid _(required)_
- `xero_contact_id`: varchar _(fk)_
- `name`: varchar _(required)_
- `email`: varchar
- `phone`: varchar
- `address`: text
- `is_account_customer`: boolean _(required)_
- `raw_json`: jsonb
- `django_updated_at`: timestamp with time zone _(required)_
- `django_created_at`: timestamp with time zone _(required)_
- `xero_last_modified`: timestamp with time zone _(required)_
- `primary_contact_email`: varchar
- `primary_contact_name`: varchar
- `additional_contact_persons`: jsonb
- `all_phones`: jsonb
- `xero_last_synced`: timestamp with time zone
- `xero_tenant_id`: varchar _(fk)_
- `merged_into_id`: uuid _(fk)_
- `xero_archived`: boolean _(required)_
- `xero_merged_into_id`: varchar _(fk)_
- `is_supplier`: boolean _(required)_

### client_clientcontact

fk: client_id

- `id`: uuid _(required)_
- `name`: varchar _(required)_
- `email`: varchar
- `phone`: varchar
- `position`: varchar
- `is_primary`: boolean _(required)_
- `notes`: text
- `client_id`: uuid _(required, fk)_
- `is_active`: boolean _(required)_

### client_supplierpickupaddress

fk: client_id, google_place_id

- `id`: uuid _(required)_
- `name`: varchar _(required)_
- `street`: varchar _(required)_
- `city`: varchar _(required)_
- `state`: varchar
- `postal_code`: varchar
- `country`: varchar _(required)_
- `is_primary`: boolean _(required)_
- `notes`: text
- `is_active`: boolean _(required)_
- `client_id`: uuid _(required, fk)_
- `google_place_id`: varchar _(fk)_
- `latitude`: numeric(10
- `longitude`: numeric(10
- `suburb`: character varying(100

### django_apscheduler_djangojob

- `id`: varchar _(required)_
- `next_run_time`: timestamp with time zone
- `job_state`: bytes _(required)_

### django_apscheduler_djangojobexecution

fk: job_id

- `id`: bigint _(required)_
- `status`: varchar _(required)_
- `run_time`: timestamp with time zone _(required)_
- `duration`: numeric(15
- `finished`: numeric(15
- `exception`: varchar
- `traceback`: text
- `job_id`: varchar _(required, fk)_

### django_content_type

- `id`: integer _(required)_
- `app_label`: varchar _(required)_
- `model`: varchar _(required)_

### django_migrations

- `id`: bigint _(required)_
- `app`: varchar _(required)_
- `name`: varchar _(required)_
- `applied`: timestamp with time zone _(required)_

### django_session

- `session_key`: varchar _(required)_
- `session_data`: text _(required)_
- `expire_date`: timestamp with time zone _(required)_

### django_site

- `id`: integer _(required)_
- `domain`: varchar _(required)_
- `name`: varchar _(required)_

### job_costline

fk: cost_set_id, xero_expense_id, xero_time_id, xero_pay_item_id

- `id`: uuid _(required)_
- `kind`: varchar _(required)_
- `desc`: varchar _(required)_
- `quantity`: numeric(10
- `unit_cost`: numeric(10
- `unit_rev`: numeric(10
- `ext_refs`: jsonb _(required)_
- `meta`: jsonb _(required)_
- `cost_set_id`: uuid _(required, fk)_
- `xero_expense_id`: varchar _(fk)_
- `xero_last_modified`: timestamp with time zone
- `xero_last_synced`: timestamp with time zone
- `xero_time_id`: varchar _(fk)_
- `accounting_date`: date _(required)_
- `approved`: boolean _(required)_
- `xero_pay_item_id`: uuid _(fk)_

### job_costset

fk: job_id

- `id`: uuid _(required)_
- `kind`: varchar _(required)_
- `rev`: integer _(required)_
- `summary`: jsonb _(required)_
- `created`: timestamp with time zone _(required)_
- `job_id`: uuid _(required, fk)_

### job_historicaljob

fk: history_id, client_id, created_by_id, history_user_id, contact_id, latest_actual_id, latest_estimate_id, latest_quote_id, xero_project_id, xero_default_task_id, default_xero_pay_item_id

- `name`: varchar _(required)_
- `id`: uuid _(required)_
- `order_number`: varchar
- `job_number`: integer _(required)_
- `description`: text
- `quote_acceptance_date`: timestamp with time zone
- `delivery_date`: date
- `status`: varchar _(required)_
- `job_is_valid`: boolean _(required)_
- `collected`: boolean _(required)_
- `paid`: boolean _(required)_
- `charge_out_rate`: numeric(10
- `pricing_methodology`: varchar _(required)_
- `complex_job`: boolean _(required)_
- `notes`: text
- `history_id`: integer _(required, fk)_
- `history_date`: timestamp with time zone _(required)_
- `history_change_reason`: varchar
- `history_type`: varchar _(required)_
- `client_id`: uuid _(fk)_
- `created_by_id`: uuid _(fk)_
- `history_user_id`: uuid _(fk)_
- `priority`: float8 _(required)_
- `contact_id`: uuid _(fk)_
- `latest_actual_id`: uuid _(fk)_
- `latest_estimate_id`: uuid _(fk)_
- `latest_quote_id`: uuid _(fk)_
- `rejected_flag`: boolean _(required)_
- `xero_last_modified`: timestamp with time zone
- `xero_last_synced`: timestamp with time zone
- `xero_project_id`: varchar _(fk)_
- `fully_invoiced`: boolean _(required)_
- `xero_default_task_id`: varchar _(fk)_
- `speed_quality_tradeoff`: varchar _(required)_
- `price_cap`: numeric(10
- `default_xero_pay_item_id`: character _(fk)_
- `completed_at`: timestamp with time zone
- `rdti_type`: character varying(20

### job_job

fk: client_id, created_by_id, contact_id, latest_actual_id, latest_estimate_id, latest_quote_id, xero_project_id, xero_default_task_id, default_xero_pay_item_id

- `name`: varchar _(required)_
- `id`: uuid _(required)_
- `order_number`: varchar
- `job_number`: integer _(required)_
- `description`: text
- `quote_acceptance_date`: timestamp with time zone
- `delivery_date`: date
- `status`: varchar _(required)_
- `job_is_valid`: boolean _(required)_
- `collected`: boolean _(required)_
- `paid`: boolean _(required)_
- `charge_out_rate`: numeric(10
- `pricing_methodology`: varchar _(required)_
- `complex_job`: boolean _(required)_
- `notes`: text
- `client_id`: uuid _(fk)_
- `created_by_id`: uuid _(fk)_
- `priority`: float8 _(required)_
- `contact_id`: uuid _(fk)_
- `latest_actual_id`: uuid _(fk)_
- `latest_estimate_id`: uuid _(fk)_
- `latest_quote_id`: uuid _(fk)_
- `rejected_flag`: boolean _(required)_
- `xero_last_modified`: timestamp with time zone
- `xero_last_synced`: timestamp with time zone
- `xero_project_id`: varchar _(fk)_
- `fully_invoiced`: boolean _(required)_
- `xero_default_task_id`: varchar _(fk)_
- `speed_quality_tradeoff`: varchar _(required)_
- `price_cap`: numeric(10
- `default_xero_pay_item_id`: uuid _(required, fk)_
- `completed_at`: timestamp with time zone
- `rdti_type`: character varying(20

### job_job_people

fk: job_id, staff_id

- `id`: bigint _(required)_
- `job_id`: uuid _(required, fk)_
- `staff_id`: uuid _(required, fk)_

### job_jobdeltarejection

fk: change_id, job_id, staff_id

- `id`: uuid _(required)_
- `change_id`: uuid _(fk)_
- `reason`: varchar _(required)_
- `detail`: text _(required)_
- `envelope`: jsonb _(required)_
- `request_etag`: varchar _(required)_
- `request_ip`: inet
- `job_id`: uuid _(fk)_
- `staff_id`: uuid _(fk)_

### job_jobevent

fk: job_id, staff_id, change_id

- `timestamp`: timestamp with time zone _(required)_
- `event_type`: varchar _(required)_
- `description`: text _(required)_
- `job_id`: uuid _(fk)_
- `staff_id`: uuid _(fk)_
- `id`: uuid _(required)_
- `dedup_hash`: varchar
- `schema_version`: smallint _(required)_
- `change_id`: uuid _(fk)_
- `delta_before`: jsonb
- `delta_after`: jsonb
- `delta_meta`: jsonb
- `delta_checksum`: varchar _(required)_

### job_jobfile

fk: job_id

- `id`: uuid _(required)_
- `filename`: varchar _(required)_
- `file_path`: varchar _(required)_
- `mime_type`: varchar _(required)_
- `uploaded_at`: timestamp with time zone _(required)_
- `status`: varchar _(required)_
- `print_on_jobsheet`: boolean _(required)_
- `job_id`: uuid _(required, fk)_

### job_jobquotechat

fk: message_id, job_id

- `id`: uuid _(required)_
- `message_id`: varchar _(required, fk)_
- `role`: varchar _(required)_
- `content`: text _(required)_
- `timestamp`: timestamp with time zone _(required)_
- `metadata`: jsonb _(required)_
- `job_id`: uuid _(required, fk)_

### job_quotespreadsheet

fk: sheet_id, job_id

- `id`: uuid _(required)_
- `sheet_id`: varchar _(required, fk)_
- `sheet_url`: varchar
- `tab`: varchar
- `job_id`: uuid _(fk)_

### process_form

- `id`: uuid _(required)_
- `document_type`: varchar _(required)_
- `title`: varchar _(required)_
- `document_number`: varchar
- `tags`: jsonb _(required)_
- `status`: varchar _(required)_
- `form_schema`: jsonb _(required)_

### process_formentry

fk: entered_by_id, form_id, job_id, staff_id

- `id`: uuid _(required)_
- `entry_date`: date _(required)_
- `data`: jsonb _(required)_
- `is_active`: boolean _(required)_
- `entered_by_id`: uuid _(fk)_
- `form_id`: uuid _(required, fk)_
- `job_id`: uuid _(fk)_
- `staff_id`: uuid _(fk)_

### process_historicalform

fk: history_id, history_user_id

- `id`: uuid _(required)_
- `document_type`: varchar _(required)_
- `title`: varchar _(required)_
- `document_number`: varchar
- `tags`: jsonb _(required)_
- `status`: varchar _(required)_
- `form_schema`: jsonb _(required)_
- `history_id`: integer _(required, fk)_
- `history_date`: timestamp with time zone _(required)_
- `history_change_reason`: varchar
- `history_type`: varchar _(required)_
- `history_user_id`: uuid _(fk)_

### process_historicalformentry

fk: history_id, entered_by_id, form_id, history_user_id, job_id, staff_id

- `id`: uuid _(required)_
- `entry_date`: date _(required)_
- `data`: jsonb _(required)_
- `is_active`: boolean _(required)_
- `history_id`: integer _(required, fk)_
- `history_date`: timestamp with time zone _(required)_
- `history_change_reason`: varchar
- `history_type`: varchar _(required)_
- `entered_by_id`: uuid _(fk)_
- `form_id`: uuid _(fk)_
- `history_user_id`: uuid _(fk)_
- `job_id`: uuid _(fk)_
- `staff_id`: uuid _(fk)_

### process_historicalprocedure

fk: google_doc_id, history_id, history_user_id, job_id

- `id`: uuid _(required)_
- `document_type`: varchar _(required)_
- `title`: varchar _(required)_
- `document_number`: varchar
- `site_location`: varchar _(required)_
- `tags`: jsonb _(required)_
- `status`: varchar _(required)_
- `google_doc_id`: varchar _(required, fk)_
- `google_doc_url`: varchar _(required)_
- `history_id`: integer _(required, fk)_
- `history_date`: timestamp with time zone _(required)_
- `history_change_reason`: varchar
- `history_type`: varchar _(required)_
- `history_user_id`: uuid _(fk)_
- `job_id`: uuid _(fk)_

### process_procedure

fk: google_doc_id, job_id

- `id`: uuid _(required)_
- `document_type`: varchar _(required)_
- `title`: varchar _(required)_
- `document_number`: varchar
- `site_location`: varchar _(required)_
- `tags`: jsonb _(required)_
- `status`: varchar _(required)_
- `google_doc_id`: varchar _(required, fk)_
- `google_doc_url`: varchar _(required)_
- `job_id`: uuid _(fk)_

### purchasing_purchaseorder

fk: xero_id, supplier_id, job_id, xero_tenant_id, pickup_address_id, created_by_id

- `id`: uuid _(required)_
- `po_number`: varchar _(required)_
- `order_date`: date _(required)_
- `expected_delivery`: date
- `xero_id`: uuid _(fk)_
- `status`: varchar _(required)_
- `supplier_id`: uuid _(fk)_
- `xero_last_modified`: timestamp with time zone
- `xero_last_synced`: timestamp with time zone
- `online_url`: varchar
- `reference`: varchar
- `job_id`: uuid _(fk)_
- `xero_tenant_id`: varchar _(fk)_
- `raw_json`: jsonb
- `pickup_address_id`: uuid _(fk)_
- `created_by_id`: uuid _(fk)_

### purchasing_purchaseorderevent

fk: purchase_order_id, staff_id

- `id`: uuid _(required)_
- `timestamp`: timestamp with time zone _(required)_
- `description`: text _(required)_
- `purchase_order_id`: uuid _(required, fk)_
- `staff_id`: uuid _(required, fk)_

### purchasing_purchaseorderline

fk: purchase_order_id, job_id, xero_line_item_id

- `id`: uuid _(required)_
- `description`: varchar _(required)_
- `quantity`: numeric(10
- `unit_cost`: numeric(10
- `received_quantity`: numeric(10
- `purchase_order_id`: uuid _(required, fk)_
- `price_tbc`: boolean _(required)_
- `dimensions`: varchar
- `supplier_item_code`: varchar
- `raw_line_data`: jsonb
- `alloy`: varchar
- `job_id`: uuid _(fk)_
- `location`: varchar
- `metal_type`: varchar
- `specifics`: varchar
- `item_code`: varchar
- `xero_line_item_id`: uuid _(fk)_

### purchasing_purchaseordersupplierquote

fk: purchase_order_id

- `id`: uuid _(required)_
- `filename`: varchar _(required)_
- `file_path`: varchar _(required)_
- `mime_type`: varchar _(required)_
- `uploaded_at`: timestamp with time zone _(required)_
- `extracted_data`: jsonb
- `status`: varchar _(required)_
- `purchase_order_id`: uuid _(required, fk)_

### purchasing_stock

fk: job_id, source_purchase_order_line_id, source_parent_stock_id, xero_id, active_source_purchase_order_line_id

- `id`: uuid _(required)_
- `description`: varchar _(required)_
- `quantity`: numeric(10
- `unit_cost`: numeric(10
- `date`: timestamp with time zone _(required)_
- `source`: varchar _(required)_
- `location`: text _(required)_
- `metal_type`: varchar _(required)_
- `alloy`: varchar
- `specifics`: varchar
- `is_active`: boolean _(required)_
- `job_id`: uuid _(fk)_
- `source_purchase_order_line_id`: uuid _(fk)_
- `source_parent_stock_id`: uuid _(fk)_
- `item_code`: varchar
- `xero_id`: varchar _(fk)_
- `xero_last_modified`: timestamp with time zone
- `raw_json`: jsonb
- `parsed_at`: timestamp with time zone
- `parser_confidence`: numeric(3
- `parser_version`: varchar
- `xero_inventory_tracked`: boolean _(required)_
- `unit_revenue`: numeric(10
- `active_source_purchase_order_line_id`: uuid _(fk)_
- `xero_last_synced`: timestamp with time zone

### quoting_productparsingmapping

fk: validated_by_id

- `id`: uuid _(required)_
- `input_hash`: varchar _(required)_
- `input_data`: jsonb _(required)_
- `mapped_item_code`: varchar
- `mapped_description`: varchar
- `mapped_metal_type`: varchar
- `mapped_alloy`: varchar
- `mapped_specifics`: varchar
- `mapped_dimensions`: varchar
- `mapped_unit_cost`: numeric(10
- `mapped_price_unit`: varchar
- `parser_version`: varchar
- `parser_confidence`: numeric(3
- `llm_response`: jsonb
- `is_validated`: boolean _(required)_
- `validated_at`: timestamp with time zone
- `validation_notes`: text
- `validated_by_id`: uuid _(fk)_
- `item_code_is_in_xero`: boolean _(required)_
- `derived_key`: character varying(100

### quoting_scrapejob

fk: supplier_id

- `id`: uuid _(required)_
- `status`: varchar _(required)_
- `started_at`: timestamp with time zone _(required)_
- `completed_at`: timestamp with time zone
- `products_scraped`: integer _(required)_
- `products_failed`: integer _(required)_
- `error_message`: text
- `supplier_id`: uuid _(required, fk)_

### quoting_supplierpricelist

fk: supplier_id

- `id`: uuid _(required)_
- `file_name`: varchar _(required)_
- `uploaded_at`: timestamp with time zone _(required)_
- `supplier_id`: uuid _(required, fk)_

### quoting_supplierproduct

fk: variant_id, supplier_id, price_list_id

- `id`: uuid _(required)_
- `product_name`: varchar _(required)_
- `item_no`: varchar _(required)_
- `description`: text
- `specifications`: text
- `variant_id`: varchar _(required, fk)_
- `variant_width`: varchar
- `variant_length`: varchar
- `variant_price`: numeric(10
- `price_unit`: varchar
- `variant_available_stock`: integer
- `url`: varchar _(required)_
- `supplier_id`: uuid _(required, fk)_
- `price_list_id`: uuid _(required, fk)_
- `parsed_alloy`: varchar
- `parsed_at`: timestamp with time zone
- `parsed_description`: varchar
- `parsed_dimensions`: varchar
- `parsed_item_code`: varchar
- `parsed_metal_type`: varchar
- `parsed_price_unit`: varchar
- `parsed_specifics`: varchar
- `parsed_unit_cost`: numeric(10
- `parser_confidence`: numeric(3
- `parser_version`: varchar
- `mapping_hash`: varchar
- `last_scraped`: timestamp with time zone _(required)_
- `is_discontinued`: boolean _(required)_

### workflow_aiprovider

- `id`: bigint _(required)_
- `name`: varchar _(required)_
- `api_key`: varchar
- `provider_type`: varchar _(required)_
- `default`: boolean _(required)_
- `model_name`: varchar _(required)_

### workflow_apperror

fk: job_id, resolved_by_id, user_id

- `id`: uuid _(required)_
- `timestamp`: timestamp with time zone _(required)_
- `message`: text _(required)_
- `data`: jsonb
- `app`: varchar
- `file`: varchar
- `function`: varchar
- `job_id`: uuid _(fk)_
- `resolved`: boolean _(required)_
- `resolved_by_id`: uuid _(fk)_
- `resolved_timestamp`: timestamp with time zone
- `severity`: integer _(required)_
- `user_id`: uuid _(fk)_

### workflow_companydefaults

fk: xero_tenant_id, gdrive_quotes_folder_id, master_quote_template_id, xero_payroll_calendar_id, gdrive_how_we_work_folder_id, gdrive_reference_library_folder_id, gdrive_sops_folder_id, google_shared_drive_id

- `time_markup`: numeric(5
- `materials_markup`: numeric(5
- `charge_out_rate`: numeric(6
- `wage_rate`: numeric(6
- `mon_start`: time without time zone _(required)_
- `mon_end`: time without time zone _(required)_
- `tue_start`: time without time zone _(required)_
- `tue_end`: time without time zone _(required)_
- `wed_start`: time without time zone _(required)_
- `wed_end`: time without time zone _(required)_
- `thu_start`: time without time zone _(required)_
- `thu_end`: time without time zone _(required)_
- `fri_start`: time without time zone _(required)_
- `fri_end`: time without time zone _(required)_
- `company_name`: varchar _(required)_
- `last_xero_sync`: timestamp with time zone
- `last_xero_deep_sync`: timestamp with time zone
- `xero_tenant_id`: varchar _(fk)_
- `starting_po_number`: integer _(required)_
- `kpi_daily_billable_hours_amber`: numeric(5
- `kpi_daily_billable_hours_green`: numeric(5
- `kpi_daily_gp_target`: numeric(10
- `kpi_daily_shop_hours_percentage`: numeric(5
- `po_prefix`: varchar _(required)_
- `master_quote_template_url`: varchar
- `starting_job_number`: integer _(required)_
- `shop_client_name`: varchar
- `gdrive_quotes_folder_id`: varchar _(fk)_
- `gdrive_quotes_folder_url`: varchar
- `master_quote_template_id`: varchar _(fk)_
- `test_client_name`: varchar
- `address_line1`: varchar
- `address_line2`: varchar
- `city`: varchar
- `country`: varchar _(required)_
- `post_code`: varchar
- `suburb`: varchar
- `company_email`: varchar
- `company_url`: varchar
- `company_acronym`: varchar
- `xero_payroll_calendar_name`: varchar _(required)_
- `xero_shortcode`: varchar
- `xero_payroll_calendar_id`: uuid _(fk)_
- `annual_leave_loading`: numeric(5
- `financial_year_start_month`: integer _(required)_
- `kpi_job_gp_target_percentage`: numeric(5
- `kpi_daily_gp_amber`: numeric(10
- `kpi_daily_gp_green`: numeric(10
- `gdrive_how_we_work_folder_id`: varchar _(fk)_
- `gdrive_reference_library_folder_id`: varchar _(fk)_
- `gdrive_sops_folder_id`: varchar _(fk)_
- `google_shared_drive_id`: varchar _(fk)_
- `xero_payroll_start_date`: date
- `id`: bigint _(required)_
- `company_phone`: varchar
- `logo`: varchar
- `logo_wide`: varchar
- `enable_xero_sync`: boolean _(required)_

### workflow_serviceapikey

- `id`: uuid _(required)_
- `name`: varchar _(required)_
- `is_active`: boolean _(required)_
- `last_used`: timestamp with time zone

### workflow_xeroaccount

fk: xero_id, xero_tenant_id

- `id`: uuid _(required)_
- `xero_id`: uuid _(required, fk)_
- `account_code`: varchar
- `account_name`: varchar _(required)_
- `description`: text
- `account_type`: varchar
- `tax_type`: varchar
- `enable_payments`: boolean _(required)_
- `xero_last_modified`: timestamp with time zone _(required)_
- `raw_json`: jsonb _(required)_
- `django_created_at`: timestamp with time zone _(required)_
- `django_updated_at`: timestamp with time zone _(required)_
- `xero_last_synced`: timestamp with time zone
- `xero_tenant_id`: character varying(255 _(fk)_

### workflow_xeroerror

fk: apperror_ptr_id, reference_id

- `apperror_ptr_id`: uuid _(required, fk)_
- `entity`: varchar _(required)_
- `reference_id`: varchar _(required, fk)_
- `kind`: varchar _(required)_

### workflow_xerojournal

fk: xero_id, source_id, xero_tenant_id

- `id`: uuid _(required)_
- `xero_id`: uuid _(required, fk)_
- `journal_date`: date _(required)_
- `created_date_utc`: timestamp with time zone _(required)_
- `journal_number`: integer _(required)_
- `reference`: varchar
- `source_id`: uuid _(fk)_
- `source_type`: varchar
- `raw_json`: jsonb _(required)_
- `django_created_at`: timestamp with time zone _(required)_
- `django_updated_at`: timestamp with time zone _(required)_
- `xero_last_modified`: timestamp with time zone _(required)_
- `xero_last_synced`: timestamp with time zone
- `xero_tenant_id`: character varying(255 _(fk)_

### workflow_xerojournallineitem

fk: xero_line_id, account_id, journal_id

- `id`: uuid _(required)_
- `xero_line_id`: uuid _(required, fk)_
- `description`: text
- `net_amount`: numeric(10
- `gross_amount`: numeric(10
- `tax_amount`: numeric(10
- `tax_type`: varchar
- `tax_name`: varchar
- `raw_json`: jsonb _(required)_
- `django_created_at`: timestamp with time zone _(required)_
- `django_updated_at`: timestamp with time zone _(required)_
- `account_id`: uuid _(fk)_
- `journal_id`: uuid _(required, fk)_

### workflow_xeropayitem

fk: xero_id, xero_tenant_id

- `id`: uuid _(required)_
- `xero_id`: varchar _(fk)_
- `xero_tenant_id`: varchar _(fk)_
- `name`: varchar _(required)_
- `uses_leave_api`: boolean _(required)_
- `multiplier`: numeric(4
- `xero_last_modified`: timestamp with time zone
- `xero_last_synced`: timestamp with time zone

### workflow_xeropayrun

fk: xero_id, xero_tenant_id, payroll_calendar_id

- `id`: uuid _(required)_
- `xero_id`: uuid _(required, fk)_
- `xero_tenant_id`: varchar _(required, fk)_
- `payroll_calendar_id`: uuid _(fk)_
- `period_start_date`: date _(required)_
- `period_end_date`: date _(required)_
- `payment_date`: date _(required)_
- `pay_run_status`: varchar
- `pay_run_type`: varchar
- `total_cost`: numeric(12
- `total_pay`: numeric(12
- `raw_json`: jsonb _(required)_
- `xero_last_modified`: timestamp with time zone _(required)_
- `xero_last_synced`: timestamp with time zone
- `django_created_at`: timestamp with time zone _(required)_
- `django_updated_at`: timestamp with time zone _(required)_

### workflow_xeropayslip

fk: xero_id, xero_tenant_id, xero_employee_id, pay_run_id

- `id`: uuid _(required)_
- `xero_id`: uuid _(required, fk)_
- `xero_tenant_id`: varchar _(required, fk)_
- `xero_employee_id`: uuid _(required, fk)_
- `employee_name`: varchar
- `gross_earnings`: numeric(10
- `tax_amount`: numeric(10
- `net_pay`: numeric(10
- `timesheet_hours`: numeric(8
- `leave_hours`: numeric(8
- `raw_json`: jsonb _(required)_
- `xero_last_modified`: timestamp with time zone _(required)_
- `xero_last_synced`: timestamp with time zone
- `django_created_at`: timestamp with time zone _(required)_
- `django_updated_at`: timestamp with time zone _(required)_
- `pay_run_id`: uuid _(required, fk)_

### workflow_xerosynccursor

- `id`: bigint _(required)_
- `entity_key`: varchar _(required)_
- `last_modified`: timestamp with time zone _(required)_

### workflow_xerotoken

fk: tenant_id

- `id`: bigint _(required)_
- `tenant_id`: varchar _(required, fk)_
- `token_type`: varchar _(required)_
- `access_token`: text _(required)_
- `refresh_token`: text _(required)_
- `expires_at`: timestamp with time zone _(required)_
- `scope`: text _(required)_

## Schema Source Files

Read and edit these files when adding columns, creating migrations, or changing relations:

- `frontend/tests/scripts/db-backup-utils.ts` — imported by **5** files
- `/models.py` — imported by **3** files

---
_Back to [overview.md](./overview.md)_
