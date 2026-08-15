"""Xero object → local model transforms for the sync engine.

Every transform stores the cleaned SDK payload in ``raw_json`` and derives
model fields from it; per-item failures persist a ``XeroError`` (validation)
or ``AppError`` (unexpected) and the batch continues — one malformed record
must not abort an entity's sync.

Typing note: the ``xero_*`` parameters are SDK model instances whose classes
we do not stub exhaustively; the contract is attribute extraction followed by
``validate_required_fields`` — validation-then-access, with ``Any`` marking
the foreign payload boundary, not an escape hatch around our own types.
"""

import logging
import time
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.utils import timezone
from xero_python.accounting import Account, AccountingApi

from apps.accounting.models import Bill, CreditNote, Invoice, Quote
from apps.company.models import Company
from apps.core.errors import persist_app_error
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Stock
from apps.purchasing.tasks import enqueue_stock_metadata_parse, stock_metadata_parse_eligible
from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.constants import SLEEP_TIME
from apps.xero.models import XeroAccount, XeroError, XeroPayRun, XeroPaySlip
from apps.xero.raw_fields import set_company_fields, set_invoice_or_bill_fields
from apps.xero.validation import (
    XeroValidationError,
    persist_xero_error,
    required,
    validate_required_fields,
)

logger = logging.getLogger(__name__)


def _build_sync_status(created: bool, changed_fields: list[str]) -> str:
    """Build a status string describing what changed during sync."""
    if created:
        return "created"
    if changed_fields:
        return f"{len(changed_fields)} fields incl {changed_fields[0]}"
    return "unchanged"


def _track_and_apply_changes(instance: Any, fields: dict[str, Any]) -> list[str]:
    """Compare fields against instance, apply changes, return changed field names."""
    changed = []
    for key, value in fields.items():
        if getattr(instance, key, None) != value:
            setattr(instance, key, value)
            changed.append(key)
    return changed


def serialize_xero_object(obj: Any) -> Any:  # noqa: PLR0911 -- a type-dispatch ladder; one return per JSON shape
    """Convert Xero SDK objects to a JSON-serializable structure."""
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, (list, tuple)):
        return [serialize_xero_object(item) for item in obj]
    if isinstance(obj, dict):
        return {key: serialize_xero_object(value) for key, value in obj.items()}
    if hasattr(obj, "__dict__"):
        return serialize_xero_object(obj.__dict__)
    return str(obj)


def clean_json(data: Any) -> Any:
    """Remove Xero's internal fields and bulky repeated data."""
    if not isinstance(data, dict):
        return data

    exclude_patterns = [
        "_value2member_map_",
        "_generate_next_value_",
        "_member_names_",
        "__objclass__",
    ]
    exclude_keys = {"_currency_code", "_currency_rate", *exclude_patterns}

    cleaned = {}
    for key, value in data.items():
        if key in exclude_keys or any(pattern in key for pattern in exclude_patterns):
            continue

        if isinstance(value, dict):
            cleaned[key] = clean_json(value)
        elif isinstance(value, list):
            cleaned[key] = [clean_json(item) if isinstance(item, dict) else item for item in value]
        else:
            cleaned[key] = value

    return cleaned


def process_xero_data(xero_obj: Any) -> Any:
    """Serialize + clean: the standard processing for every stored raw_json."""
    return clean_json(serialize_xero_object(xero_obj))


def get_or_fetch_company(contact_id: str, reference: str | None = None) -> Company:
    """Get company by Xero contact_id, fetching from the API if needed."""
    company = Company.objects.filter(xero_contact_id=contact_id).first()
    if company:
        return company.get_final_company()

    response = AccountingApi(get_api_client()).get_contacts(
        get_tenant_id(), i_ds=[contact_id], include_archived=True
    )
    time.sleep(SLEEP_TIME)

    if not response.contacts:
        raise ValueError(f"Company not found for {reference or contact_id}")

    synced = sync_companies([response.contacts[0]])
    if not synced:
        raise ValueError(f"Failed to sync company for {reference or contact_id}")

    return synced[0].get_final_company()


def sync_company_from_xero_contact(contact: Any, reference: str | None = None) -> Company:
    """Resolve a local company from embedded Xero contact data.

    Use embedded contact payloads from parent Xero documents first. Only the
    caller decides when the payload is too incomplete and a separate API
    fetch is warranted.
    """
    contact_id = getattr(contact, "contact_id", None)
    if not contact_id:
        raise ValueError(f"Company not found for {reference or 'missing contact'}")

    company = Company.objects.filter(xero_contact_id=contact_id).first()
    if company:
        return company.get_final_company()

    synced = sync_companies([contact])
    if not synced:
        raise ValueError(f"Failed to sync company for {reference or contact_id}")

    return synced[0].get_final_company()


