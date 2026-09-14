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
from datetime import date
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
from apps.xero.fake.http import query_dict
from apps.xero.fake.wire import Json

# A recording keeps two elements of any top-level list: the shape of an
# element is what the fake and the drift check read, and a full page of
# contacts is a hundred copies of it. The reference lists are the exception:
# the fake serves them whole (every tax rate prices a line; every theme is
# selectable), so those recordings keep every element.
LIST_ELEMENTS_KEPT = 2
UNTRUNCATED = frozenset({"tax_rates", "branding_themes", "leave_types", "earnings_rates"})

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
    #: The quota and rate-limit headers Xero sent, when it sent them.
    headers: dict[str, str] = field(default_factory=dict)


#: The headers a recording keeps: the two quota meters every tenant-scoped
#: answer carries, and the two a 429 adds. Nothing else in a header is contract.
RECORDED_HEADERS = (
    "X-DayLimit-Remaining",
    "X-MinLimit-Remaining",
    "Retry-After",
    "X-Rate-Limit-Problem",
)
#: Xero allows 60 calls a minute per app and tenant; a burst past that is the
#: only way to record its 429, and the only capture that spends more than one call.
BURST_CALLS = 70


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
        #: While a burst is being recorded the paced client's minute-limit
        #: retry must not run: the 429 IS the answer being captured.
        self.recording_a_refusal = False

    def _handle_rate_limit(self, exc: ApiException) -> None:
        if self.recording_a_refusal:
            raise exc
        super()._handle_rate_limit(exc)

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
        self.last_query = query_dict(query_params)
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


def capture_all(
    client: ApiClient, tenant_id: str, only: frozenset[str] | None = None
) -> Iterator[Capture]:
    """Drive every route the fake serves and yield each raw answer, scrubbed.

    ``only`` names a subset to re-record; the routes a subset depends on
    for an id are still called, because the call is how the id is found.
    """
    tap = _TransportTap(client.configuration)
    client.rest_client = tap
    accounting = AccountingApi(client)
    payroll = PayrollNzApi(client)
    remaining = None if only is None else set(only)
    for capture in _capture_every_route(tap, accounting, payroll, tenant_id):
        if remaining is None:
            yield capture
        elif capture.name in remaining:
            yield capture
            remaining.discard(capture.name)
            if not remaining:
                # Nothing left to record; the burst and the rest are calls the
                # tenant's quota need not pay for.
                return


def _capture_every_route(
    tap: "_TransportTap", accounting: AccountingApi, payroll: PayrollNzApi, tenant_id: str
) -> Iterator[Capture]:
    yield from _capture_accounting(tap, accounting, tenant_id)
    yield from _capture_accounting_writes(tap, accounting, tenant_id)
    yield from _capture_payroll(tap, payroll, tenant_id)
    yield _record(tap, "rate_limit_minute", lambda: _burst(tap, accounting, tenant_id))


def _capture_accounting(
    tap: "_TransportTap", accounting: AccountingApi, tenant_id: str
) -> Iterator[Capture]:
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


