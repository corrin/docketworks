"""The single NinjaAPI instance.

One router per domain app, mounted at the exact v1 URL prefixes. Endpoints
declare their own auth (CookieJWTAuth or auth=None for the ADR 0002
allowlist); the LoginRequiredMiddleware is defense-in-depth.
"""

from ninja import NinjaAPI

from apps.accounts.api import router as accounts_router
from apps.core.api import router as core_router
from apps.core.envelope import register_exception_handlers
from apps.crm.api import router as crm_router

api = NinjaAPI(
    title="Docketworks API",
    version="2.0.0",
)

register_exception_handlers(api)

api.add_router("/", core_router)
api.add_router("/accounts/", accounts_router)
api.add_router("/crm/", crm_router)
