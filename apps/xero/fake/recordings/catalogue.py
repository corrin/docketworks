"""The routes the fake serves, captured from the real tenant in one pass.

One function drives both the recorder (``scripts/ops/record_xero_wire.py``)
and the drift test, so what gets written and what gets checked cannot
diverge. It calls the typed SDK methods the application calls — never a
hand-built URL — and reads the raw bytes off the transport, which is the one
place the wire body exists before the SDK deserialises it.

Ids are chosen from the first page of each listing rather than pinned: the
demo organisation is replaced roughly monthly and every id changes with it,
and a recording that named one would 404 on the first drift check after.
"""

import contextlib
import json
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import uuid4

from urllib3 import HTTPResponse
from xero_python.accounting import AccountingApi
from xero_python.api_client import ApiClient
from xero_python.api_client.configuration import Configuration
from xero_python.exceptions import ApiException
from xero_python.payrollnz import PayrollNzApi
from xero_python.rest import RESTResponse

from apps.accounts.models import StaffPayrollTerm
from apps.xero.client import RateLimitedRESTClient
from apps.xero.fake.wire import Json

# A recording keeps two elements of any top-level list: the shape of an
# element is what the fake and the drift check read, and a full page of
# contacts is a hundred copies of it.
LIST_ELEMENTS_KEPT = 2

# Replaced before anything is written: the dev tenant is a restore of a real
# business, and a shape needs none of these values. The organisation's own
# name is kept, because the fake suffixes it into the run banner.
SCRUBBED_KEYS = frozenset(
    {
        "FirstName",
        "LastName",
        "EmailAddress",
        "PhoneNumber",
        "AddressLine1",
        "AddressLine2",
        "AddressLine3",
        "AddressLine4",
        "AttentionTo",
        "TaxNumber",
        "BankAccountDetails",
        "RegistrationNumber",
        "LegalName",
        "firstName",
        "lastName",
        "email",
        "dateOfBirth",
        "phoneNumber",
        "addressLine1",
        "addressLine2",
        "city",
        "suburb",
        "postCode",
        "accountNumber",
        "accountName",
        "bacsHash",
    }
)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class Capture:
    """One route's wire response, as recorded or as re-fetched."""

    name: str
    method: str
    path: str
    query: dict[str, str]
    status: int
    content_type: str
    content_disposition: str | None
    body: Json
    truncated: bool = field(default=False)


class _TransportTap(RateLimitedRESTClient):
    """The paced client, remembering the last request and its raw answer."""

    def __init__(self, configuration: Configuration) -> None:
        super().__init__(configuration)
        self.last_method = ""
        self.last_url = ""
        self.last_query: dict[str, str] = {}
        self.last_status = 0
        self.last_headers: dict[str, str] = {}
        self.last_data = b""

    def request(  # noqa: PLR0913, PLR0917 -- the SDK base-class signature; not ours to shrink
        self,
        method: str,
        url: str,
        query_params: object = None,
        headers: object = None,
        body: object = None,
        post_params: object = None,
        _preload_content: bool = True,
        _request_timeout: object = None,
    ) -> RESTResponse | HTTPResponse:
        self.last_method = method
        self.last_url = url
        self.last_query = _query_of(query_params)
        try:
            response = super().request(
                method,
                url,
                query_params=query_params,
                headers=headers,
                body=body,
                post_params=post_params,
                _preload_content=_preload_content,
                _request_timeout=_request_timeout,
            )
        except ApiException as exc:
            if exc.status is None or exc.body is None:
                # Not an answer from Xero at all (the SDK raises the same
                # class for a transport failure); nothing to record.
                raise
            self.last_status = exc.status
            self.last_headers = dict(exc.headers) if exc.headers else {}
            self.last_data = exc.body
            raise
        self.last_status = response.status
        self.last_headers = dict(self._headers_of(response))
        self.last_data = response.data
        return response


def _query_of(query_params: object) -> dict[str, str]:
    if query_params is None:
        return {}
    if isinstance(query_params, Mapping):
        return {str(key): str(value) for key, value in query_params.items()}
    if isinstance(query_params, list):
        return {str(key): str(value) for key, value in query_params}
    raise TypeError(f"unexpected query_params shape: {type(query_params).__name__}")