def _capture_accounting_writes(
    tap: "_TransportTap", accounting: AccountingApi, tenant_id: str
) -> Iterator[Capture]:
    """Every write the application makes, and every refusal it handles, provoked on the tenant.

    Two contacts carry the pass. The first takes an invoice, its note and
    attachment, and is archived while that invoice stands authorised — the
    E2E cleanup's order. The second takes the quotes, the orders and the
    items, is archived once everything against it is voided, and archived
    again for the refusal. Every delete is sent as the provider sends it:
    id, DELETED, the contact and the date. The Demo Company exists for this;
    what a pass leaves behind (archived contacts, voided documents) is
    nobody's books.
    """
    stamp = uuid4().hex[:8]
    today = date.today().isoformat()  # noqa: DTZ011 -- Xero's date is the organisation's day
    name = f"[TEST] Recording {stamp}"
    contact_body: dict[str, Json] = {
        "Name": name,
        "EmailAddress": "recording@example.test",
        "Phones": [{"PhoneType": "DEFAULT", "PhoneNumber": "09 111 1111"}],
        "IsCustomer": True,
    }
    created = _record(
        tap,
        "contact_create",
        lambda: accounting.create_contacts(tenant_id, {"Contacts": [contact_body]}),
    )
    yield created
    contact_id = _text(_element(created, "Contacts"), "ContactID")
    yield _record(
        tap,
        "contact_create_duplicate_name",
        lambda: accounting.create_contacts(tenant_id, {"Contacts": [contact_body]}),
    )
    yield _record(
        tap,
        "contact_update",
        lambda: accounting.update_contact(
            tenant_id,
            contact_id,
            {"Contacts": [{"ContactID": contact_id, "EmailAddress": "changed@example.test"}]},
        ),
    )
    yield _record(
        tap,
        "contacts_by_name_other_case",
        lambda: accounting.get_contacts(tenant_id, where=f'Name=="{name.lower()}"'),
    )
    yield from _capture_invoice_writes(tap, accounting, tenant_id, contact_id, today)
    yield _record(
        tap,
        "contact_archive_with_documents",
        lambda: accounting.update_or_create_contacts(
            tenant_id,
            {"Contacts": [{"ContactID": contact_id, "ContactStatus": "ARCHIVED"}]},
            summarize_errors=False,
        ),
    )

    second = accounting.create_contacts(
        tenant_id, {"Contacts": [{**contact_body, "Name": f"{name} B", "IsSupplier": True}]}
    ).contacts
    if not second or second[0].contact_id is None:
        raise ValueError("the second recording contact was not created")
    supplier_id = str(second[0].contact_id)
    yield from _capture_quote_writes(tap, accounting, tenant_id, supplier_id, today)
    yield from _capture_purchase_order_writes(tap, accounting, tenant_id, supplier_id, today, stamp)
    yield from _capture_item_writes(tap, accounting, tenant_id, stamp)

    def archive() -> object:
        return accounting.update_or_create_contacts(
            tenant_id,
            {"Contacts": [{"ContactID": supplier_id, "ContactStatus": "ARCHIVED"}]},
            summarize_errors=False,
        )

    yield _record(tap, "contact_archive", archive)
    yield _record(tap, "contact_archive_archived", archive)


def _deletion(id_key: str, object_id: str, contact_id: str, today: str) -> dict[str, Json]:
    """Spell the DELETED update as the provider sends it: id, status, contact and date."""
    return {
        id_key: object_id,
        "Status": "DELETED",
        "Contact": {"ContactID": contact_id},
        "Date": today,
    }


def _capture_invoice_writes(
    tap: "_TransportTap", accounting: AccountingApi, tenant_id: str, contact_id: str, today: str
) -> Iterator[Capture]:
    invoice = _record(
        tap,
        "invoice_create",
        lambda: accounting.create_invoices(
            tenant_id,
            {
                "Invoices": [
                    {
                        "Type": "ACCREC",
                        "Contact": {"ContactID": contact_id},
                        "LineItems": [
                            {
                                "Description": "Job: 1 - recording",
                                "Quantity": 2,
                                "UnitAmount": Decimal("10.50"),
                                "AccountCode": "200",
                            }
                        ],
                        "Date": today,
                        "DueDate": today,
                        "LineAmountTypes": "Exclusive",
                        "Reference": "recording",
                        "Status": "AUTHORISED",
                    }
                ]
            },
        ),
    )
    yield invoice
    invoice_id = _text(_element(invoice, "Invoices"), "InvoiceID")
    yield _record(
        tap,
        "invoice_history_create",
        lambda: accounting.create_invoice_history(
            tenant_id, invoice_id, {"HistoryRecords": [{"Details": "Recorded by the catalogue"}]}
        ),
    )
    yield _record(
        tap,
        "invoice_attachment_create",
        lambda: accounting.create_invoice_attachment_by_file_name(
            tenant_id, invoice_id, "recording.pdf", b"%PDF-1.4 recording", include_online=False
        ),
    )
    yield _record(
        tap,
        "invoice_delete_authorised",
        lambda: accounting.update_or_create_invoices(
            tenant_id,
            {"Invoices": [_deletion("InvoiceID", invoice_id, contact_id, today)]},
            summarize_errors=False,
        ),
    )
    yield _record(
        tap,
        "invoice_void",
        lambda: accounting.update_or_create_invoices(
            tenant_id,
            {
                "Invoices": [
                    {**_deletion("InvoiceID", invoice_id, contact_id, today), "Status": "VOIDED"}
                ]
            },
            summarize_errors=False,
        ),
    )


