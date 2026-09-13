"""The Accounting API routes an E2E run reaches, answered from the store.

Reads page the store the way Xero pages its own listings; writes are
``defaults ⊕ request ⊕ minted`` (defaults.py, minting.py) and refuse in
exactly the cases the application already handles — each refusal names the
provider line that handles it, and none is a rule Xero was not seen to apply.
"""

import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from xero_python.rest import RESTResponse

from apps.xero.constants import ZERO_UUID
from apps.xero.fake import defaults
from apps.xero.fake.http import FakeRequest, json_response, raw_response
from apps.xero.fake.minting import (
    MintingError,
    as_list,
    as_mapping,
    date_fields,
    embedded_contact,
    money,
    new_id,
    now_utc,
    text,
    totalled_lines,
)
from apps.xero.fake.models import FakeXeroObject
from apps.xero.fake.pdf import render_quote_pdf
from apps.xero.fake.store import FakeXeroNotFoundError, FakeXeroStore, Kind
from apps.xero.fake.wire import Json, ms_date_now

# Every tenant-scoped answer carries Xero's quota headers: the paced client
# records them and the preflight reads them. A day that never runs out is
# the point of the fake.
QUOTA_HEADERS = {"X-DayLimit-Remaining": "4999", "X-MinLimit-Remaining": "59"}
PAGE_SIZE = 100
_WHERE = re.compile(r'^(?P<field>[A-Za-z]+)=="(?P<value>(?:[^"\\]|\\.)*)"$')
_UNHANDLED_ORDER = "the fake pages in UpdatedDateUTC ASC only; the sync asks for nothing else"


class FakeXeroUnhandledRouteError(NotImplementedError):
    """A call the fake has no answer for: never a guess, always this."""


# ---- envelopes ---------------------------------------------------------------


def envelope(key: str, elements: list[Json], *, summarize_errors: bool | None = None) -> Json:
    """Wrap elements the way the Accounting API does (recordings/contact.json, quotes_page.json)."""
    body: dict[str, Json] = {
        "Id": new_id(),
        "Status": "OK",
        "ProviderName": defaults.PROVIDER_NAME,
        "DateTimeUTC": ms_date_now(now_utc()),
    }
    if summarize_errors is not None:
        # Only the Quotes family echoes the flag (recordings/quotes_page.json).
        body["SummarizeErrors"] = summarize_errors
    body[key] = elements
    return body


def ok(key: str, elements: list[Json], *, summarize_errors: bool | None = None) -> RESTResponse:
    """Answer 200 with the listing or the written objects under ``key``."""
    return json_response(
        200, envelope(key, elements, summarize_errors=summarize_errors), QUOTA_HEADERS
    )


def not_found() -> RESTResponse:
    """Xero's 404: text/html and no JSON (recordings/invoice_not_found.json)."""
    return raw_response(404, b"", {"Content-Type": "text/html; charset=utf-8", **QUOTA_HEADERS})


def validation_failure(elements: list[Json]) -> RESTResponse:
    """Answer the whole-request 400 Xero sends when summarizeErrors is not off."""
    body: dict[str, Json] = {
        "ErrorNumber": 10,
        "Type": "ValidationException",
        "Message": "A validation exception occurred",
        "Elements": elements,
    }
    return json_response(400, body, QUOTA_HEADERS)


# ---- listings ----------------------------------------------------------------

_LISTINGS: dict[str, Kind] = {
    "Contacts": Kind.CONTACT,
    "Invoices": Kind.INVOICE,
    "CreditNotes": Kind.CREDIT_NOTE,
    "Quotes": Kind.QUOTE,
    "PurchaseOrders": Kind.PURCHASE_ORDER,
    "Items": Kind.ITEM,
    "Accounts": Kind.ACCOUNT,
    "TaxRates": Kind.TAX_RATE,
    "BrandingThemes": Kind.BRANDING_THEME,
}


