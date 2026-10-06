"""The Accounting API routes, answered from the model (ADR 0060).

Reads filter, order and page the model through the one query language;
writes are ``defaults ⊕ request ⊕ minted`` (defaults.py, minting.py) and
refuse where Xero refuses — each refusal names the recording or the
measurement it was seen in, and none is a rule Xero was not seen to apply.
"""

import re
from collections.abc import Callable, Mapping
from datetime import date
from uuid import UUID, uuid4

from django.db.models import QuerySet
from xero_python.rest import RESTResponse

from apps.xero.constants import ZERO_UUID
from apps.xero.fake import defaults, query
from apps.xero.fake.http import FakeRequest, json_response, raw_response
from apps.xero.fake.limits import quota_headers
from apps.xero.fake.minting import (
    MintingError,
    as_list,
    as_mapping,
    date_fields,
    money,
    new_id,
    next_number,
    now_utc,
    text,
    totalled_lines,
)
from apps.xero.fake.models import (
    Document,
    FakeAccount,
    FakeAttachment,
    FakeBrandingTheme,
    FakeContact,
    FakeCreditNote,
    FakeHistoryRecord,
    FakeInvoice,
    FakeItem,
    FakeOrganisation,
    FakePurchaseOrder,
    FakeQuote,
    FakeTaxRate,
    XeroRecord,
)
from apps.xero.fake.pdf import render_quote_pdf
from apps.xero.fake.wire import Json, ms_date_now

# ---- envelopes ---------------------------------------------------------------


def envelope(
    key: str,
    elements: list[Json],
    *,
    summarize_errors: bool | None = None,
    pagination: dict[str, Json] | None = None,
) -> Json:
    """Wrap elements as the Accounting API does (recordings/contact.json, invoices_page.json)."""
    body: dict[str, Json] = {
        "Id": new_id(),
        "Status": "OK",
        "ProviderName": defaults.PROVIDER_NAME,
        "DateTimeUTC": ms_date_now(now_utc()),
    }
    if summarize_errors is not None:
        body = {"SummarizeErrors": summarize_errors, **body}
    if pagination is not None:
        body["pagination"] = pagination
    body[key] = elements
    return body


def ok(
    key: str,
    elements: list[Json],
    *,
    summarize_errors: bool | None = None,
    pagination: dict[str, Json] | None = None,
) -> RESTResponse:
    """Answer 200 with the listing or the written objects under ``key``."""
    return json_response(
        200,
        envelope(key, elements, summarize_errors=summarize_errors, pagination=pagination),
        quota_headers(),
    )


def not_found() -> RESTResponse:
    """Xero's 404: text/html and no JSON (recordings/invoice_not_found.json)."""
    return raw_response(404, b"", {"Content-Type": "text/html; charset=utf-8", **quota_headers()})


def validation_failure(elements: list[Json]) -> RESTResponse:
    """Answer the whole-request 400 Xero sends when summarizeErrors is not off."""
    body: dict[str, Json] = {
        "ErrorNumber": 10,
        "Type": "ValidationException",
        "Message": "A validation exception occurred",
        "Elements": elements,
    }
    return json_response(400, body, quota_headers())


# ---- listings ----------------------------------------------------------------

_LISTINGS: dict[str, type[XeroRecord]] = {
    "Contacts": FakeContact,
    "Invoices": FakeInvoice,
    "CreditNotes": FakeCreditNote,
    "Quotes": FakeQuote,
    "PurchaseOrders": FakePurchaseOrder,
    "Items": FakeItem,
    "Accounts": FakeAccount,
    "TaxRates": FakeTaxRate,
    "BrandingThemes": FakeBrandingTheme,
}
#: The listings whose answer carries Xero's ``pagination`` block when a page is asked for
#: (recordings/contacts_page.json, invoices_page.json; quotes_page.json has none).
_PAGINATED = frozenset({"Contacts", "Invoices", "CreditNotes", "PurchaseOrders"})
#: The quote and purchase-order listings' own parameters, which name columns rather
#: than a ``where`` (the SDK offers neither listing a ``where``).
_QUOTE_FILTERS: dict[str, str] = {
    "Status": "status",
    "ContactID": "contact_id",
    "QuoteNumber": "number",
    "DateFrom": "date__gte",
    "DateTo": "date__lte",
    "ExpiryDateFrom": "expiry_date__gte",
    "ExpiryDateTo": "expiry_date__lte",
}
_PURCHASE_ORDER_FILTERS: dict[str, str] = {
    "Status": "status",
    "DateFrom": "date__gte",
    "DateTo": "date__lte",
}
_OWN_FILTERS: dict[str, dict[str, str]] = {
    "Quotes": _QUOTE_FILTERS,
    "PurchaseOrders": _PURCHASE_ORDER_FILTERS,
}