def _capture_quote_writes(
    tap: "_TransportTap", accounting: AccountingApi, tenant_id: str, contact_id: str, today: str
) -> Iterator[Capture]:
    def quote_body(status: str, quote_id: str | None = None) -> dict[str, Json]:
        body: dict[str, Json] = {
            "Contact": {"ContactID": contact_id},
            "Date": today,
            "LineAmountTypes": "Exclusive",
            "LineItems": [
                {
                    "Description": "Job: 1 - recording",
                    "Quantity": 1,
                    "UnitAmount": Decimal("703.02"),
                    "AccountCode": "200",
                }
            ],
            "Status": status,
            "Terms": "Recorded by the catalogue",
        }
        if quote_id is not None:
            body["QuoteID"] = quote_id
        return body

    def upsert(body: dict[str, Json]) -> object:
        return accounting.update_or_create_quotes(
            tenant_id, {"Quotes": [body]}, summarize_errors=False
        )

    quote = _record(
        tap,
        "quote_create",
        lambda: accounting.create_quotes(
            tenant_id, {"Quotes": [quote_body("DRAFT")]}, summarize_errors=False
        ),
    )
    yield quote
    quote_id = _text(_element(quote, "Quotes"), "QuoteID")
    yield _record(tap, "quote_send", lambda: upsert(quote_body("SENT", quote_id)))
    yield _record(tap, "quote_accept", lambda: upsert(quote_body("ACCEPTED", quote_id)))
    yield _record(
        tap,
        "quote_delete_accepted",
        lambda: upsert(_deletion("QuoteID", quote_id, contact_id, today)),
    )
    draft = accounting.create_quotes(
        tenant_id, {"Quotes": [quote_body("DRAFT")]}, summarize_errors=False
    ).quotes
    if not draft or draft[0].quote_id is None:
        raise ValueError("the second recording quote was not created")
    draft_id = str(draft[0].quote_id)
    yield _record(
        tap, "quote_delete", lambda: upsert(_deletion("QuoteID", draft_id, contact_id, today))
    )


def _capture_purchase_order_writes(  # noqa: PLR0913, PLR0917 -- the pass's shared state, named
    tap: "_TransportTap",
    accounting: AccountingApi,
    tenant_id: str,
    contact_id: str,
    today: str,
    stamp: str,
) -> Iterator[Capture]:
    def order_body(number: str, status: str, order_id: str | None = None) -> dict[str, Json]:
        body: dict[str, Json] = {
            "PurchaseOrderNumber": number,
            "Contact": {"ContactID": contact_id},
            "LineItems": [
                {
                    "Description": "steel",
                    "Quantity": 1,
                    "UnitAmount": Decimal("100"),
                    "AccountCode": "300",
                }
            ],
            "Date": today,
            "Status": status,
        }
        if order_id is not None:
            body["PurchaseOrderID"] = order_id
        return body

    def upsert(body: dict[str, Json]) -> object:
        return accounting.update_or_create_purchase_orders(
            tenant_id, {"PurchaseOrders": [body]}, summarize_errors=False
        )

    number = f"PO-REC-{stamp}"
    order = _record(tap, "purchase_order_create", lambda: upsert(order_body(number, "SUBMITTED")))
    yield order
    order_id = _text(_element(order, "PurchaseOrders"), "PurchaseOrderID")
    yield _record(
        tap, "purchase_order_update", lambda: upsert(order_body(number, "AUTHORISED", order_id))
    )
    # Voided as the provider voids: the number released in the same update.
    yield _record(
        tap,
        "purchase_order_delete",
        lambda: upsert(
            {
                **_deletion("PurchaseOrderID", order_id, contact_id, today),
                "PurchaseOrderNumber": f"{number}-VOID-{stamp}",
            }
        ),
    )
    held = _record(
        tap, "purchase_order_create_held", lambda: upsert(order_body(f"{number}-H", "DRAFT"))
    )
    held_id = _text(_element(held, "PurchaseOrders"), "PurchaseOrderID")
    yield _record(
        tap,
        "purchase_order_delete_keeping_number",
        lambda: upsert(_deletion("PurchaseOrderID", held_id, contact_id, today)),
    )
    yield _record(
        tap,
        "purchase_order_number_held_by_deleted",
        lambda: upsert(order_body(f"{number}-H", "SUBMITTED")),
    )
    billed = _record(
        tap, "purchase_order_create_billed", lambda: upsert(order_body(f"{number}-B", "BILLED"))
    )
    billed_id = _text(_element(billed, "PurchaseOrders"), "PurchaseOrderID")
    yield _record(
        tap,
        "purchase_order_delete_billed",
        lambda: upsert(_deletion("PurchaseOrderID", billed_id, contact_id, today)),
    )