def _modified_since(request: FakeRequest) -> datetime | None:
    header = request.header("If-Modified-Since")
    if header is None:
        return None
    try:
        parsed = datetime.fromisoformat(header)
    # deliberate-swallow: the SDK sends If-Modified-Since as ISO-8601 and the spec
    # allows RFC 1123; the second parser is the other accepted form
    except ValueError:
        parsed = parsedate_to_datetime(header)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _where(request: FakeRequest) -> tuple[str, str] | None:
    where = request.query.get("where")
    if where is None:
        return None
    match = _WHERE.match(where)
    if match is None:
        # Only Name=="…" (the duplicate check) and Type=="ACCREC"/"ACCPAY"
        # (the sync) are sent; anything else is a new caller to route.
        raise FakeXeroUnhandledRouteError(f"where filter {where!r} on {request.path}")
    value = match["value"].replace('\\"', '"').replace("\\\\", "\\")
    return match["field"], value


def list_resource(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /{resource}: filter, order and page the store as Xero would."""
    resource = match["resource"]
    kind = _LISTINGS[resource]
    store = FakeXeroStore(request.tenant_id)
    order = request.query.get("order")
    if order not in (None, "UpdatedDateUTC ASC"):
        raise FakeXeroUnhandledRouteError(f"order={order!r}: {_UNHANDLED_ORDER}")
    exclude = () if kind is not Kind.CONTACT or request.flag("includeArchived") else ("ARCHIVED",)
    name = None
    body_filter: dict[str, str] = {}
    where = _where(request)
    if where is not None:
        field, value = where
        if field == "Name":
            name = value
        else:
            body_filter[field] = value
    rows = store.listing(
        kind, modified_since=_modified_since(request), exclude_status=exclude, name=name
    )
    for field, value in body_filter.items():
        rows = rows.filter(**{f"body__{field}": value})
    page = request.query.get("page")
    if page is not None:
        size = int(request.query.get("pageSize", PAGE_SIZE))
        offset = (int(page) - 1) * size
        rows = rows[offset : offset + size]
    summarize = _summarize_errors(request) if resource == "Quotes" else None
    return ok(resource, [row.body for row in rows], summarize_errors=summarize)


def get_resource(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /{resource}/{id}: one object, or Xero's 404."""
    resource = match["resource"]
    store = FakeXeroStore(request.tenant_id)
    try:
        row = store.require(_LISTINGS[resource], match["id"])
    # deliberate-swallow: reading an id the organisation never issued is Xero's 404
    except FakeXeroNotFoundError:
        return not_found()
    if resource == "Quotes" and (request.header("Accept") or "").startswith("application/pdf"):
        return raw_response(
            200, render_quote_pdf(row.body), {"Content-Type": "application/pdf", **QUOTA_HEADERS}
        )
    summarize = _summarize_errors(request) if resource == "Quotes" else None
    return ok(resource, [row.body], summarize_errors=summarize)


def get_organisation(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /Organisation: the seeded organisation, name suffixed so every banner says FAKE."""
    del match
    rows = list(FakeXeroStore(request.tenant_id).listing(Kind.ORGANISATION))
    if len(rows) != 1:
        raise MintingError(
            f"the fake holds {len(rows)} organisations for {request.tenant_id}; seed it"
        )
    return ok("Organisations", [rows[0].body])


# ---- writes ------------------------------------------------------------------


def _elements(request: FakeRequest, key: str) -> list[Json]:
    """Read the list under the envelope key, whatever case the application spelt it in.

    ``contacts.py`` sends ``{"contacts": [...]}`` and the provider
    ``{"Invoices": [...]}``; Xero reads both.
    """
    body = as_mapping(request.json_body, f"{request.method} {request.path}")
    for candidate, value in body.items():
        if candidate.lower() == key.lower():
            return as_list(value, candidate)
    raise MintingError(f"{request.method} {request.path}: no {key} in the request body")


def _summarize_errors(request: FakeRequest) -> bool:
    return request.query.get("summarizeErrors", "true").lower() == "true"


def _refused(
    element: dict[str, Json], message: str, *, id_key: str, object_id: str
) -> dict[str, Json]:
    """Xero's element-level refusal: the element back, with its errors attached."""
    return {
        **element,
        # Echoed as Xero stores dates, not as the application spelt them: the
        # SDK parses the echo with the same date[ms-format] reader.
        **date_fields(element),
        id_key: object_id,
        "HasErrors": True,
        "HasValidationErrors": True,
        "StatusAttributeString": "ERROR",
        "ValidationErrors": [{"Message": message}],
    }


def _answer_writes(
    request: FakeRequest, key: str, written: list[Json], *, refused: bool, quotes: bool = False
) -> RESTResponse:
    """200 with the elements, or the 400 Xero sends for a refusal when errors are summarised."""
    summarize = _summarize_errors(request)
    if refused and summarize:
        return validation_failure(written)
    return ok(key, written, summarize_errors=summarize if quotes else None)


def _merge_slots(current: Json, sent: Json, slot_key: str) -> list[Json]:
    """Fill Xero's fixed slots (four phone types, two address types) from what was sent."""
    slots = [dict(as_mapping(slot, slot_key)) for slot in as_list(current, slot_key)]
    for raw in as_list(sent, slot_key):
        provided = as_mapping(raw, slot_key)
        kind = provided.get(slot_key)
        for slot in slots:
            if slot.get(slot_key) == kind:
                slot.update(provided)
                break
        else:
            slots.append(dict(provided))
    return [dict(slot) for slot in slots]


def write_contacts(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """PUT (create) and POST (update or create) /Contacts."""
    del match
    store = FakeXeroStore(request.tenant_id)
    written: list[Json] = []
    refused = False
    for raw in _elements(request, "Contacts"):
        sent = as_mapping(raw, "Contacts[]")
        contact_id = text(sent, "ContactID")
        existing = store.get(Kind.CONTACT, contact_id) if contact_id else None
        if contact_id and existing is None:
            # An id the organisation never issued: Xero answers 404 to the
            # whole request rather than creating under that id.
            return not_found()
        current: dict[str, Json] = dict(existing.body) if existing else dict(defaults.CONTACT)
        if (
            sent.get("ContactStatus") == "ARCHIVED"
            and existing is not None
            and store.owned_documents(str(existing.id)).exists()
        ):
            # contacts.py:archive_contacts_in_xero reads this per element.
            # Wording is the fake's: the refusal was seen, its text was not
            # recorded.
            written.append(
                _refused(
                    sent,
                    "Contact has transactions and cannot be archived",
                    id_key="ContactID",
                    object_id=str(existing.id),
                )
            )
            refused = True
            continue
        merged = {**current, **sent}
        for slot_key, plural in (("PhoneType", "Phones"), ("AddressType", "Addresses")):
            if plural in sent:
                merged[plural] = _merge_slots(current.get(plural, []), sent[plural], slot_key)
        merged["ContactID"] = contact_id or new_id()
        merged["UpdatedDateUTC"] = ms_date_now(now_utc())
        name = text(merged, "Name")
        if not name:
            raise MintingError("a contact must have a Name")
        row = store.save(
            Kind.CONTACT,
            str(merged["ContactID"]),
            merged,
            updated_date_utc=now_utc(),
            name=name,
            status=text(merged, "ContactStatus"),
        )
        written.append(row.body)
    return _answer_writes(request, "Contacts", written, refused=refused)


class _DocumentKind:
    """How one document family is keyed, numbered and defaulted."""

    def __init__(
        self, kind: Kind, key: str, id_key: str, number_key: str, defaults_body: Mapping[str, Json]
    ) -> None:
        self.kind = kind
        self.key = key
        self.id_key = id_key
        self.number_key = number_key
        self.defaults = defaults_body


_INVOICES = _DocumentKind(Kind.INVOICE, "Invoices", "InvoiceID", "InvoiceNumber", defaults.INVOICE)
_QUOTES = _DocumentKind(Kind.QUOTE, "Quotes", "QuoteID", "QuoteNumber", defaults.QUOTE)
_PURCHASE_ORDERS = _DocumentKind(
    Kind.PURCHASE_ORDER,
    "PurchaseOrders",
    "PurchaseOrderID",
    "PurchaseOrderNumber",
    defaults.PURCHASE_ORDER,
)


def _refusal_for(
    family: _DocumentKind, existing: Mapping[str, Json], sent: Mapping[str, Json]
) -> str | None:
    """Name the refusal for a case the application handles, in the wording it was seen with."""
    current_status = text(existing, "Status")
    wanted = text(sent, "Status")
    if family is _PURCHASE_ORDERS and current_status == "DELETED":
        # Measured 2026-09-12 against the demo tenant (provider.py, the
        # ZERO_UUID comment): Xero's own words.
        return "Deleted PurchaseOrders cannot be updated"
    if wanted != "DELETED":
        return None
    if family is _INVOICES and current_status in ("AUTHORISED", "PAID"):
        # provider.delete_invoice sends DELETED; an approved invoice is voided,
        # never deleted. Wording is the fake's.
        return "Invoice not of valid status for deletion"
    if family is _QUOTES and current_status == "ACCEPTED":
        # provider.delete_quote reads the element-level refusal. Wording is the fake's.
        return "Quote is ACCEPTED and cannot be deleted"
    if family is _PURCHASE_ORDERS and current_status == "BILLED":
        # provider.delete_purchase_order reads the element-level refusal. Wording is the fake's.
        return "A BILLED purchase order cannot be deleted"
    return None


def _base_currency(store: FakeXeroStore) -> str:
    rows = list(store.listing(Kind.ORGANISATION))
    if len(rows) != 1:
        raise MintingError(
            f"the fake holds {len(rows)} organisations for {store.tenant_id}; seed it"
        )
    currency = text(rows[0].body, "BaseCurrency")
    if currency is None:
        raise MintingError("the seeded organisation has no BaseCurrency")
    return currency


def _merged_body(
    family: _DocumentKind, existing: FakeXeroObject | None, sent: dict[str, Json]
) -> dict[str, Json]:
    """Merge what stood with what was sent into the body this write stores."""
    current: dict[str, Json] = dict(existing.body) if existing else dict(family.defaults)
    merged: dict[str, Json] = {**current, **sent}
    if family is _QUOTES and "LineAmountTypes" in sent:
        # Xero echoes a quote's LineAmountTypes in the quote enum's own form
        # (EXCLUSIVE, recordings/quote.json) whatever casing the request used;
        # this app sends the invoice form (Exclusive), which the SDK's quote
        # deserialiser refuses, so the echo canonicalises as the tenant does.
        merged["LineAmountTypes"] = str(sent["LineAmountTypes"]).upper()
    return merged


def _write_document(
    store: FakeXeroStore, family: _DocumentKind, sent: dict[str, Json]
) -> tuple[Json, bool]:
    """Create or update one document; return the element and whether it was refused."""
    object_id = text(sent, family.id_key)
    existing = store.get(family.kind, object_id) if object_id else None
    if object_id and existing is None:
        raise FakeXeroNotFoundError(f"{family.kind} {object_id}")
    if existing is not None:
        refusal = _refusal_for(family, existing.body, sent)
        if refusal is not None:
            return _refused(sent, refusal, id_key=family.id_key, object_id=str(existing.id)), True
    number = text(sent, family.number_key)
    if (
        existing is None
        and family is _PURCHASE_ORDERS
        and number is not None
        and store.holds_number(family.kind, number, status="DELETED")
    ):
        # Measured 2026-09-12 (provider.py, ZERO_UUID): a number a deleted
        # order still owns comes back as the all-zero id with the refusal.
        return (
            _refused(
                sent,
                "Deleted PurchaseOrders cannot be updated",
                id_key=family.id_key,
                object_id=ZERO_UUID,
            ),
            True,
        )
    merged = _merged_body(family, existing, sent)
    if "Contact" in sent:
        merged["Contact"] = embedded_contact(store, sent["Contact"], f"{family.key}[].Contact")
    if "LineItems" in sent:
        lines, totals = totalled_lines(
            store,
            as_list(sent["LineItems"], "LineItems"),
            str(merged.get("LineAmountTypes", "Exclusive")),
        )
        merged["LineItems"] = lines
        merged.update(totals)
    if family is _INVOICES and "Total" in merged:
        merged["AmountDue"] = (
            money(merged["Total"], "Total")
            - money(merged.get("AmountPaid", 0), "AmountPaid")
            - money(merged.get("AmountCredited", 0), "AmountCredited")
        )
    merged.update(date_fields(sent))
    merged[family.id_key] = object_id or new_id()
    if existing is None:
        merged[family.number_key] = number or store.next_number(
            family.kind, defaults.FIRST_NUMBER[family.kind.value]
        )
        merged.setdefault("CurrencyCode", _base_currency(store))
    stamp = now_utc()
    merged["UpdatedDateUTC"] = ms_date_now(stamp)
    if family is _INVOICES:
        merged["UpdatedDateUTCString"] = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    row = store.save(
        family.kind,
        str(merged[family.id_key]),
        merged,
        updated_date_utc=stamp,
        number=text(merged, family.number_key),
        status=text(merged, "Status"),
    )
    return row.body, False


def _write_documents(family: _DocumentKind) -> Callable[[FakeRequest, re.Match[str]], RESTResponse]:
    def handler(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
        del match
        store = FakeXeroStore(request.tenant_id)
        written: list[Json] = []
        refused = False
        try:
            for raw in _elements(request, family.key):
                element, was_refused = _write_document(
                    store, family, as_mapping(raw, f"{family.key}[]")
                )
                written.append(element)
                refused = refused or was_refused
        # deliberate-swallow: a write naming an unknown document answers 404 before
        # anything is written
        except FakeXeroNotFoundError:
            return not_found()
        return _answer_writes(
            request, family.key, written, refused=refused, quotes=family is _QUOTES
        )

    return handler


write_invoices = _write_documents(_INVOICES)
write_quotes = _write_documents(_QUOTES)
write_purchase_orders = _write_documents(_PURCHASE_ORDERS)


def write_history(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """PUT /{Invoices|Quotes}/{id}/History: a note against a document."""
    store = FakeXeroStore(request.tenant_id)
    try:
        parent = store.require(_LISTINGS[match["resource"]], match["id"])
    # deliberate-swallow: a note against a document Xero does not hold is its 404
    except FakeXeroNotFoundError:
        return not_found()
    stamp = now_utc()
    written: list[Json] = []
    for raw in _elements(request, "HistoryRecords"):
        sent = as_mapping(raw, "HistoryRecords[]")
        # Shape from recordings/invoice_history.json; the user is the fake,
        # because that is who wrote it.
        record: dict[str, Json] = {
            "Changes": "Note",
            "DateUTCString": stamp.strftime("%Y-%m-%dT%H:%M:%S"),
            "DateUTC": ms_date_now(stamp),
            "User": defaults.PROVIDER_NAME,
            "Details": text(sent, "Details") or "",
        }
        store.save(
            Kind.HISTORY_RECORD, new_id(), record, updated_date_utc=stamp, parent_id=str(parent.id)
        )
        written.append(record)
    return ok("HistoryRecords", written)


def write_attachment(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """PUT /Invoices/{id}/Attachments/{name}: the bytes are kept by size only."""
    store = FakeXeroStore(request.tenant_id)
    try:
        parent = store.require(Kind.INVOICE, match["id"])
    # deliberate-swallow: an attachment for an invoice Xero does not hold is its 404
    except FakeXeroNotFoundError:
        return not_found()
    if request.raw_body is None:
        raise MintingError("an attachment upload carries the file as its body")
    stamp = now_utc()
    attachment_id = new_id()
    # No recording of an attachment answer exists (the run attaches, it never
    # lists); these are the fields Xero documents for one, and the application
    # reads none of them.
    body: dict[str, Json] = {
        "AttachmentID": attachment_id,
        "FileName": match["name"],
        "Url": f"https://api.xero.com/api.xro/2.0/Invoices/{parent.id}/Attachments/{match['name']}",
        "MimeType": request.header("Content-Type") or "application/octet-stream",
        "ContentLength": len(request.raw_body),
        "IncludeOnline": request.flag("IncludeOnline"),
    }
    store.save(
        Kind.ATTACHMENT,
        attachment_id,
        body,
        updated_date_utc=stamp,
        name=match["name"],
        parent_id=str(parent.id),
    )
    return ok("Attachments", [body])


def write_items(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """POST /Items: the stock sync's upsert, keyed by Code as Xero keys it."""
    del match
    store = FakeXeroStore(request.tenant_id)
    stamp = now_utc()
    written: list[Json] = []
    for raw in _elements(request, "Items"):
        sent = as_mapping(raw, "Items[]")
        code = text(sent, "Code")
        if not code:
            raise MintingError("an item must have a Code")
        existing = next((row for row in store.listing(Kind.ITEM) if row.number == code), None)
        current: dict[str, Json] = dict(existing.body) if existing else {}
        merged: dict[str, Json] = {**current, **sent}
        merged["ItemID"] = str(existing.id) if existing else new_id()
        merged["UpdatedDateUTC"] = ms_date_now(stamp)
        row = store.save(
            Kind.ITEM,
            str(merged["ItemID"]),
            merged,
            updated_date_utc=stamp,
            number=code,
            name=text(merged, "Name"),
        )
        written.append(row.body)
    return ok("Items", written)