def capture_all(client: ApiClient, tenant_id: str) -> Iterator[Capture]:
    """Drive every route the fake serves and yield each raw answer, scrubbed."""
    tap = _TransportTap(client.configuration)
    client.rest_client = tap
    accounting = AccountingApi(client)
    payroll = PayrollNzApi(client)

    yield _record(tap, "organisation", lambda: accounting.get_organisations(tenant_id))
    yield _record(tap, "tax_rates", lambda: accounting.get_tax_rates(tenant_id))
    yield _record(tap, "branding_themes", lambda: accounting.get_branding_themes(tenant_id))
    yield _record(tap, "accounts", lambda: accounting.get_accounts(tenant_id))
    yield _record(tap, "items", lambda: accounting.get_items(tenant_id))

    contacts = _record(
        tap,
        "contacts_page",
        lambda: accounting.get_contacts(
            tenant_id, page=1, page_size=LIST_ELEMENTS_KEPT, include_archived=True
        ),
    )
    yield contacts
    contact = _element(contacts, "Contacts")
    yield _record(
        tap, "contact", lambda: accounting.get_contact(tenant_id, _text(contact, "ContactID"))
    )
    yield _record(
        tap,
        "contacts_by_name",
        lambda: accounting.get_contacts(tenant_id, where=f'Name=="{_text(contact, "Name")}"'),
    )

    invoices = _record(
        tap,
        "invoices_page",
        lambda: accounting.get_invoices(
            tenant_id, where='Type=="ACCREC"', page=1, page_size=LIST_ELEMENTS_KEPT
        ),
    )
    yield invoices
    invoice_id = _text(_element(invoices, "Invoices"), "InvoiceID")
    yield _record(tap, "invoice", lambda: accounting.get_invoice(tenant_id, invoice_id))
    yield _record(
        tap, "invoice_history", lambda: accounting.get_invoice_history(tenant_id, invoice_id)
    )
    yield _record(
        tap,
        "bills_page",
        lambda: accounting.get_invoices(
            tenant_id, where='Type=="ACCPAY"', page=1, page_size=LIST_ELEMENTS_KEPT
        ),
    )
    yield _record(
        tap,
        "credit_notes_page",
        lambda: accounting.get_credit_notes(tenant_id, page=1, page_size=LIST_ELEMENTS_KEPT),
    )
    yield _record(tap, "invoice_not_found", lambda: accounting.get_invoice(tenant_id, str(uuid4())))

    quotes = _record(tap, "quotes_page", lambda: accounting.get_quotes(tenant_id, page=1))
    yield quotes
    quote_id = _text(_element(quotes, "Quotes"), "QuoteID")
    yield _record(tap, "quote", lambda: accounting.get_quote(tenant_id, quote_id))
    yield _record(tap, "quote_pdf", lambda: accounting.get_quote_as_pdf(tenant_id, quote_id))

    orders = _record(
        tap,
        "purchase_orders_page",
        lambda: accounting.get_purchase_orders(tenant_id, page=1, page_size=LIST_ELEMENTS_KEPT),
    )
    yield orders
    yield _record(
        tap,
        "purchase_order",
        lambda: accounting.get_purchase_order(
            tenant_id, _text(_element(orders, "PurchaseOrders"), "PurchaseOrderID")
        ),
    )

    employees = _record(tap, "employees_page", lambda: payroll.get_employees(tenant_id, page=1))
    yield employees
    # The employee for the detail routes comes from the mirror, not the
    # listing's first element: an employee with no salary line or working
    # pattern answers those routes with an empty list, which records nothing.
    employee_id, pattern_id = _employee_with_terms(tenant_id)
    yield _record(tap, "employee", lambda: payroll.get_employee(tenant_id, employee_id))
    yield _record(
        tap,
        "salary_and_wages",
        lambda: payroll.get_employee_salary_and_wages(tenant_id, employee_id),
    )
    yield _record(
        tap,
        "working_patterns",
        lambda: payroll.get_employee_working_patterns(tenant_id, employee_id),
    )
    yield _record(
        tap,
        "working_pattern",
        lambda: payroll.get_employee_working_pattern(tenant_id, employee_id, pattern_id),
    )
    yield _record(tap, "employees_past_end", lambda: payroll.get_employees(tenant_id, page=9999))
    yield _record(tap, "leave_types", lambda: payroll.get_leave_types(tenant_id))
    yield _record(tap, "earnings_rates", lambda: payroll.get_earnings_rates(tenant_id))
    pay_runs = _record(tap, "pay_runs", lambda: payroll.get_pay_runs(tenant_id))
    yield pay_runs
    yield _record(
        tap,
        "pay_slips",
        lambda: payroll.get_pay_slips(tenant_id, _text(_element(pay_runs, "payRuns"), "payRunID")),
    )