def _summarize_errors(request: FakeRequest) -> bool:
    return request.query.get("summarizeErrors", "true").lower() == "true"


def list_resource(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /{resource}: filter, order and page the model as Xero would."""
    resource = match["resource"]
    extra = _OWN_FILTERS.get(resource, {})
    rows: QuerySet[XeroRecord]
    if resource == "Contacts":
        contacts = query.listing(FakeContact, request)
        # Xero lists live contacts unless asked for the archived too.
        rows = contacts if request.flag("includeArchived") else contacts.exclude(status="ARCHIVED")
    else:
        rows = query.listing(_LISTINGS[resource], request, extra=extra)
    for key, path in extra.items():
        raw = request.query.get(key)
        if raw is None:
            continue
        value: object = date.fromisoformat(raw) if path.startswith(("date", "expiry_date")) else raw
        rows = rows.filter(**{path: value})
    page, pagination = query.page(request, rows)
    summarize = _summarize_errors(request) if resource == "Quotes" else None
    return ok(
        resource,
        [row.to_wire() for row in page],
        summarize_errors=summarize,
        pagination=pagination if resource in _PAGINATED else None,
    )


def get_resource(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /{resource}/{id}: one object, or Xero's 404."""
    resource = match["resource"]
    row = _LISTINGS[resource].held(request.tenant_id, match["id"])
    if row is None:
        return not_found()
    if resource == "Quotes" and (request.header("Accept") or "").startswith("application/pdf"):
        return raw_response(
            200,
            render_quote_pdf(row.to_wire()),
            {"Content-Type": "application/pdf", **quota_headers()},
        )
    summarize = _summarize_errors(request) if resource == "Quotes" else None
    return ok(resource, [row.to_wire()], summarize_errors=summarize)


def _organisation(tenant_id: str) -> FakeOrganisation:
    organisation = FakeOrganisation.objects.filter(tenant_id=tenant_id).first()
    if organisation is None:
        raise MintingError(f"the fake holds no organisation for {tenant_id}; seed it")
    return organisation


def get_organisation(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /Organisation: the seeded organisation, name suffixed so every banner says FAKE."""
    del match
    return ok("Organisations", [_organisation(request.tenant_id).to_wire()])


def get_history(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """GET /{resource}/{id}/History (recordings/invoice_history.json)."""
    resource = match["resource"]
    parent = _LISTINGS[resource].held(request.tenant_id, match["id"])
    if parent is None:
        return not_found()
    rows = FakeHistoryRecord.for_tenant(request.tenant_id).filter(
        resource=resource, document_id=parent.id
    )
    return ok("HistoryRecords", [row.to_wire() for row in rows])


# ---- writes ------------------------------------------------------------------


def _elements(request: FakeRequest, key: str, match: re.Match[str], id_key: str) -> list[Json]:
    """Read the list under the envelope key, whatever case the application spelt it in.

    ``contacts.py`` sends ``{"contacts": [...]}`` and the provider
    ``{"Invoices": [...]}``; Xero reads both. On the single-object route
    (``POST /Contacts/{id}``) the path names the object and the element
    need not.
    """
    body = as_mapping(request.json_body, f"{request.method} {request.path}")
    path_id = match.groupdict().get("id")
    for candidate, value in body.items():
        if candidate.lower() != key.lower():
            continue
        elements = as_list(value, candidate)
        if path_id is None:
            return elements
        named: list[Json] = []
        for raw in elements:
            element = as_mapping(raw, f"{key}[]")
            sent_id = text(element, id_key)
            if sent_id is not None and sent_id.lower() != path_id.lower():
                raise MintingError(f"{request.path} names {path_id} but the element {sent_id}")
            named.append({**element, id_key: path_id})
        return named
    raise MintingError(f"{request.method} {request.path}: no {key} in the request body")


def _refused(
    element: dict[str, Json], *messages: str, id_key: str, object_id: str
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
        "ValidationErrors": [{"Message": message} for message in messages],
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
    """PUT (create) and POST (update or create) /Contacts, and POST /Contacts/{id}."""
    tenant_id = request.tenant_id
    written: list[Json] = []
    refused = False
    for raw in _elements(request, "Contacts", match, "ContactID"):
        sent = as_mapping(raw, "Contacts[]")
        contact_id = text(sent, "ContactID")
        existing = FakeContact.held(tenant_id, contact_id) if contact_id else None
        if contact_id and existing is None:
            # An id the organisation never issued: Xero answers 404 to the
            # whole request rather than creating under that id.
            return not_found()
        current: dict[str, Json] = existing.to_wire() if existing else dict(defaults.CONTACT)
        name = text(sent, "Name")
        if (
            existing is None
            and name is not None
            and FakeContact.objects.filter(
                tenant_id=tenant_id, name__iexact=name, status="ACTIVE"
            ).exists()
        ):
            # recordings/contact_create_duplicate_name.json: the whole request
            # is a 400 under the SDK's summarised errors, the element carries
            # the zero id and the reason.
            written.append(
                _refused(
                    sent,
                    f"The contact name {name} is already assigned to another contact. "
                    "The contact name must be unique across all active contacts.",
                    id_key="ContactID",
                    object_id=ZERO_UUID,
                )
            )
            refused = True
            continue
        if existing is not None and existing.status == "ARCHIVED":
            # Xero archives a contact whatever stands against it
            # (recordings/contact_archive_with_documents.json: an authorised
            # invoice) and refuses every later edit, the archive included
            # (contact_archive_archived.json); contacts.py reads it per element.
            written.append(
                _refused(
                    sent,
                    "The specified contact details matched an archived contact. "
                    "Archived contacts cannot currently be edited via the API.",
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
        if not text(merged, "Name"):
            raise MintingError("a contact must have a Name")
        row = FakeContact.write(
            tenant_id,
            UUID(contact_id) if contact_id else uuid4(),
            merged,
            updated_date_utc=now_utc(),
        )
        written.append(row.to_wire())
    return _answer_writes(request, "Contacts", written, refused=refused)


def _refusal_for(model: type[Document], existing: Document, sent: Mapping[str, Json]) -> str | None:
    """Name the refusal Xero applies to an update of a standing document, in Xero's words.

    An accepted quote and a billed order delete without complaint
    (recordings/quote_delete_accepted.json, purchase_order_delete_billed.json);
    an authorised invoice and a deleted order refuse.
    """
    if model is FakePurchaseOrder and existing.status == "DELETED":
        # recordings/purchase_order_number_held_by_deleted.json, and measured
        # on 2026-09-12 (provider.py, the ZERO_UUID comment).
        return "Deleted PurchaseOrders cannot be updated"
    if (
        model is FakeInvoice
        and text(sent, "Status") == "DELETED"
        and existing.status
        in (
            "AUTHORISED",
            "PAID",
        )
    ):
        # recordings/invoice_delete_authorised.json: an approved invoice is
        # voided, never deleted.
        return "Invoice not of valid status for modification"
    return None


_DEFAULTS: dict[type[Document], Mapping[str, Json]] = {
    FakeInvoice: defaults.INVOICE,
    FakeQuote: defaults.QUOTE,
    FakePurchaseOrder: defaults.PURCHASE_ORDER,
}


def _write_document(
    tenant_id: str, model: type[Document], sent: dict[str, Json]
) -> tuple[Json, bool]:
    """Create or update one document; return the element and whether it was refused."""
    object_id = text(sent, model.ID_KEY or "")
    existing = model.held(tenant_id, object_id) if object_id else None
    if object_id and existing is None:
        raise Document.DoesNotExist(f"{model.RESOURCE} {object_id}")
    number = text(sent, model.NUMBER_KEY)
    if existing is None and model is FakePurchaseOrder and number is not None:
        # Measured against the demo tenant on 2026-09-12: a number a LIVE order
        # already holds turns the create into an update of that order, answered
        # with its id and no error, so a duplicate number silently edits another
        # supplier's document and reports success. Reproduced rather than
        # refused: the fake is Xero's behaviour, not a kinder one (ADR 0060), and
        # a fake that refused here would hide the one collision the provider
        # cannot see.
        existing = (
            model.for_tenant(tenant_id).filter(number=number).exclude(status="DELETED").first()
        )
    if existing is not None:
        refusal = _refusal_for(model, existing, sent)
        if refusal is not None:
            return _refused(
                sent, refusal, id_key=model.ID_KEY or "", object_id=str(existing.id)
            ), True
    if (
        existing is None
        and model is FakePurchaseOrder
        and number is not None
        and model.for_tenant(tenant_id).filter(number=number, status="DELETED").exists()
    ):
        # recordings/purchase_order_number_held_by_deleted.json: a number a
        # deleted order still owns comes back as the all-zero id with two
        # messages, and the provider reads the id.
        return (
            _refused(
                sent,
                "PurchaseOrder status change is invalid",
                "Deleted PurchaseOrders cannot be updated",
                id_key=model.ID_KEY or "",
                object_id=ZERO_UUID,
            ),
            True,
        )
    current: dict[str, Json] = existing.to_wire() if existing else dict(_DEFAULTS[model])
    merged = _computed(tenant_id, model, current, sent)
    if existing is None:
        merged[model.NUMBER_KEY] = number or next_number(model, tenant_id)
        merged.setdefault("CurrencyCode", _organisation(tenant_id).base_currency)
    row = model.write(
        tenant_id, existing.id if existing else uuid4(), merged, updated_date_utc=now_utc()
    )
    return row.to_wire(), False


def _computed(
    tenant_id: str, model: type[Document], current: Mapping[str, Json], sent: Mapping[str, Json]
) -> dict[str, Json]:
    """Merge what stood with what was sent, then compute what Xero computes: lines, totals, due."""
    merged: dict[str, Json] = {**current, **sent}
    if model is FakeQuote and "LineAmountTypes" in sent:
        # Xero echoes a quote's LineAmountTypes in the quote enum's own form
        # (EXCLUSIVE, recordings/quote.json) whatever casing the request used;
        # this app sends the invoice form (Exclusive), which the SDK's quote
        # deserialiser refuses, so the echo canonicalises as the tenant does.
        merged["LineAmountTypes"] = str(sent["LineAmountTypes"]).upper()
    if "Contact" in sent:
        contact_id = text(as_mapping(sent["Contact"], "Contact"), "ContactID")
        if contact_id is None or FakeContact.held(tenant_id, contact_id) is None:
            # A document names its contact by id, and Xero holds it.
            raise FakeContact.DoesNotExist(f"{model.RESOURCE}[].Contact {contact_id}")
        merged["Contact"] = {"ContactID": contact_id}
    if "LineItems" in sent:
        lines, totals = totalled_lines(
            tenant_id,
            as_list(sent["LineItems"], "LineItems"),
            str(merged.get("LineAmountTypes", "Exclusive")),
        )
        merged["LineItems"] = lines
        merged.update(totals)
    if model is FakeInvoice and "Total" in merged:
        merged["AmountDue"] = (
            money(merged["Total"], "Total")
            - money(merged.get("AmountPaid", 0), "AmountPaid")
            - money(merged.get("AmountCredited", 0), "AmountCredited")
        )
    return merged


def _write_documents(model: type[Document]) -> Callable[[FakeRequest, re.Match[str]], RESTResponse]:
    def handler(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
        written: list[Json] = []
        refused = False
        try:
            for raw in _elements(request, model.RESOURCE, match, model.ID_KEY or ""):
                element, was_refused = _write_document(
                    request.tenant_id, model, as_mapping(raw, f"{model.RESOURCE}[]")
                )
                written.append(element)
                refused = refused or was_refused
        # deliberate-swallow: a write naming an unknown document or contact answers 404
        # before anything is written
        except (Document.DoesNotExist, FakeContact.DoesNotExist):
            return not_found()
        return _answer_writes(
            request, model.RESOURCE, written, refused=refused, quotes=model is FakeQuote
        )

    return handler


write_invoices = _write_documents(FakeInvoice)
write_quotes = _write_documents(FakeQuote)
write_purchase_orders = _write_documents(FakePurchaseOrder)


def write_history(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """PUT /{resource}/{id}/History: a note against a document."""
    resource = match["resource"]
    parent = _LISTINGS[resource].held(request.tenant_id, match["id"])
    if parent is None:
        return not_found()
    stamp = now_utc()
    written: list[Json] = []
    for raw in _elements(request, "HistoryRecords", match, ""):
        sent = as_mapping(raw, "HistoryRecords[]")
        # Shape from recordings/invoice_history.json; the user is the fake,
        # because that is who wrote it.
        record: dict[str, Json] = {
            "Changes": "Note",
            "DateUTC": ms_date_now(stamp),
            "User": defaults.PROVIDER_NAME,
            "Details": text(sent, "Details") or "",
        }
        row = FakeHistoryRecord.write(
            request.tenant_id,
            uuid4(),
            record,
            updated_date_utc=stamp,
            resource=resource,
            document_id=parent.id,
        )
        written.append(row.to_wire())
    return ok("HistoryRecords", written)


def write_attachment(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """PUT /{resource}/{id}/Attachments/{name}: the bytes are kept by size only."""
    resource = match["resource"]
    parent = _LISTINGS[resource].held(request.tenant_id, match["id"])
    if parent is None:
        return not_found()
    if request.raw_body is None:
        raise MintingError("an attachment upload carries the file as its body")
    stamp = now_utc()
    # No recording of an attachment answer exists (the run attaches, it never
    # lists); these are the fields Xero documents for one, and the application
    # reads none of them.
    body: dict[str, Json] = {
        "FileName": match["name"],
        "Url": f"https://api.xero.com/api.xro/2.0/{resource}/{parent.id}/Attachments/{match['name']}",
        "MimeType": request.header("Content-Type") or "application/octet-stream",
        "ContentLength": len(request.raw_body),
        "IncludeOnline": request.flag("IncludeOnline"),
    }
    row = FakeAttachment.write(
        request.tenant_id,
        uuid4(),
        body,
        updated_date_utc=stamp,
        resource=resource,
        document_id=parent.id,
    )
    return ok("Attachments", [row.to_wire()])


def write_items(request: FakeRequest, match: re.Match[str]) -> RESTResponse:
    """POST /Items: the stock sync's upsert, keyed by Code as Xero keys it."""
    tenant_id = request.tenant_id
    stamp = now_utc()
    written: list[Json] = []
    for raw in _elements(request, "Items", match, "ItemID"):
        sent = as_mapping(raw, "Items[]")
        code = text(sent, "Code")
        if not code:
            raise MintingError("an item must have a Code")
        existing = FakeItem.objects.filter(tenant_id=tenant_id, code=code).first()
        current: dict[str, Json] = existing.to_wire() if existing else {}
        row = FakeItem.write(
            tenant_id,
            existing.id if existing else uuid4(),
            {**current, **sent},
            updated_date_utc=stamp,
        )
        written.append(row.to_wire())
    return ok("Items", written)
