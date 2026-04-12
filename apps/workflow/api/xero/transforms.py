import logging
import time
from datetime import date, datetime
from datetime import timezone as dt_timezone
from decimal import Decimal
from uuid import UUID

from django.utils import timezone
from xero_python.accounting import AccountingApi

from apps.accounting.models import Bill, CreditNote, Invoice, Quote
from apps.client.models import Client
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Stock
from apps.workflow.api.xero.reprocess_xero import (
    set_client_fields,
    set_invoice_or_bill_fields,
    set_journal_fields,
)
from apps.workflow.api.xero.auth import api_client, get_tenant_id
from apps.workflow.exceptions import XeroValidationError
from apps.workflow.models import (
    XeroAccount,
    XeroError,
    XeroJournal,
    XeroPayRun,
    XeroPaySlip,
)
from apps.workflow.services.error_persistence import (
    persist_app_error,
    persist_xero_error,
)
from apps.workflow.services.validation import validate_required_fields

logger = logging.getLogger("xero")

SLEEP_TIME = 1  # Sleep after every API call to avoid hitting rate limits


def _build_sync_status(created: bool, changed_fields: list) -> str:
    """Build a status string describing what changed during sync."""
    if created:
        return "created"
    if changed_fields:
        return f"{len(changed_fields)} fields incl {changed_fields[0]}"
    return "unchanged"


def _track_and_apply_changes(instance, fields: dict) -> list:
    """Compare fields against instance, apply changes, return list of changed field names."""
    changed = []
    for key, value in fields.items():
        if getattr(instance, key, None) != value:
            setattr(instance, key, value)
            changed.append(key)
    return changed


