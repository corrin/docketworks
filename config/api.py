"""The single NinjaAPI instance.

One router per domain app, mounted at the exact v1 URL prefixes. Endpoints
declare their own auth (CookieJWTAuth or auth=None for the ADR 0002
allowlist); the LoginRequiredMiddleware is defense-in-depth.
"""

from ninja import NinjaAPI

from apps.accounting.api import router as accounting_router
from apps.accounts.api import router as accounts_router
from apps.company.api import router as company_router
from apps.core.api import router as core_router
from apps.core.envelope import register_exception_handlers
from apps.crm.api import router as crm_router
from apps.job.api import router as job_router
from apps.purchasing.api import router as purchasing_router
from apps.quoting.api import router as quoting_router
from apps.timesheet.api import router as timesheet_router

api = NinjaAPI(
    title="Docketworks API",
    version="2.0.0",
)

register_exception_handlers(api)

api.add_router("/", core_router)
api.add_router("/accounting/", accounting_router)
api.add_router("/accounts/", accounts_router)
api.add_router("/crm/", crm_router)
# Company and job router paths carry their own prefixes (/companies/, /people/,
# /job/..., and v1-exact data-quality paths), so they mount at the root.
api.add_router("/", company_router)
api.add_router("/", job_router)
# Timesheet paths carry their own prefixes (/timesheets/... and the v1-exact
# /job/workshop/timesheets/), so this mounts at the root too.
api.add_router("/", timesheet_router)
api.add_router("/", purchasing_router)
api.add_router("/", quoting_router)
