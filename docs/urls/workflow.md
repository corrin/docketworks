# Workflow URLs Documentation

<!-- This file is auto-generated. To regenerate, run: python scripts/generate_url_docs.py -->

### App-Errors Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/app-errors/` | `app_error_view.AppErrorListAPIView` | `app-error-list` | API view for listing application errors. |
| `/app-errors/<uuid:pk>/` | `app_error_view.AppErrorDetailAPIView` | `app-error-detail` | API view for retrieving a single application error. |
| `/app-errors/grouped/` | `app_error_grouped_view.AppErrorGroupedListView` | `app-error-grouped-list` | No description available |
| `/app-errors/grouped/mark_resolved/` | `app_error_grouped_view.AppErrorGroupedMarkResolvedView` | `app-error-grouped-mark-resolved` | No description available |
| `/app-errors/grouped/mark_unresolved/` | `app_error_grouped_view.AppErrorGroupedMarkUnresolvedView` | `app-error-grouped-mark-unresolved` | No description available |

### Build-Id Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/build-id/` | `build_id_view.BuildIdAPIView` | `build_id` | Return the git SHA of the running backend process. |

### Company-Defaults Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/company-defaults/schema/` | `company_defaults_schema_api.CompanyDefaultsSchemaAPIView` | `api_company_defaults_schema` | API endpoint that returns field metadata for CompanyDefaults. |
| `/company-defaults/upload-logo/` | `company_defaults_logo_api.CompanyDefaultsLogoAPIView` | `api_company_defaults_upload_logo` | API view for uploading and deleting company logo images. |

### Disable_Cache Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/disable_cache/` | `cache_control_api.DisableCacheAPIView` | `disable_cache` | No description available |

### Enable_Cache Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/enable_cache/` | `cache_control_api.EnableCacheAPIView` | `enable_cache` | No description available |

### Reports
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/reports/job-movement/` | `JobMovementMetricsView` | `accounting:api_job_movement` | API endpoint for job movement and conversion metrics. |
| `/reports/payroll-date-range/` | `PayrollDateRangeView` | `accounting:api_payroll_date_range` | Snap arbitrary dates to pay-period-aligned week boundaries. |
| `/reports/payroll-reconciliation/` | `PayrollReconciliationReport` | `accounting:api_payroll_reconciliation` | Weekly payroll reconciliation: Xero pay runs vs JM time CostLines. |
| `/reports/profit-and-loss/` | `CompanyProfitAndLossReport` | `accounting:api_profit_and_loss` | No description available |

### Rest Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/rest/app-errors/` | `app_error_view.AppErrorRestListView` | `app-error-rest-list` | REST-style view that exposes AppError telemetry for admin monitoring. |

### System
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/company-defaults/` | `company_defaults_api.CompanyDefaultsAPIView` | `api_company_defaults` | API view for managing company default settings. |
| `/enums/<str:enum_name>/` | `get_enum_choices` | `get_enum_choices` | API endpoint to get enum choices. |
| `/xero-errors/` | `xero_view.XeroErrorListAPIView` | `xero-error-list` | API view for listing Xero synchronization errors. |
| `/xero-errors/<uuid:pk>/` | `xero_view.XeroErrorDetailAPIView` | `xero-error-detail` | API view for retrieving a single Xero synchronization error. |

### Xero Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/xero/authenticate/` | `xero_view.xero_authenticate` | `api_xero_authenticate` | Xero Authentication (Step 1: Redirect user to Xero OAuth2 login) |
| `/xero/create_invoice/<uuid:job_id>/` | `xero_view.create_xero_invoice` | `create_invoice` | Creates an Invoice in Xero for a given job. |
| `/xero/create_purchase_order/<uuid:purchase_order_id>/` | `xero_view.create_xero_purchase_order` | `create_xero_purchase_order` | Creates or updates a Purchase Order in Xero for a given purchase order. |
| `/xero/create_quote/<uuid:job_id>/` | `xero_view.create_xero_quote` | `create_quote` | Creates a quote in Xero for a given job. |
| `/xero/delete_invoice/<uuid:job_id>/` | `xero_view.delete_xero_invoice` | `delete_invoice` | Deletes a specific invoice in Xero for a given job, identified by its Xero ID. |
| `/xero/delete_purchase_order/<uuid:purchase_order_id>/` | `xero_view.delete_xero_purchase_order` | `delete_xero_purchase_order` | Deletes a Purchase Order in Xero. |
| `/xero/delete_quote/<uuid:job_id>/` | `xero_view.delete_xero_quote` | `delete_quote` | Deletes a quote in Xero for a given job. |
| `/xero/disconnect/` | `xero_view.xero_disconnect` | `xero_disconnect` | Disconnect from Xero by clearing tokens on the active XeroApp. |
| `/xero/oauth/callback/` | `xero_view.xero_oauth_callback` | `xero_oauth_callback` | OAuth callback |
| `/xero/ping/` | `xero_view.xero_ping` | `xero_ping` | Simple endpoint to check if the user is authenticated with Xero. |
| `/xero/sync-info/` | `xero_view.get_xero_sync_info` | `xero_sync_info` | Get current sync status and last sync times for all entities in ENTITY_CONFIGS. |
| `/xero/sync-stream/` | `xero_view.stream_xero_sync` | `stream_xero_sync` | HTTP endpoint to serve an EventSource stream of Xero sync events. |
| `/xero/sync/` | `xero_view.start_xero_sync` | `synchronise_xero_data` | View function to start a Xero sync as a background task. |
| `/xero/webhook/` | `XeroWebhookView` | `xero_webhook` | Accept Xero webhook deliveries and dispatch each event to Celery. |

### Xero-Errors Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/xero-errors/grouped/` | `app_error_grouped_view.XeroErrorGroupedListView` | `xero-error-grouped-list` | No description available |
| `/xero-errors/grouped/mark_resolved/` | `app_error_grouped_view.XeroErrorGroupedMarkResolvedView` | `xero-error-grouped-mark-resolved` | No description available |
| `/xero-errors/grouped/mark_unresolved/` | `app_error_grouped_view.XeroErrorGroupedMarkUnresolvedView` | `xero-error-grouped-mark-unresolved` | No description available |