def serialize_xero_object(obj):
    """Convert Xero objects to JSON-serializable format"""
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    elif isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, UUID):
        return str(obj)
    elif isinstance(obj, (list, tuple)):
        return [serialize_xero_object(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: serialize_xero_object(value) for key, value in obj.items()}
    elif hasattr(obj, "__dict__"):
        return serialize_xero_object(obj.__dict__)
    else:
        return str(obj)


def clean_json(data):
    """Remove Xero's internal fields and bulky repeated data"""
    if not isinstance(data, dict):
        return data

    exclude_keys = {
        "_currency_code",
        "_currency_rate",
        "_value2member_map_",
        "_generate_next_value_",
        "_member_names_",
        "__objclass__",
    }

    cleaned = {}
    for key, value in data.items():
        if key in exclude_keys or any(
            pattern in key
            for pattern in [
                "_value2member_map_",
                "_generate_next_value_",
                "_member_names_",
                "__objclass__",
            ]
        ):
            continue

        if isinstance(value, dict):
            cleaned[key] = clean_json(value)
        elif isinstance(value, list):
            cleaned[key] = [
                clean_json(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            cleaned[key] = value

    return cleaned


def process_xero_data(xero_obj):
    """Standard processing for all Xero objects"""
    return clean_json(serialize_xero_object(xero_obj))


def get_or_fetch_client(contact_id, reference=None):
    """Get client by Xero contact_id, fetching from API if needed"""
    client = Client.objects.filter(xero_contact_id=contact_id).first()
    if client:
        return client.get_final_client()

    response = AccountingApi(api_client).get_contacts(
        get_tenant_id(), i_ds=[contact_id], include_archived=True
    )
    time.sleep(SLEEP_TIME)

    if not response.contacts:
        raise ValueError(f"Client not found for {reference or contact_id}")

    synced = sync_clients([response.contacts[0]])
    if not synced:
        raise ValueError(f"Failed to sync client for {reference or contact_id}")

    return synced[0].get_final_client()


def sync_entities(
    items, model_class, xero_id_attr, transform_func, delete_orphans=False
):
    """Persist a batch of Xero objects.

    Args:
        items: Iterable of objects from Xero.
        model_class: Django model used for storage.
        xero_id_attr: Attribute name of the Xero ID on each item.
        transform_func: Callable returning (instance, status) tuple or None.
        delete_orphans: If True, delete local records not in the fetched set.
            Use for cache-only entities where Xero is the master.

    Returns:
        int: Number of items successfully synced.
    """
    # Convert to list if we need to iterate twice (for delete_orphans)
    items_list = list(items) if delete_orphans else items

    if delete_orphans:
        xero_ids = {getattr(item, xero_id_attr) for item in items_list}
        deleted, _ = model_class.objects.exclude(xero_id__in=xero_ids).delete()
        if deleted:
            logger.info(f"Deleted {deleted} orphaned {model_class.__name__} records")

    synced = 0
    for item in items_list:
        xero_id = getattr(item, xero_id_attr)

        # Xero omits fields for deleted docs so we skip to avoid errors
        if getattr(item, "status", None) == "DELETED":
            logger.info(f"Skipping deleted {model_class.__name__} {xero_id}")
            continue

        try:
            result = transform_func(item, xero_id)
        except XeroValidationError as exc:
            persist_xero_error(exc)
            logger.error(f"Failed to sync {model_class.__name__} {xero_id}: {exc}")
            continue
        except Exception as exc:
            persist_app_error(exc)
            logger.error(f"Failed to sync {model_class.__name__} {xero_id}: {exc}")
            continue
        if not result:
            continue
        instance, status = result
        identifier = getattr(instance, "number", getattr(instance, "name", xero_id))
        logger.info(f"Synced {model_class.__name__}: {identifier} ({status})")
        synced += 1
    return synced


def _resolve_document_number(
    doc_type: str, xero_obj, xero_id: UUID | str
) -> str | None:
    """Return the canonical document number provided by Xero."""
    match doc_type:
        case "invoice" | "bill":
            primary = getattr(xero_obj, "invoice_number", None)
        case "credit_note":
            primary = getattr(xero_obj, "credit_note_number", None)
        case _:
            logger.error(f"Unknown document type for Xero sync: {doc_type}")
            return None

    return str(primary) if primary is not None else None


def _extract_required_fields_xero(doc_type, xero_obj, xero_id):
    """Gather required values from a Xero document.

    Args:
        doc_type: Name of the document type.
        xero_obj: Object returned from Xero.
        xero_id: Identifier of the Xero object.

    Returns:
        Mapping of required field names to values.
    """
    number = _resolve_document_number(doc_type, xero_obj, xero_id)
    client = get_or_fetch_client(xero_obj.contact.contact_id, number)
    date = getattr(xero_obj, "date", None)
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

    required_fields = {
        "client": client,
        "date": date,
        "number": number,
        "total_excl_tax": total_excl_tax,
        "tax": tax,
        "total_incl_tax": total_incl_tax,
        "amount_due": amount_due,
        "xero_last_modified": xero_last_modified,
        "raw_json": raw_json,
    }
    validate_required_fields(required_fields, doc_type, xero_id)
    return required_fields


def transform_invoice(xero_invoice, xero_id):
    """Convert a Xero invoice into an Invoice instance.

    Args:
        xero_invoice: Invoice object from Xero.
        xero_id: Identifier of the invoice in Xero.

    Returns:
        The saved Invoice model.
    """
    fields = _extract_required_fields_xero("invoice", xero_invoice, xero_id)
    if not fields:
        return None
    invoice, created = Invoice.objects.get_or_create(xero_id=xero_id, defaults=fields)
    changed_fields = _track_and_apply_changes(invoice, fields) if not created else []
    if changed_fields:
        invoice.save()
    set_invoice_or_bill_fields(invoice, "INVOICE")
    if created:
        invoice.save()

    # Recalculate job state if invoice is linked to a job
    if invoice.job:
        from apps.job.services.job_service import recalculate_job_invoicing_state

        recalculate_job_invoicing_state(invoice.job.id)

    return invoice, _build_sync_status(created, changed_fields)


def transform_bill(xero_bill, xero_id):
    """Convert a Xero bill into a Bill instance.

    Args:
        xero_bill: Bill object from Xero.
        xero_id: Identifier of the bill in Xero.

    Returns:
        The saved Bill model.
    """
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
    if not fields:
        return None
    bill, created = Bill.objects.get_or_create(xero_id=xero_id, defaults=fields)
    changed_fields = _track_and_apply_changes(bill, fields) if not created else []
    if changed_fields:
        bill.save()
    set_invoice_or_bill_fields(bill, "BILL")
    if created:
        bill.save()
    return bill, _build_sync_status(created, changed_fields)


def transform_credit_note(xero_note, xero_id):
    """Convert a Xero credit note into a CreditNote instance.

    Args:
        xero_note: Credit note object from Xero.
        xero_id: Identifier of the credit note in Xero.

    Returns:
        The saved CreditNote model.
    """
    fields = _extract_required_fields_xero("credit_note", xero_note, xero_id)
    if not fields:
        return None
    note, created = CreditNote.objects.get_or_create(xero_id=xero_id, defaults=fields)
    changed_fields = _track_and_apply_changes(note, fields) if not created else []
    if changed_fields:
        note.save()
    set_invoice_or_bill_fields(note, "CREDIT_NOTE")
    if created:
        note.save()
    return note, _build_sync_status(created, changed_fields)


def transform_journal(xero_journal, xero_id):
    """Convert a Xero journal into a XeroJournal instance.

    Args:
        xero_journal: Journal object from Xero.
        xero_id: Identifier of the journal in Xero.

    Returns:
        The saved XeroJournal model.
    """
    journal_date = getattr(xero_journal, "journal_date", None)
    created_date_utc = getattr(xero_journal, "created_date_utc", None)
    journal_number = getattr(xero_journal, "journal_number", None)
    raw_json = process_xero_data(xero_journal)
    validate_required_fields(
        {
            "journal_date": journal_date,
            "created_date_utc": created_date_utc,
            "journal_number": journal_number,
        },
        "journal",
        xero_id,
    )

    defaults = {
        "journal_date": journal_date,
        "created_date_utc": created_date_utc,
        "journal_number": journal_number,
        "raw_json": raw_json,
        # CREATED is correct! Xero journals are non-editable
        "xero_last_modified": created_date_utc,
    }
    journal, created = XeroJournal.objects.get_or_create(
        xero_id=xero_id,
        defaults=defaults,
    )
    # Journals are non-editable in Xero, so changed_fields will always be empty
    changed_fields = _track_and_apply_changes(journal, defaults)
    set_journal_fields(journal)
    if created or changed_fields:
        journal.save()
    return journal, _build_sync_status(created, changed_fields)


def transform_stock(xero_item, xero_id):
    """Convert a Xero item into a Stock instance.

    Args:
        xero_item: Item object from Xero.
        xero_id: Identifier of the item in Xero.

    Returns:
        The saved Stock model.
    """
    # Get basic required fields - NO FALLBACKS, fail early if missing
    item_code = getattr(xero_item, "code", None)
    description = getattr(xero_item, "name", None)
    is_tracked = getattr(xero_item, "is_tracked_as_inventory", None)
    xero_last_modified = getattr(xero_item, "updated_date_utc", None)
    raw_json = process_xero_data(xero_item)

    # Base validation requirements (always required)
    required_fields = {
        "code": item_code,
        "name": description,
        "is_tracked_as_inventory": is_tracked,
        "updated_date_utc": xero_last_modified,
    }

    # Only access and validate quantity_on_hand for tracked items
    if is_tracked:
        quantity = getattr(xero_item, "quantity_on_hand", None)
        required_fields["quantity_on_hand"] = quantity
        quantity_value = Decimal(str(quantity))
    else:
        # For untracked items, don't access quantity_on_hand at all
        quantity_value = Decimal("0")

    validate_required_fields(required_fields, "item", xero_id)

    defaults = {
        "item_code": item_code,
        "description": description,
        "quantity": quantity_value,
        "raw_json": raw_json,
        "xero_last_modified": xero_last_modified,
        "xero_last_synced": timezone.now(),
        "xero_inventory_tracked": is_tracked,
        "source": "product_catalog",
    }
    # Handle missing sales_details.unit_price (set default if missing)
    if not xero_item.sales_details or xero_item.sales_details.unit_price is None:
        logger.warning(
            f"Item {xero_id}: Missing sales_details.unit_price, setting unit_revenue to 0"
        )
        defaults["unit_revenue"] = Decimal("0")
    else:
        defaults["unit_revenue"] = Decimal(str(xero_item.sales_details.unit_price))

    # Zero cost means we can supply it at no cost to us.
    if not xero_item.purchase_details or xero_item.purchase_details.unit_price is None:
        logger.warning(
            f"Item {xero_id}: Missing purchase_details.unit_price, setting unit_cost to 0"
        )
        defaults["unit_cost"] = Decimal("0")
    else:
        defaults["unit_cost"] = Decimal(str(xero_item.purchase_details.unit_price))

    # Try to find existing stock by xero_id first, then by item_code
    # (handles case where Stock was created locally without xero_id)
    stock = Stock.objects.filter(xero_id=xero_id).first()
    if not stock and item_code:
        stock = Stock.objects.filter(item_code=item_code).first()

    xero_id_updated = False
    if stock:
        created = False
        # Ensure xero_id is linked (in case we found by item_code)
        if stock.xero_id != xero_id:
            stock.xero_id = xero_id
            xero_id_updated = True
    else:
        stock = Stock.objects.create(xero_id=xero_id, **defaults)
        created = True

    changed_fields = _track_and_apply_changes(stock, defaults)
    if xero_id_updated:
        changed_fields.append("xero_id")
    if changed_fields:
        stock.save()
    return stock, _build_sync_status(created, changed_fields)


def transform_quote(xero_quote, xero_id):
    """Convert a Xero quote into a Quote instance.

    Args:
        xero_quote: Quote object from Xero.
        xero_id: Identifier of the quote in Xero.

    Returns:
        The saved Quote model.
    """
    client = get_or_fetch_client(xero_quote.contact.contact_id, f"quote {xero_id}")
    raw_json = process_xero_data(xero_quote)

    status_data = raw_json.get("_status", {})
    status = status_data.get("_value_") if isinstance(status_data, dict) else None
    validate_required_fields({"status": status}, "quote", xero_id)

    defaults = {
        "client": client,
        "date": raw_json.get("_date"),
        "number": getattr(xero_quote, "quote_number", None),
        "status": status,
        "total_excl_tax": Decimal(str(raw_json.get("_sub_total", 0))),
        "total_incl_tax": Decimal(str(raw_json.get("_total", 0))),
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


def transform_purchase_order(xero_po, xero_id):
    """Convert a Xero purchase order into a PurchaseOrder instance.

    Args:
        xero_po: Purchase order object from Xero.
        xero_id: Identifier of the purchase order in Xero.

    Returns:
        The saved PurchaseOrder model.
    """
    status_map = {
        "DRAFT": "draft",
        "SUBMITTED": "submitted",
        "AUTHORISED": "submitted",
        "BILLED": "fully_received",
        "VOIDED": "deleted",
    }
    supplier = get_or_fetch_client(
        xero_po.contact.contact_id, xero_po.purchase_order_number
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
        xero_id,
    )
    # Check for existing PO by xero_id first, then by po_number
    # (po_number has unique constraint but xero_id is the canonical link)
    created = False
    linked = False
    po = PurchaseOrder.objects.filter(xero_id=xero_id).first()
    if not po:
        po = PurchaseOrder.objects.filter(po_number=po_number).first()
        if po:
            # Link existing PO to Xero
            po.xero_id = xero_id
            linked = True
            logger.info(f"Linked existing PO {po_number} to Xero ID {xero_id}")
    if not po:
        po = PurchaseOrder.objects.create(
            xero_id=xero_id,
            supplier=supplier,
            po_number=po_number,
            order_date=order_date,
            status=status_map.get(status, "draft"),
            xero_last_modified=xero_last_modified,
            raw_json=raw_json,
        )
        created = True

    # Track field changes for existing POs
    new_values = {
        "po_number": po_number,
        "order_date": order_date,
        "expected_delivery": getattr(xero_po, "delivery_date", None),
        "xero_last_modified": xero_last_modified,
        "xero_last_synced": timezone.now(),
        "status": status_map.get(status, "draft"),
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
                error_msg = (
                    f"Skipping PO line in {po_number} - missing {', '.join(missing)}"
                )
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
                    f"Processing PO line: xero_line_item_id={line_item_id}, "
                    f"description='{description[:50]}...'"
                )
                po_line, created = PurchaseOrderLine.objects.update_or_create(
                    purchase_order=po,
                    xero_line_item_id=line_item_id,
                    defaults={
                        "description": description,
                        "supplier_item_code": line.item_code or "",
                        "quantity": quantity,
                        "unit_cost": getattr(line, "unit_amount", None),
                        "raw_line_data": raw_line_data,
                    },
                )
                logger.info(
                    f"PO line {'created' if created else 'updated'}: {po_line.id}"
                )
            except PurchaseOrderLine.MultipleObjectsReturned:
                logger.error(
                    f"Multiple PurchaseOrderLine records found for document '{po_number}' "
                    f"(Xero ID: {xero_id}), line item: '{description}', "
                    f"supplier_item_code: '{line.item_code or ''}'"
                )
                continue

    # "linked" is special case for POs - existing PO matched by po_number
    if linked:
        return po, "linked"
    return po, _build_sync_status(created, changed_fields)


def transform_pay_run(xero_pay_run, xero_id):
    """Convert a Xero pay run into a XeroPayRun instance.

    Args:
        xero_pay_run: PayRun object from Xero PayrollNzApi.
        xero_id: Identifier of the pay run in Xero (pay_run_id).

    Returns:
        The saved XeroPayRun model.
    """
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
            posted_date_time = posted_date_time.replace(tzinfo=dt_timezone.utc)
        xero_last_modified = posted_date_time
    else:
        xero_last_modified = timezone.now()
    raw_json = process_xero_data(xero_pay_run)

    # Convert dates if they're datetime objects
    if hasattr(period_start_date, "date"):
        period_start_date = period_start_date.date()
    if hasattr(period_end_date, "date"):
        period_end_date = period_end_date.date()
    if hasattr(payment_date, "date"):
        payment_date = payment_date.date()

    validate_required_fields(
        {
            "period_start_date": period_start_date,
            "period_end_date": period_end_date,
            "payment_date": payment_date,
        },
        "pay_run",
        xero_id,
    )

    defaults = {
        "xero_tenant_id": get_tenant_id(),
        "payroll_calendar_id": payroll_calendar_id,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "payment_date": payment_date,
        "pay_run_status": pay_run_status,
        "pay_run_type": pay_run_type,
        "total_cost": Decimal(str(total_cost)) if total_cost else None,
        "total_pay": Decimal(str(total_pay)) if total_pay else None,
        "xero_last_modified": xero_last_modified,
        "xero_last_synced": timezone.now(),
        "raw_json": raw_json,
    }
    pay_run, created = XeroPayRun.objects.get_or_create(
        xero_id=xero_id,
        defaults=defaults,
    )
    changed_fields = _track_and_apply_changes(pay_run, defaults) if not created else []
    if changed_fields:
        pay_run.save()

    return pay_run, _build_sync_status(created, changed_fields)


def transform_pay_slip(xero_pay_slip, xero_id):
    """Convert a Xero pay slip into a XeroPaySlip instance.

    Args:
        xero_pay_slip: PaySlip object from Xero PayrollNzApi.
        xero_id: Identifier of the pay slip in Xero (pay_slip_id).

    Returns:
        The saved XeroPaySlip model, or None if pay run not found.
    """
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
        },
        "pay_slip",
        xero_id,
    )

    # Find the parent pay run
    try:
        pay_run = XeroPayRun.objects.get(xero_id=pay_run_id)
    except XeroPayRun.DoesNotExist:
        logger.warning(
            f"PayRun {pay_run_id} not found for PaySlip {xero_id} - skipping"
        )
        return None

    # Extract hours from earnings lines
    timesheet_hours = Decimal("0")
    leave_hours = Decimal("0")

    # Get hours from timesheet_earnings_lines (actual worked hours)
    timesheet_lines = getattr(xero_pay_slip, "timesheet_earnings_lines", None) or []
    for line in timesheet_lines:
        units = getattr(line, "number_of_units", None)
        if units:
            timesheet_hours += Decimal(str(units))

    # Get hours from leave_earnings_lines (sick, annual leave, etc)
    leave_lines = getattr(xero_pay_slip, "leave_earnings_lines", None) or []
    for line in leave_lines:
        units = getattr(line, "number_of_units", None)
        if units:
            leave_hours += Decimal(str(units))

    defaults = {
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
    pay_slip, created = XeroPaySlip.objects.get_or_create(
        xero_id=xero_id,
        defaults=defaults,
    )
    changed_fields = _track_and_apply_changes(pay_slip, defaults) if not created else []
    if changed_fields:
        pay_slip.save()

    return pay_slip, _build_sync_status(created, changed_fields)


def sync_clients(xero_contacts):
    """Sync Xero contacts to Client model"""
    clients = []

    for contact in xero_contacts:
        raw_json = process_xero_data(contact)

        # Check if we already have a client with this xero_contact_id
        existing_client = Client.objects.filter(
            xero_contact_id=contact.contact_id
        ).first()

        if existing_client:
            # Already linked - just update with latest Xero data
            client = existing_client
            client.raw_json = raw_json
            client.xero_last_modified = timezone.now()
            client.xero_archived = contact.contact_status == "ARCHIVED"
            client.xero_merged_into_id = getattr(contact, "merged_to_contact_id", None)
            client.save()
            created = False
        else:
            # Not linked yet - check if name already exists in our database
            contact_name = raw_json.get("_name", "").strip()
            if contact_name:
                matching_client = Client.objects.filter(name=contact_name).first()

                if matching_client:
                    if matching_client.xero_contact_id is None:
                        # Safe to link - no existing Xero ID
                        matching_client.xero_contact_id = contact.contact_id
                        matching_client.raw_json = raw_json
                        matching_client.xero_last_modified = timezone.now()
                        matching_client.xero_archived = (
                            contact.contact_status == "ARCHIVED"
                        )
                        matching_client.xero_merged_into_id = getattr(
                            contact, "merged_to_contact_id", None
                        )
                        matching_client.save()
                        logger.info(
                            f"Linked existing client '{contact_name}' (ID: {matching_client.id}) to Xero contact {contact.contact_id}"
                        )
                        client = matching_client
                        created = False
                    else:
                        if contact.contact_status == "ARCHIVED":
                            # Archived contact with same name as an existing client
                            # linked to a different (active) Xero contact. This
                            # commonly happens when Xero merges contacts — the old
                            # record is archived. Create a separate archived client.
                            logger.warning(
                                f"Archived Xero contact '{contact_name}' ({contact.contact_id}) "
                                f"has same name as client already linked to {matching_client.xero_contact_id}. "
                                f"Creating separate archived client record."
                            )
                            client = Client.objects.create(
                                xero_contact_id=contact.contact_id,
                                raw_json=raw_json,
                                xero_last_modified=timezone.now(),
                                xero_archived=True,
                                xero_merged_into_id=getattr(
                                    contact, "merged_to_contact_id", None
                                ),
                            )
                            created = True
                        else:
                            # Active contact name collision — real conflict
                            raise ValueError(
                                f"Name '{contact_name}' already linked to Xero ID {matching_client.xero_contact_id}, cannot link to {contact.contact_id}"
                            )
                else:
                    # No existing client with this name - safe to create new one
                    client = Client.objects.create(
                        xero_contact_id=contact.contact_id,
                        raw_json=raw_json,
                        xero_last_modified=timezone.now(),
                        xero_archived=contact.contact_status == "ARCHIVED",
                        xero_merged_into_id=getattr(
                            contact, "merged_to_contact_id", None
                        ),
                    )
                    created = True
            else:
                # No name in contact - create anyway
                client = Client.objects.create(
                    xero_contact_id=contact.contact_id,
                    raw_json=raw_json,
                    xero_last_modified=timezone.now(),
                    xero_archived=contact.contact_status == "ARCHIVED",
                    xero_merged_into_id=getattr(contact, "merged_to_contact_id", None),
                )
                created = True

        set_client_fields(client, new_from_xero=created)
        clients.append(client)

    # Resolve merges
    for client in clients:
        if client.xero_merged_into_id and not client.merged_into:
            merged_into = Client.objects.filter(
                xero_contact_id=client.xero_merged_into_id
            ).first()
            if merged_into:
                client.merged_into = merged_into
                client.save()

    return clients


def sync_accounts(xero_accounts):
    """Sync Xero accounts"""
    for account in xero_accounts:
        XeroAccount.objects.update_or_create(
            xero_id=account.account_id,
            defaults={
                "account_code": account.code,
                "account_name": account.name,
                "description": getattr(account, "description", None),
                "account_type": account.type,
                "tax_type": account.tax_type,
                "enable_payments": getattr(
                    account, "enable_payments_to_account", False
                ),
                "xero_last_modified": account._updated_date_utc,
                "xero_last_synced": timezone.now(),
                "raw_json": process_xero_data(account),
            },
        )