def resolve_company_from_xero_contact(contact: Any, reference: str | None = None) -> Company:
    """Resolve a company from embedded contact data, GET only if it is absent."""
    if contact is None:
        raise ValueError(f"Company not found for {reference or 'missing contact'}")

    contact_id = getattr(contact, "contact_id", None)
    if contact_id is None:
        raise ValueError(f"Company not found for {reference or 'missing contact id'}")

    # An embedded contact with only its id (attr count 1) is a bare reference;
    # anything richer is worth syncing from directly, saving the GET.
    contact_attrs = getattr(contact, "__dict__", None) or {}
    if len(contact_attrs) > 1:
        return sync_company_from_xero_contact(contact, reference)

    return get_or_fetch_company(contact_id, reference)


def sync_entities(
    items: Iterable[Any],
    model_class: type[Any],
    xero_id_attr: str,
    transform_func: Any,
    delete_orphans: bool = False,
) -> int:
    """Persist a batch of Xero objects.

    Args:
        items: Iterable of objects from Xero.
        model_class: Django model used for storage.
        xero_id_attr: Attribute name of the Xero ID on each item.
        transform_func: Callable returning (instance, status) tuple or None.
        delete_orphans: If True, delete local records not in the fetched set.
            Use for cache-only entities where Xero is the master.

    Returns:
        Number of items successfully synced.
    """
    # Convert to list if we need to iterate twice (for delete_orphans)
    items_list = list(items) if delete_orphans else items

    if delete_orphans:
        xero_ids = {getattr(item, xero_id_attr) for item in items_list}
        deleted, _ = model_class.objects.exclude(xero_id__in=xero_ids).delete()
        if deleted:
            logger.info("Deleted %d orphaned %s records", deleted, model_class.__name__)

    synced = 0
    for item in items_list:
        xero_id = getattr(item, xero_id_attr)

        # Xero omits fields for deleted docs so we skip to avoid errors
        if getattr(item, "status", None) == "DELETED":
            logger.info("Skipping deleted %s %s", model_class.__name__, xero_id)
            continue

        try:
            result = transform_func(item, xero_id)
        # deliberate-swallow: one malformed record is persisted as a
        # XeroError row and must not abort the rest of the entity's batch
        except XeroValidationError as exc:
            persist_xero_error(exc)
            logger.error("Failed to sync %s %s: %s", model_class.__name__, xero_id, exc)
            continue
        # deliberate-swallow: unexpected per-item failures persist an
        # AppError; the batch continues for the same reason as above
        except Exception as exc:  # noqa: BLE001
            persist_app_error(exc)
            logger.error("Failed to sync %s %s: %s", model_class.__name__, xero_id, exc)
            continue
        if not result:
            continue
        instance, status = result
        identifier = getattr(instance, "number", getattr(instance, "name", xero_id))
        logger.info("Synced %s: %s (%s)", model_class.__name__, identifier, status)
        synced += 1
    return synced


def _resolve_document_number(doc_type: str, xero_obj: Any) -> str | None:
    """Return the canonical document number provided by Xero."""
    match doc_type:
        case "invoice" | "bill":
            primary = getattr(xero_obj, "invoice_number", None)
        case "credit_note":
            primary = getattr(xero_obj, "credit_note_number", None)
        case _:
            logger.error("Unknown document type for Xero sync: %s", doc_type)
            return None

    return str(primary) if primary is not None else None


def _extract_required_fields_xero(
    doc_type: str, xero_obj: Any, xero_id: UUID | str
) -> dict[str, Any]:
    """Gather required values from a Xero document, validated non-None."""
    number = _resolve_document_number(doc_type, xero_obj)
    company = resolve_company_from_xero_contact(getattr(xero_obj, "contact", None), number)
    doc_date = getattr(xero_obj, "date", None)
    total_excl_tax = getattr(xero_obj, "sub_total", None)
    tax = getattr(xero_obj, "total_tax", None)
    total_incl_tax = getattr(xero_obj, "total", None)
    # Credit notes use remaining_credit instead of amount_due
    if doc_type == "credit_note":
        amount_due = getattr(xero_obj, "remaining_credit", None)
    else:
        amount_due = getattr(xero_obj, "amount_due", None)
    xero_last_modified = getattr(xero_obj, "updated_date_utc", None)
    raw_json = process_xero_data(xero_obj)

    required_fields: dict[str, Any] = {
        "company": company,
        "date": doc_date,
        "number": number,
        "total_excl_tax": total_excl_tax,
        "tax": tax,
        "total_incl_tax": total_incl_tax,
        "amount_due": amount_due,
        "xero_last_modified": xero_last_modified,
        "raw_json": raw_json,
    }
    validate_required_fields(required_fields, doc_type, str(xero_id))
    return required_fields


