"""Constants used by the Xero API integration."""

from decimal import Decimal

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

    Defined beside the key rather than at each call site: the reader and the
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

#: Xero's documented maximum number of objects in one batch create or update;
#: every batched write (contact seeding, document seeding, contact archiving)
#: slices by it.
XERO_BATCH_SIZE = 50

#: The two contact statuses Xero documents. GDPRREQUEST also exists and is
#: deliberately not accepted: it should never occur on an NZ organisation, and
#: treating an erased contact as either would be wrong — fail loudly and
#: decide its handling then.
XERO_CONTACT_STATUSES = ("ACTIVE", "ARCHIVED")

#: Seconds slept between calls on the PAYROLL endpoints, which rate-limit harder
#: than the accounting ones and take several mutating calls per employee. v1
#: measured 3s as the interval that survives a full staff list without
#: throttling.
#:
#: Opus: One definition, for the same reason SLEEP_TIME above has one. This was
#: declared separately in `payroll_push` and `payroll_leave`, with near-identical
#: comments — two copies of one policy value, either free to drift.
#:
#: OPEN QUESTION, deliberately not settled here: whether this manual layer should
#: exist at all. `payroll_employees` argues it should not — `RateLimitedRESTClient`
#: already enforces a minimum gap and absorbs a minute-limit 429 by sleeping
#: Retry-After and retrying, so a second layer on top is "our own invented
#: constraint over a mechanism that already handles it". Deleting it is a live
#: behaviour change to payroll pacing and needs one clean integration run to
#: settle, which the tenant's exhausted daily quota prevented.
PAYROLL_SLEEP_SECONDS = 3

#: The precision payroll units are held and compared at, on BOTH payroll
#: surfaces: timesheet lines and leave periods are quantized to it before any
#: equality decides whether Xero already holds the right hours.
#:
#: Fable: One definition, for the same reason SLEEP_TIME above has one. This
#: was declared as `payroll_push.UNIT_PRECISION` and
#: `payroll_leave.LEAVE_UNIT_PRECISION` — two names for one policy value, held
#: equal only by a comment promising they match.
PAYROLL_UNIT_PRECISION = Decimal("0.001")

# Xero sometimes returns this instead of a real document id on create; it must
# never be stored or treated as an existing document.
ZERO_UUID = "00000000-0000-0000-0000-000000000000"
