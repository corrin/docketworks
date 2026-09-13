"""Which handler answers which call: exact paths, nothing inferred.

A route is (method, path pattern, handler). The table is the complete list
of what the fake serves; a call that matches nothing raises rather than
answering, so a new SDK call in the application is noticed the first time an
iteration run makes it, not when a real run does.
"""

import re
from collections.abc import Callable

from xero_python.rest import RESTResponse

from apps.xero.fake import accounting, identity, payroll
from apps.xero.fake.accounting import FakeXeroUnhandledRouteError
from apps.xero.fake.http import FakeRequest

Handler = Callable[[FakeRequest, re.Match[str]], RESTResponse]

# Routes match on host and path together: the Accounting and Payroll APIs
# share a host and differ by prefix, the identity endpoint is another host.
_ACCOUNTING = "api.xero.com/api.xro/2.0"
_PAYROLL = "api.xero.com/payroll.xro/2.0"
_IDENTITY = "identity.xero.com"
_ID = r"(?P<id>[0-9a-fA-F-]{36})"


def _route(method: str, pattern: str, handler: Handler) -> tuple[str, re.Pattern[str], Handler]:
    return method, re.compile(f"^{pattern}$"), handler


ROUTES: tuple[tuple[str, re.Pattern[str], Handler], ...] = (
    _route("GET", f"{_ACCOUNTING}/Organisation", accounting.get_organisation),
    _route(
        "GET",
        f"{_ACCOUNTING}/(?P<resource>Contacts|Invoices|CreditNotes|Quotes|PurchaseOrders|Items|Accounts|TaxRates|BrandingThemes)",
        accounting.list_resource,
    ),
    _route(
        "GET",
        f"{_ACCOUNTING}/(?P<resource>Contacts|Invoices|Quotes|PurchaseOrders)/{_ID}",
        accounting.get_resource,
    ),
    _route("PUT", f"{_ACCOUNTING}/Contacts", accounting.write_contacts),
    _route("POST", f"{_ACCOUNTING}/Contacts", accounting.write_contacts),
    _route("PUT", f"{_ACCOUNTING}/Invoices", accounting.write_invoices),
    _route("POST", f"{_ACCOUNTING}/Invoices", accounting.write_invoices),
    _route("PUT", f"{_ACCOUNTING}/Quotes", accounting.write_quotes),
    _route("POST", f"{_ACCOUNTING}/Quotes", accounting.write_quotes),
    _route("POST", f"{_ACCOUNTING}/PurchaseOrders", accounting.write_purchase_orders),
    _route(
        "PUT",
        f"{_ACCOUNTING}/(?P<resource>Invoices|Quotes)/{_ID}/History",
        accounting.write_history,
    ),
    _route(
        "PUT",
        f"{_ACCOUNTING}/Invoices/{_ID}/Attachments/(?P<name>[^/]+)",
        accounting.write_attachment,
    ),
    _route("POST", f"{_ACCOUNTING}/Items", accounting.write_items),
    _route(
        "GET",
        f"{_PAYROLL}/(?P<resource>Employees|LeaveTypes|EarningsRates|PayRuns)",
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