def _log_invoice_sync_events(
    invoice: Invoice,
    old_total: Decimal | None,
    old_status: str | None,
    changed_fields: list[str],
    status_changed: bool = False,
) -> None:
    """Create JobEvents when Xero sync changes invoice totals or status."""
    # Call-time imports: keep this module importable before the app registry.
    from apps.accounts.models import Staff  # noqa: PLC0415
    from apps.job.models import JobEvent  # noqa: PLC0415

    automation_user = Staff.get_automation_user()

    if "total_excl_tax" in changed_fields and old_total is not None:
        JobEvent.objects.create(
            job=invoice.job,
            staff=automation_user,
            event_type="invoice_amount_changed",
            detail={
                "xero_invoice_number": invoice.number,
                "old_total_excl_tax": str(old_total),
                "new_total_excl_tax": str(invoice.total_excl_tax),
            },
        )

    if status_changed and old_status is not None:
        new_status = invoice.status
        if new_status == "VOIDED":
            JobEvent.objects.create(
                job=invoice.job,
                staff=automation_user,
                event_type="invoice_voided",
                detail={
                    "xero_invoice_number": invoice.number,
                    "total_excl_tax": str(invoice.total_excl_tax),
                },
            )
        elif new_status == "DELETED":
            JobEvent.objects.create(
                job=invoice.job,
                staff=automation_user,
                event_type="invoice_deleted",
                detail={
                    "xero_invoice_number": invoice.number,
                    "total_excl_tax": str(invoice.total_excl_tax),
                },
            )


def transform_invoice(xero_invoice: Any, xero_id: UUID | str) -> tuple[Invoice, str] | None:
    """Convert a Xero invoice into an Invoice instance."""
    fields = _extract_required_fields_xero("invoice", xero_invoice, xero_id)
    invoice, created = Invoice.objects.get_or_create(xero_id=xero_id, defaults=fields)

    old_total_excl_tax = invoice.total_excl_tax if not created else None
    old_status = invoice.status if not created else None

    changed_fields = _track_and_apply_changes(invoice, fields) if not created else []
    if changed_fields:
        invoice.save()
    set_invoice_or_bill_fields(invoice, "INVOICE")
    if created:
        invoice.save()

    # Check if status was changed by set_invoice_or_bill_fields
    status_changed = not created and old_status is not None and invoice.status != old_status
    if status_changed:
        invoice.save(update_fields=["status"])

    if invoice.job and (changed_fields or status_changed):
        _log_invoice_sync_events(
            invoice, old_total_excl_tax, old_status, changed_fields, status_changed
        )

    if invoice.job:
        from apps.accounts.models import Staff  # noqa: PLC0415 -- call-time, as above
        from apps.job.services.job_service import recalculate_job_invoicing_state  # noqa: PLC0415

        recalculate_job_invoicing_state(invoice.job.id, Staff.get_automation_user())

    return invoice, _build_sync_status(created, changed_fields)


def transform_bill(xero_bill: Any, xero_id: UUID | str) -> tuple[Bill, str] | None:
    """Convert a Xero bill into a Bill instance."""
    # Skip bills without invoice numbers - data entry issue in Xero
    invoice_number = getattr(xero_bill, "invoice_number", None)
    if not invoice_number:
        contact_name = getattr(xero_bill.contact, "name", "Unknown")
        msg = f"Skipping bill {xero_id} - no invoice number (supplier: {contact_name})"
        logger.error(msg)
        XeroError.objects.create(
            message=msg,
            data={"supplier": contact_name},
            entity="bill",
            reference_id=str(xero_id),
            kind="missing_invoice_number",
        )
        return None
    fields = _extract_required_fields_xero("bill", xero_bill, xero_id)
    bill, created = Bill.objects.get_or_create(xero_id=xero_id, defaults=fields)
    changed_fields = _track_and_apply_changes(bill, fields) if not created else []
    if changed_fields:
        bill.save()
    set_invoice_or_bill_fields(bill, "BILL")
    if created:
        bill.save()
    return bill, _build_sync_status(created, changed_fields)