def _employee_with_terms(tenant_id: str) -> tuple[str, str]:
    """Return one linked employee and a working pattern of theirs, from the mirror."""
    term = (
        StaffPayrollTerm.objects.filter(
            staff__xero_tenant_id=tenant_id,
            staff__xero_user_id__isnull=False,
            xero_salary_wage_id__isnull=False,
            xero_working_pattern_id__isnull=False,
        )
        .select_related("staff")
        .order_by("staff__xero_user_id", "effective_from")
        .first()
    )
    if term is None:
        raise ValueError(
            f"no staff linked to tenant {tenant_id} carries both a salary line and a "
            "working pattern; run the payroll sync first"
        )
    if term.staff.xero_user_id is None or term.xero_working_pattern_id is None:
        raise ValueError("the filtered term lost its ids")
    return term.staff.xero_user_id, term.xero_working_pattern_id


def _record(tap: _TransportTap, name: str, call: Callable[[], object]) -> Capture:
    """Make the call (its own error responses included) and read the tap."""
    # deliberate-swallow: a 404 or a past-the-end 400 is a route the fake
    # serves too, and the tap has already kept the body the SDK raised on.
    with contextlib.suppress(ApiException):
        call()
    return _capture(name, tap)


def _capture(name: str, tap: _TransportTap) -> Capture:
    content_type = tap.last_headers.get("Content-Type", "")
    if "application/json" in content_type:
        body: Json = _scrub(json.loads(tap.last_data, parse_float=Decimal))
        body, truncated = _truncate_lists(body)
    else:
        # A PDF's bytes are not a shape; its headers are what the SDK reads.
        body, truncated = None, False
    return Capture(
        name=name,
        method=tap.last_method,
        path=tap.last_url.removeprefix("https://api.xero.com"),
        query=tap.last_query,
        status=tap.last_status,
        content_type=content_type,
        content_disposition=tap.last_headers.get("Content-Disposition"),
        body=body,
        truncated=truncated,
    )


def _scrub(value: Json) -> Json:
    if isinstance(value, dict):
        return {
            key: _placeholder(key, item) if key in SCRUBBED_KEYS else _scrub(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def _placeholder(key: str, value: Json) -> Json:
    if not isinstance(value, str) or value == "":
        return value
    if _ISO_DATE.match(value):
        # The date changes; whatever follows it (a T00:00:00, or nothing) is
        # the wire format, which is the thing being recorded.
        return "1990-01-01" + value[10:]
    return f"{key}-scrubbed"


def _truncate_lists(body: Json) -> tuple[Json, bool]:
    if not isinstance(body, dict):
        return body, False
    truncated = False
    kept: dict[str, Json] = {}
    for key, value in body.items():
        if isinstance(value, list) and len(value) > LIST_ELEMENTS_KEPT:
            kept[key] = value[:LIST_ELEMENTS_KEPT]
            truncated = True
        else:
            kept[key] = value
    return kept, truncated


def _element(capture: Capture, key: str) -> dict[str, Json]:
    body = capture.body
    if not isinstance(body, dict) or not isinstance(body.get(key), list):
        raise TypeError(f"{capture.name}: no {key} list in the response")
    items = body[key]
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise ValueError(f"{capture.name}: {key} is empty; the tenant holds nothing to record")
    return items[0]


def _text(element: Mapping[str, Json], key: str) -> str:
    value = element.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"expected a non-empty {key}, got {value!r}")
    return value
