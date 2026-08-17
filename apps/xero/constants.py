"""Constants used by the Xero API integration."""

from django.core.cache import BaseCache, caches

# Cache key for the active app's resolved Xero tenant id. Read by
# auth.get_tenant_id and xero_sync_service; INVALIDATED by
# active_app.swap_active and active_app.wipe_tokens_and_quota — without
# that invalidation the cache can pin the prior app's tenant id under
# the new app's credentials.
TENANT_ID_CACHE_KEY = "xero_tenant_id"


def tenant_cache() -> BaseCache:
    """Return the cache holding TENANT_ID_CACHE_KEY, which must span processes.

    Opus: On the default (per-process) cache the invalidation above only clears the
    process that ran it, while the entry itself keeps Django's default 300s
    timeout. A Celery worker could therefore go on resolving the PREVIOUS
    tenant for up to five minutes after an organisation swap — and on the
    payroll path that means writing timesheets into the wrong Xero
    organisation. restore-prod-to-nonprod performs exactly that swap.

    Opus: Defined beside the key rather than at each call site: the reader and the
    three invalidators live in four modules, and they only work while all four
    agree on which cache holds it.
    """
    return caches["shared"]


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