def transform_credit_note(xero_note: Any, xero_id: UUID | str) -> tuple[CreditNote, str] | None:
    """Convert a Xero credit note into a CreditNote instance."""
    fields = _extract_required_fields_xero("credit_note", xero_note, xero_id)
    note, created = CreditNote.objects.get_or_create(xero_id=xero_id, defaults=fields)
    changed_fields = _track_and_apply_changes(note, fields) if not created else []
    if changed_fields:
        note.save()
    set_invoice_or_bill_fields(note, "CREDIT_NOTE")
    if created:
        note.save()
    return note, _build_sync_status(created, changed_fields)


def transform_stock(  # noqa: C901, PLR0912 -- ported v1 shape; each branch is one Xero item-payload quirk
    xero_item: Any, xero_id: UUID | str
) -> tuple[Stock, str]:
    """Convert a Xero item into a Stock instance."""
    # Basic required fields - NO FALLBACKS, fail early if missing
    item_code = getattr(xero_item, "code", None)
    description = getattr(xero_item, "name", None)
    is_tracked = getattr(xero_item, "is_tracked_as_inventory", None)
    xero_last_modified = getattr(xero_item, "updated_date_utc", None)
    raw_json = process_xero_data(xero_item)

    required_fields: dict[str, Any] = {
        "code": item_code,
        "name": description,
        "is_tracked_as_inventory": is_tracked,
        "updated_date_utc": xero_last_modified,
    }

    # Only access and validate quantity_on_hand for tracked items
    if is_tracked:
        quantity = getattr(xero_item, "quantity_on_hand", None)
        required_fields["quantity_on_hand"] = quantity

    validate_required_fields(required_fields, "item", str(xero_id))

    # After validation: quantity is proven non-None for tracked items, so
    # this cannot manufacture Decimal("None").
    quantity_value = (
        Decimal(str(required_fields["quantity_on_hand"])) if is_tracked else Decimal("0")
    )

    defaults: dict[str, Any] = {
        "item_code": item_code,
        "description": description,
        "quantity": quantity_value,
        "raw_json": raw_json,
        "xero_last_modified": xero_last_modified,
        "xero_last_synced": timezone.now(),
        "xero_inventory_tracked": is_tracked,
        "source": "product_catalog",
    }
    if not xero_item.sales_details or xero_item.sales_details.unit_price is None:
        logger.warning(
            "Item %s: Missing sales_details.unit_price, setting unit_revenue to 0", xero_id
        )
        defaults["unit_revenue"] = Decimal("0")
    else:
        defaults["unit_revenue"] = Decimal(str(xero_item.sales_details.unit_price))

    # Zero cost means we can supply it at no cost to us.
    if not xero_item.purchase_details or xero_item.purchase_details.unit_price is None:
        logger.warning(
            "Item %s: Missing purchase_details.unit_price, setting unit_cost to 0", xero_id
        )
        defaults["unit_cost"] = Decimal("0")
    else:
        defaults["unit_cost"] = Decimal(str(xero_item.purchase_details.unit_price))

    # Find existing stock by xero_id first, then by item_code (handles Stock
    # created locally without a xero_id yet).
    stock = Stock.objects.filter(xero_id=str(xero_id)).first()
    if not stock and item_code:
        stock = Stock.objects.filter(item_code=item_code).first()

    xero_id_updated = False
    if stock:
        created = False
        if stock.xero_id != str(xero_id):
            stock.xero_id = str(xero_id)
            xero_id_updated = True
    else:
        stock = Stock.objects.create(xero_id=str(xero_id), **defaults)
        created = True

    changed_fields = _track_and_apply_changes(stock, defaults)
    if xero_id_updated:
        changed_fields.append("xero_id")
    if changed_fields:
        stock.save()
    relevant_parse_fields = {"description", "item_code", "specifics"}
    if created or relevant_parse_fields.intersection(changed_fields):
        if stock_metadata_parse_eligible(stock):
            enqueue_stock_metadata_parse(stock.id)
        else:
            pass  # Existing metadata is complete; no parser task needed.
    else:
        pass  # No parser-relevant Xero fields changed.
    return stock, _build_sync_status(created, changed_fields)


