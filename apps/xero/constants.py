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
    "payroll.timesheets.read",
    "payroll.payruns",
    "payroll.payruns.read",
    "payroll.payslip",
    "payroll.payslip.read",
    "payroll.employees",
    "payroll.employees.read",
    "payroll.settings",
    "payroll.settings.read",
]

# Seconds slept after every Xero API call — the coarse half of rate limiting
# (RateLimitedRESTClient's pacing is the precise half). One definition: this
# is a policy value that must not drift between the sync loop, transforms,
# webhook single-syncs, contact push and stock push.
SLEEP_TIME = 1

# Xero sometimes returns this instead of a real document id on create; it must
# never be stored or treated as an existing document.
ZERO_UUID = "00000000-0000-0000-0000-000000000000"