def _capture_item_writes(
    tap: "_TransportTap", accounting: AccountingApi, tenant_id: str, stamp: str
) -> Iterator[Capture]:
    code = f"REC-{stamp}"

    def item_body(name: str) -> dict[str, Json]:
        return {
            "Code": code,
            "Name": name,
            "IsSold": True,
            "IsPurchased": True,
            "SalesDetails": {"UnitPrice": Decimal("128.19"), "AccountCode": "200"},
            "PurchaseDetails": {"UnitPrice": Decimal("98.61"), "AccountCode": "300"},
        }

    created = _record(
        tap,
        "item_create",
        lambda: accounting.update_or_create_items(tenant_id, {"Items": [item_body("Recorded")]}),
    )
    yield created
    yield _record(
        tap,
        "item_update",
        lambda: accounting.update_or_create_items(
            tenant_id, {"Items": [item_body("Recorded again")]}
        ),
    )
    # The pass leaves no item behind: the stock sync would otherwise list it.
    with contextlib.suppress(ApiException):
        # The SDK has the method; its stub does not.
        accounting.delete_item(  # type: ignore[attr-defined]
            tenant_id, _text(_element(created, "Items"), "ItemID")
        )


def _capture_payroll(
    tap: "_TransportTap", payroll: PayrollNzApi, tenant_id: str
) -> Iterator[Capture]:
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
        "leave_balances",
        lambda: payroll.get_employee_leave_balances(tenant_id, employee_id),
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
    yield _record(tap, "pay_run_calendars", lambda: payroll.get_pay_run_calendars(tenant_id))
    yield _record(tap, "leave_types", lambda: payroll.get_leave_types(tenant_id))
    yield _record(tap, "earnings_rates", lambda: payroll.get_earnings_rates(tenant_id))
    pay_runs = _record(tap, "pay_runs", lambda: payroll.get_pay_runs(tenant_id))
    yield pay_runs
    yield _record(
        tap,
        "pay_slips",
        lambda: payroll.get_pay_slips(tenant_id, _text(_element(pay_runs, "payRuns"), "payRunID")),
    )


def _burst(tap: "_TransportTap", accounting: AccountingApi, tenant_id: str) -> None:
    """Cross the minute limit so the 429 is what the tap holds."""
    # Unpaced: the paced client's 1s interval is exactly what keeps a real
    # run under the minute limit, and the point here is to cross it.
    tap.minimum_sleep = 0
    tap.recording_a_refusal = True
    try:
        for _ in range(BURST_CALLS):
            accounting.get_organisations(tenant_id)
    finally:
        tap.minimum_sleep = RateLimitedRESTClient.minimum_sleep
        tap.recording_a_refusal = False
    raise ValueError(f"{BURST_CALLS} unpaced calls were all answered; no minute limit to record")


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
    # deliberate-swallow: a 404, a past-the-end 400 or a 429 is a route the fake
    # serves too, and the tap has already kept the body the SDK raised on.
    with contextlib.suppress(ApiException):
        call()
    return _capture(name, tap)


def _capture(name: str, tap: _TransportTap) -> Capture:
    content_type = tap.last_headers.get("Content-Type", "")
    if "application/json" in content_type:
        body: Json = _scrub(json.loads(tap.last_data, parse_float=Decimal))
        truncated = False
        if name not in UNTRUNCATED:
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
        headers={
            name: tap.last_headers[name] for name in RECORDED_HEADERS if name in tap.last_headers
        },
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