def transform_quote(xero_quote: Any, xero_id: UUID | str) -> tuple[Quote, str]:
    """Convert a Xero quote into a Quote instance."""
    company = resolve_company_from_xero_contact(
        getattr(xero_quote, "contact", None), f"quote {xero_id}"
    )
    raw_json = process_xero_data(xero_quote)

    status_data = raw_json.get("_status", {})
    status = status_data.get("_value_") if isinstance(status_data, dict) else None
    validate_required_fields(
        {
            "status": status,
            "sub_total": raw_json.get("_sub_total"),
            "total": raw_json.get("_total"),
        },
        "quote",
        str(xero_id),
    )

    defaults: dict[str, Any] = {
        "company": company,
        "date": raw_json.get("_date"),
        "number": getattr(xero_quote, "quote_number", None),
        "status": status,
        "total_excl_tax": Decimal(str(raw_json.get("_sub_total"))),
        "total_incl_tax": Decimal(str(raw_json.get("_total"))),
        "xero_last_modified": raw_json.get("_updated_date_utc"),
        "xero_last_synced": timezone.now(),
        "online_url": f"https://go.xero.com/app/quotes/edit/{xero_id}",
        "raw_json": raw_json,
    }
    quote, created = Quote.objects.get_or_create(xero_id=xero_id, defaults=defaults)
    changed_fields = _track_and_apply_changes(quote, defaults) if not created else []
    if changed_fields:
        quote.save()
    return quote, _build_sync_status(created, changed_fields)


def transform_purchase_order(  # noqa: C901, PLR0915 -- ported v1 shape; header + per-line handling in one pass
    xero_po: Any, xero_id: UUID | str
) -> tuple[PurchaseOrder, str]:
    """Convert a Xero purchase order into a PurchaseOrder instance."""
    status_map = {
        "DRAFT": "draft",
        "SUBMITTED": "submitted",
        "AUTHORISED": "submitted",
        "BILLED": "fully_received",
        "VOIDED": "deleted",
    }

    def map_status(raw_status: str) -> str:
        # Unknown statuses fail this PO's sync (XeroError row via the
        # per-item handler) instead of silently becoming "draft" — a v1
        # default that could revert a real PO to draft locally.
        mapped = status_map.get(raw_status)
        if mapped is None:
            raise ValueError(f"Unknown Xero purchase order status {raw_status!r}")
        return mapped

    supplier = resolve_company_from_xero_contact(
        getattr(xero_po, "contact", None), xero_po.purchase_order_number
    )

    po_number = getattr(xero_po, "purchase_order_number", None)
    order_date = getattr(xero_po, "date", None)
    status = getattr(xero_po, "status", None)
    xero_last_modified = getattr(xero_po, "updated_date_utc", None)
    raw_json = process_xero_data(xero_po)
    validate_required_fields(
        {
            "purchase_order_number": po_number,
            "date": order_date,
            "status": status,
        },
        "purchase_order",
        str(xero_id),
    )
    po_number = required(po_number, "purchase_order_number", "purchase_order", str(xero_id))
    order_date = required(order_date, "date", "purchase_order", str(xero_id))
    status = required(status, "status", "purchase_order", str(xero_id))
    # Check for existing PO by xero_id first, then by po_number
    # (po_number has unique constraint but xero_id is the canonical link)
    created = False
    linked = False
    po = PurchaseOrder.objects.filter(xero_id=xero_id).first()
    if not po:
        po = PurchaseOrder.objects.filter(po_number=po_number).first()
        if po:
            po.xero_id = xero_id
            linked = True
            logger.info("Linked existing PO %s to Xero ID %s", po_number, xero_id)
    if not po:
        po = PurchaseOrder.objects.create(
            xero_id=xero_id,
            supplier=supplier,
            po_number=po_number,
            order_date=order_date,
            status=map_status(status),
            xero_last_modified=xero_last_modified,
            raw_json=raw_json,
        )
        created = True

    new_values: dict[str, Any] = {
        "po_number": po_number,
        "order_date": order_date,
        "expected_delivery": getattr(xero_po, "delivery_date", None),
        "xero_last_modified": xero_last_modified,
        "xero_last_synced": timezone.now(),
        "status": map_status(status),
        "raw_json": raw_json,
    }
    changed_fields = _track_and_apply_changes(po, new_values)
    if changed_fields or created or linked:
        po.save()

    if xero_po.line_items:
        for line in xero_po.line_items:
            description = getattr(line, "description", None)
            quantity = getattr(line, "quantity", None)
            if not description or quantity is None:
                missing = []
                if not description:
                    missing.append("description")
                if quantity is None:
                    missing.append("quantity")
                error_msg = f"Skipping PO line in {po_number} - missing {', '.join(missing)}"
                logger.error(error_msg)
                XeroError.objects.create(
                    message=error_msg,
                    data={"po_number": po_number, "missing_fields": missing},
                    entity="purchase_order_line",
                    reference_id=str(xero_id),
                    kind="missing_field",
                )
                continue
            try:
                line_item_id = getattr(line, "line_item_id", None)
                raw_line_data = process_xero_data(line)

                # Match on Xero's unique line item ID
                logger.info(
                    "Processing PO line: xero_line_item_id=%s, description='%.50s...'",
                    line_item_id,
                    description,
                )
                po_line, line_created = PurchaseOrderLine.objects.update_or_create(
                    purchase_order=po,
                    xero_line_item_id=line_item_id,
                    defaults={
                        "description": description,
                        "supplier_item_code": line.item_code or None,
                        "quantity": quantity,
                        "unit_cost": getattr(line, "unit_amount", None),
                        "raw_line_data": raw_line_data,
                    },
                )
                logger.info("PO line %s: %s", "created" if line_created else "updated", po_line.id)
            # deliberate-swallow: duplicated line rows are a known v1 data
            # wart; skipping the line keeps the rest of the PO syncing while
            # the log names the conflict for manual repair
            except PurchaseOrderLine.MultipleObjectsReturned:
                logger.error(
                    "Multiple PurchaseOrderLine records found for document '%s' "
                    "(Xero ID: %s), line item: '%s', supplier_item_code: '%s'",
                    po_number,
                    xero_id,
                    description,
                    line.item_code or "",
                )
                continue

    # "linked" is special case for POs - existing PO matched by po_number
    if linked:
        return po, "linked"
    return po, _build_sync_status(created, changed_fields)


