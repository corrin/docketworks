"""Which handler answers which call: exact paths, nothing inferred.

A route is (method, path pattern, handler). The table is the complete list
of what the fake serves; a call that matches nothing raises rather than
answering, so a new SDK call in the application is noticed the first time an
iteration run makes it, not when a real run does.
``tests/test_every_call_is_routed.py`` holds the table to the calls the
application makes.
"""

import re
from collections.abc import Callable

from xero_python.rest import RESTResponse

from apps.xero.fake import accounting, identity, payroll
from apps.xero.fake.http import FakeRequest, FakeXeroUnhandledRouteError
from apps.xero.fake.limits import rate_limit_refusal

Handler = Callable[[FakeRequest, re.Match[str]], RESTResponse]

# Routes match on host and path together: the Accounting and Payroll APIs
# share a host and differ by prefix, the identity endpoint is another host.
_ACCOUNTING = "api.xero.com/api.xro/2.0"
_PAYROLL = "api.xero.com/payroll.xro/2.0"
_IDENTITY = "identity.xero.com"
_ID = r"(?P<id>[0-9a-fA-F-]{36})"
_DOCUMENTS = "Invoices|CreditNotes|Quotes|PurchaseOrders"


def _route(method: str, pattern: str, handler: Handler) -> tuple[str, re.Pattern[str], Handler]:
    return method, re.compile(f"^{pattern}$"), handler


ROUTES: tuple[tuple[str, re.Pattern[str], Handler], ...] = (
    _route("GET", f"{_ACCOUNTING}/Organisation", accounting.get_organisation),
    _route(
        "GET",
        f"{_ACCOUNTING}/(?P<resource>Contacts|{_DOCUMENTS}|Items|Accounts|TaxRates|BrandingThemes)",
        accounting.list_resource,
    ),
    _route(
        "GET",
        f"{_ACCOUNTING}/(?P<resource>Contacts|{_DOCUMENTS}|Items|Accounts)/{_ID}",
        accounting.get_resource,
    ),
    _route(
        "GET", f"{_ACCOUNTING}/(?P<resource>{_DOCUMENTS})/{_ID}/History", accounting.get_history
    ),
    _route("PUT", f"{_ACCOUNTING}/Contacts", accounting.write_contacts),
    _route("POST", f"{_ACCOUNTING}/Contacts", accounting.write_contacts),
    _route("POST", f"{_ACCOUNTING}/Contacts/{_ID}", accounting.write_contacts),
    _route("PUT", f"{_ACCOUNTING}/Invoices", accounting.write_invoices),
    _route("POST", f"{_ACCOUNTING}/Invoices", accounting.write_invoices),
    _route("PUT", f"{_ACCOUNTING}/Quotes", accounting.write_quotes),
    _route("POST", f"{_ACCOUNTING}/Quotes", accounting.write_quotes),
    _route("PUT", f"{_ACCOUNTING}/PurchaseOrders", accounting.write_purchase_orders),
    _route("POST", f"{_ACCOUNTING}/PurchaseOrders", accounting.write_purchase_orders),
    _route(
        "PUT", f"{_ACCOUNTING}/(?P<resource>{_DOCUMENTS})/{_ID}/History", accounting.write_history
    ),
    _route(
        "PUT",
        f"{_ACCOUNTING}/(?P<resource>{_DOCUMENTS})/{_ID}/Attachments/(?P<name>[^/]+)",
        accounting.write_attachment,
    ),
    _route("PUT", f"{_ACCOUNTING}/Items", accounting.write_items),
    _route("POST", f"{_ACCOUNTING}/Items", accounting.write_items),
    _route(
        "GET",
        f"{_PAYROLL}/(?P<resource>Employees|LeaveTypes|EarningsRates|PayRuns|PayRunCalendars)",
        payroll.list_payroll_resource,
    ),
    _route("GET", f"{_PAYROLL}/Employees/{_ID}", payroll.get_employee),
    _route("GET", f"{_PAYROLL}/Employees/{_ID}/SalaryAndWages", payroll.list_salary_and_wages),
    _route("GET", f"{_PAYROLL}/Employees/{_ID}/Working-Patterns", payroll.list_working_patterns),
    _route(
        "GET",
        f"{_PAYROLL}/Employees/{_ID}/Working-Patterns/(?P<pattern>[0-9a-fA-F-]{{36}})",
        payroll.get_working_pattern,
    ),
    _route("GET", f"{_PAYROLL}/PaySlips", payroll.list_pay_slips),
    _route("POST", f"{_IDENTITY}/connect/token", identity.answer_refresh),
)


def dispatch(request: FakeRequest) -> RESTResponse:
    """Answer the request from the first route that matches it, or refuse."""
    if request.host == "api.xero.com":
        # Xero meters the tenant-scoped hosts and not identity (limits.py).
        refusal = rate_limit_refusal()
        if refusal is not None:
            return refusal
    for method, pattern, handler in ROUTES:
        if method != request.method:
            continue
        match = pattern.match(f"{request.host}{request.path}")
        if match is not None:
            return handler(request, match)
    raise FakeXeroUnhandledRouteError(
        f"the fake Xero has no route for {request.method} {request.host}{request.path}; "
        "add it to apps/xero/fake/router.py, from a recording"
    )


def routes_served() -> frozenset[tuple[str, str]]:
    """Every (method, host and path pattern) the table answers, for the static gate."""
    return frozenset((method, pattern.pattern) for method, pattern, _handler in ROUTES)
