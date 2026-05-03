"""Constants used by the Xero API integration."""

# Cache key for the active app's resolved Xero tenant id. Read by
# auth.get_tenant_id and xero_sync_service; INVALIDATED by
# active_app.swap_active and active_app.wipe_tokens_and_quota — without
# that invalidation the cache can pin the prior app's tenant id under
# the new app's credentials.
TENANT_ID_CACHE_KEY = "xero_tenant_id"

XERO_SCOPES = [
    "offline_access",
    "openid",
    "profile",
    "email",
    "accounting.contacts",
    "accounting.invoices",
    "accounting.attachments",
    "accounting.settings",
    "projects",
    "payroll.timesheets",
    "payroll.payruns",
    "payroll.payslip",
    "payroll.employees",
    "payroll.settings",
]