def transform_pay_run(xero_pay_run: Any, xero_id: UUID | str) -> tuple[XeroPayRun, str]:
    """Convert a Xero pay run into a XeroPayRun instance."""
    payroll_calendar_id = getattr(xero_pay_run, "payroll_calendar_id", None)
    period_start_date = getattr(xero_pay_run, "period_start_date", None)
    period_end_date = getattr(xero_pay_run, "period_end_date", None)
    payment_date = getattr(xero_pay_run, "payment_date", None)
    pay_run_status = getattr(xero_pay_run, "pay_run_status", None)
    pay_run_type = getattr(xero_pay_run, "pay_run_type", None)
    total_cost = getattr(xero_pay_run, "total_cost", None)
    total_pay = getattr(xero_pay_run, "total_pay", None)
    # Xero pay runs don't have updated_date_utc like invoices do.
    # Posted runs have posted_date_time; Draft runs have no timestamp at all.
    # Fall back to current time for Draft runs since Xero provides nothing.
    posted_date_time = getattr(xero_pay_run, "posted_date_time", None)
    if posted_date_time:
        # Xero returns naive datetime, make it timezone-aware (assume UTC)
        if timezone.is_naive(posted_date_time):
            posted_date_time = posted_date_time.replace(tzinfo=UTC)
        xero_last_modified = posted_date_time
    else:
        xero_last_modified = timezone.now()
    raw_json = process_xero_data(xero_pay_run)

    # Convert dates if they're datetime objects
    if period_start_date is not None and hasattr(period_start_date, "date"):
        period_start_date = period_start_date.date()
    if period_end_date is not None and hasattr(period_end_date, "date"):
        period_end_date = period_end_date.date()
    if payment_date is not None and hasattr(payment_date, "date"):
        payment_date = payment_date.date()

    validate_required_fields(
        {
            "period_start_date": period_start_date,
            "period_end_date": period_end_date,
            "payment_date": payment_date,
        },
        "pay_run",
        str(xero_id),
    )

    defaults: dict[str, Any] = {
        "xero_tenant_id": get_tenant_id(),
        "payroll_calendar_id": payroll_calendar_id,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "payment_date": payment_date,
        "pay_run_status": pay_run_status,
        "pay_run_type": pay_run_type,
        "total_cost": Decimal(str(total_cost)) if total_cost is not None else None,
        "total_pay": Decimal(str(total_pay)) if total_pay is not None else None,
        "xero_last_modified": xero_last_modified,
        "xero_last_synced": timezone.now(),
        "raw_json": raw_json,
    }
    pay_run, created = XeroPayRun.objects.get_or_create(xero_id=xero_id, defaults=defaults)
    changed_fields = _track_and_apply_changes(pay_run, defaults) if not created else []
    if changed_fields:
        pay_run.save()

    return pay_run, _build_sync_status(created, changed_fields)


def transform_pay_slip(xero_pay_slip: Any, xero_id: UUID | str) -> tuple[XeroPaySlip, str] | None:
    """Convert a Xero pay slip into a XeroPaySlip instance (None if pay run missing)."""
    pay_run_id = getattr(xero_pay_slip, "pay_run_id", None)
    employee_id = getattr(xero_pay_slip, "employee_id", None)
    first_name = getattr(xero_pay_slip, "first_name", "")
    last_name = getattr(xero_pay_slip, "last_name", "")
    employee_name = f"{first_name} {last_name}".strip()

    gross_earnings = getattr(xero_pay_slip, "gross_earnings", 0) or 0
    tax_amount = getattr(xero_pay_slip, "tax", 0) or 0
    net_pay = getattr(xero_pay_slip, "net_pay", 0) or 0
    # Xero pay slips don't have updated_date_utc. Use current time.
    xero_last_modified = timezone.now()
    raw_json = process_xero_data(xero_pay_slip)

    validate_required_fields(
        {
            "pay_run_id": pay_run_id,
            "employee_id": employee_id,
            # "" would violate the employee_name_not_blank constraint and
            # surface as an unexplained IntegrityError; a nameless slip is
            # malformed remote data, reported as such.
            "employee_name": employee_name or None,
        },
        "pay_slip",
        str(xero_id),
    )
    pay_run_id = required(pay_run_id, "pay_run_id", "pay_slip", str(xero_id))

    try:
        pay_run = XeroPayRun.objects.get(xero_id=pay_run_id)
    # deliberate-swallow: pay slips arrive in the same sync pass as their
    # runs; a missing parent means the run's own transform failed and was
    # already recorded — skipping the slip avoids a duplicate error per slip
    except XeroPayRun.DoesNotExist:
        logger.warning("PayRun %s not found for PaySlip %s - skipping", pay_run_id, xero_id)
        return None

    # Extract hours from earnings lines
    timesheet_hours = Decimal("0")
    leave_hours = Decimal("0")

    timesheet_lines = getattr(xero_pay_slip, "timesheet_earnings_lines", None) or []
    for line in timesheet_lines:
        units = getattr(line, "number_of_units", None)
        if units:
            timesheet_hours += Decimal(str(units))

    leave_lines = getattr(xero_pay_slip, "leave_earnings_lines", None) or []
    for line in leave_lines:
        units = getattr(line, "number_of_units", None)
        if units:
            leave_hours += Decimal(str(units))

    defaults: dict[str, Any] = {
        "xero_tenant_id": get_tenant_id(),
        "pay_run": pay_run,
        "xero_employee_id": employee_id,
        "employee_name": employee_name,
        "gross_earnings": Decimal(str(gross_earnings)),
        "tax_amount": Decimal(str(tax_amount)),
        "net_pay": Decimal(str(net_pay)),
        "timesheet_hours": timesheet_hours,
        "leave_hours": leave_hours,
        "xero_last_modified": xero_last_modified,
        "xero_last_synced": timezone.now(),
        "raw_json": raw_json,
    }
    pay_slip, created = XeroPaySlip.objects.get_or_create(xero_id=xero_id, defaults=defaults)
    changed_fields = _track_and_apply_changes(pay_slip, defaults) if not created else []
    if changed_fields:
        pay_slip.save()

    return pay_slip, _build_sync_status(created, changed_fields)


def resolve_pending_merge(company: Company, logger_prefix: str) -> None:
    """Resolve a Xero contact merge: set the pointer, block jobs, move FKs.

    One implementation for both sync paths (hourly batch and webhook) — v1
    carried a diverging copy in each. A merge target not yet synced defers
    with a warning; the next sync retries.
    """
    if not company.xero_merged_into_id or company.merged_into:
        return
    merged_into = Company.objects.filter(xero_contact_id=company.xero_merged_into_id).first()
    if not merged_into:
        logger.warning(
            "Deferred merge: company %s points at unsynced "
            "xero_contact_id=%s; reassignment will retry next sync",
            company.id,
            company.xero_merged_into_id,
        )
        return
    company.merged_into = merged_into
    company.allow_jobs = False
    company.save()
    destination = company.get_final_company()
    if destination.id != company.id:
        # Call-time imports: keep this module importable pre-registry.
        from apps.accounts.models import Staff  # noqa: PLC0415
        from apps.company.services.company_merge_service import (  # noqa: PLC0415
            reassign_company_fk_records,
        )

        reassign_company_fk_records(
            company,
            destination,
            Staff.get_automation_user(),
            logger_prefix=logger_prefix,
        )


def sync_companies(
    xero_contacts: Iterable[Any],
) -> list[Company]:
    """Sync Xero contacts to the Company model (name-link, archive, merge rules)."""
    companies: list[Company] = []

    for contact in xero_contacts:
        raw_json = process_xero_data(contact)
        company: Company

        existing_company = Company.objects.filter(xero_contact_id=contact.contact_id).first()

        if existing_company:
            # Already linked - just update with latest Xero data.
            # xero_archived is NOT pre-set here: set_company_fields below owns
            # the archive-state derivation, and pre-writing it destroyed the
            # was_archived transition its allow_jobs restore keys off (v1 had
            # this ordering; the unarchive restore was dead code on the
            # hourly path — ledgered).
            company = existing_company
            company.raw_json = raw_json
            company.xero_last_modified = timezone.now()
            company.xero_merged_into_id = getattr(contact, "merged_to_contact_id", None)
            company.save()
            created = False
        else:
            # Not linked yet - check if name already exists in our database
            # `or ""`, not a .get default: Xero's null arrives as a PRESENT
            # None, which would dodge the default and crash .strip().
            contact_name = (raw_json.get("_name") or "").strip()
            if contact_name:
                matching_company = Company.objects.filter(name=contact_name).first()

                if matching_company:
                    if matching_company.xero_contact_id is None:
                        # Safe to link - no existing Xero ID. As above,
                        # xero_archived is left to set_company_fields.
                        matching_company.xero_contact_id = contact.contact_id
                        matching_company.raw_json = raw_json
                        matching_company.xero_last_modified = timezone.now()
                        matching_company.xero_merged_into_id = getattr(
                            contact, "merged_to_contact_id", None
                        )
                        matching_company.save()
                        logger.info(
                            "Linked existing company '%s' (ID: %s) to Xero contact %s",
                            contact_name,
                            matching_company.id,
                            contact.contact_id,
                        )
                        company = matching_company
                        created = False
                    elif contact.contact_status == "ARCHIVED":
                        # Archived contact with same name as an existing company
                        # linked to a different (active) Xero contact. This
                        # commonly happens when Xero merges contacts — the old
                        # record is archived. Create a separate archived company.
                        logger.warning(
                            "Archived Xero contact '%s' (%s) has same name as company "
                            "already linked to %s. Creating separate archived company record.",
                            contact_name,
                            contact.contact_id,
                            matching_company.xero_contact_id,
                        )
                        company = Company.objects.create(
                            xero_contact_id=contact.contact_id,
                            raw_json=raw_json,
                            xero_last_modified=timezone.now(),
                            xero_archived=True,
                            xero_merged_into_id=getattr(contact, "merged_to_contact_id", None),
                        )
                        created = True
                    else:
                        # Active contact name collision — real conflict
                        raise ValueError(
                            f"Name '{contact_name}' already linked to Xero ID "
                            f"{matching_company.xero_contact_id}, cannot link to "
                            f"{contact.contact_id}"
                        )
                else:
                    # No existing company with this name - safe to create new one
                    company = Company.objects.create(
                        xero_contact_id=contact.contact_id,
                        raw_json=raw_json,
                        xero_last_modified=timezone.now(),
                        xero_archived=contact.contact_status == "ARCHIVED",
                        xero_merged_into_id=getattr(contact, "merged_to_contact_id", None),
                    )
                    created = True
            else:
                # No name in contact - create anyway
                company = Company.objects.create(
                    xero_contact_id=contact.contact_id,
                    raw_json=raw_json,
                    xero_last_modified=timezone.now(),
                    xero_archived=contact.contact_status == "ARCHIVED",
                    xero_merged_into_id=getattr(contact, "merged_to_contact_id", None),
                )
                created = True

        set_company_fields(company, new_from_xero=created)
        companies.append(company)

    # Resolve merges and move stranded FK records onto the terminal company.
    for company in companies:
        resolve_pending_merge(company, logger_prefix="[batch-sync] ")

    return companies


def sync_accounts(xero_accounts: Iterable[Account]) -> None:
    """Sync Xero chart-of-accounts rows into XeroAccount."""
    for account in xero_accounts:
        # updated_date_utc joins the guard because xero_last_modified is NOT
        # NULL: the stub used to declare it Any, which let a None through to
        # an IntegrityError deep in the loop instead of naming the payload.
        if account.account_id is None or account.name is None or account.updated_date_utc is None:
            raise ValueError(
                "Xero account payload missing id, name or updated_date_utc "
                f"(id={account.account_id!r})"
            )
        XeroAccount.objects.update_or_create(
            xero_id=account.account_id,
            defaults={
                "xero_tenant_id": get_tenant_id(),
                "account_code": account.code or None,
                "account_name": account.name,
                "description": account.description or None,
                # .value, not str(): the SDK deserialises type as an
                # AccountType enum, and str() persists "AccountType.BANK".
                "account_type": account.type.value if account.type else None,
                "tax_type": account.tax_type or None,
                "enable_payments": bool(account.enable_payments_to_account),
                "xero_last_modified": account.updated_date_utc,
                "xero_last_synced": timezone.now(),
                "raw_json": process_xero_data(account),
            },
        )
