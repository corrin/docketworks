# workflow/xero/reprocess_xero.py
import logging
import uuid
from collections.abc import Mapping

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.accounting.models import (
    Bill,
    BillLineItem,
    CreditNote,
    CreditNoteLineItem,
    Invoice,
    InvoiceLineItem,
)
from apps.company.models import (
    Company,
    ContactMethod,
    SupplierPickupAddress,
)
from apps.crm.tasks import rematch_phone_calls_task
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models import XeroAccount
from apps.workflow.services.error_persistence import (
    persist_app_error,
)

logger = logging.getLogger("xero")


def _xero_phone_value(phone_entry: Mapping[str, str | None]) -> str:
    number = phone_entry.get("_phone_number") or ""
    area_code = phone_entry.get("_phone_area_code") or ""
    country_code = phone_entry.get("_phone_country_code") or ""
    return f"{country_code} {area_code} {number}".strip()


def sync_xero_phone_methods(company: Company) -> list[str]:
    """Ensure the company's Xero phone numbers exist as contact methods.

    Xero owns the number's existence; the CRM user owns label/is_primary.
    Existing rows are therefore never updated here — only missing numbers are
    created (label/is_primary/source are create-time defaults only).

    Returns the normalized numbers that were newly created, so the caller can
    dispatch a call rematch for them.
    """
    phones = company.raw_json.get("_phones", []) if company.raw_json else []
    if not isinstance(phones, list):
        return []

    created_numbers: list[str] = []
    for phone_entry in phones:
        if not isinstance(phone_entry, dict):
            continue
        value = _xero_phone_value(phone_entry)
        normalized = ContactMethod.normalize_phone(value)
        if not normalized:
            continue
        # The "one number, one company" rule is enforced by the grandfathered
        # ContactMethod.save() guard reached via get_or_create below:
        # re-syncing an existing number never saves (nothing to update), while
        # a genuinely-new cross-company number raises and hard-fails this
        # company's sync (deliberate — the data must be fixed, not skipped).
        phone_type = phone_entry.get("_phone_type") or ""
        try:
            _, created = ContactMethod.objects.get_or_create(
                company=company,
                method_type=ContactMethod.MethodType.PHONE,
                normalized_value=normalized,
                defaults={
                    "value": value,
                    "label": phone_type,
                    "is_primary": phone_type == "DEFAULT",
                    "source": ContactMethod.Source.IMPORTED,
                },
            )
        except AlreadyLoggedException:
            raise
        except ValidationError as exc:
            error = ValidationError(
                f"Xero phone sync for company '{company.name}' ({company.id}) "
                f"rejected number '{value}' ({normalized}): "
                f"{'; '.join(exc.messages)}"
            )
            app_error = persist_app_error(
                error,
                additional_context={
                    "operation": "sync_xero_phone_methods_duplicate_owner",
                    "client_id": str(company.id),
                    "normalized_number": normalized,
                },
            )
            raise AlreadyLoggedException(error, app_error.id) from exc
        if created:
            created_numbers.append(normalized)
    return created_numbers


def set_invoice_or_bill_fields(document, document_type, new_from_xero=False):
    """
    Process either an invoice or bill from Xero.

    Args:
        document: Instance of XeroInvoiceOrBill
        document_type: String either "INVOICE" or "BILL"
    """

    if not document.raw_json:
        raise ValueError(
            f"{document_type.title()} raw_json is empty. "
            "We better not try to process it"
        )

    if new_from_xero:
        logger.info(
            f"[XERO-WEBHOOK] Setting fields for new {document_type.lower()} "
            f"from Xero data: {document.number}"
            f"[XERO-WEBHOOK] Document ID: {document.xero_id}"
        )

    is_invoice = document.raw_json.get("_type") == "ACCREC"
    is_bill = document.raw_json.get("_type") == "ACCPAY"
    is_credit_note = document.raw_json.get("_type") in ["ACCRECCREDIT", "ACCPAYCREDIT"]

    if is_invoice:
        json_document_type = "INVOICE"
    elif is_bill:
        json_document_type = "BILL"
    elif is_credit_note:
        json_document_type = "CREDIT_NOTE"

    # Validate the document matches the type
    if document_type != json_document_type:
        raise ValueError(
            f"Document type mismatch. Got {document_type} "
            f"but document appears to be a {json_document_type}"
        )

    raw_data = document.raw_json

    # Common fields that are identical between invoices and bills
    if is_credit_note:
        document.xero_id = raw_data.get("_credit_note_id")
        document.number = raw_data.get("_credit_note_number")
    else:
        document.xero_id = raw_data.get("_invoice_id")
        document.number = raw_data.get("_invoice_number")
    document.date = raw_data.get("_date")
    document.due_date = raw_data.get("_due_date")
    document.status = raw_data.get("_status")
    document.tax = raw_data.get("_total_tax")
    document.total_excl_tax = raw_data.get("_sub_total")
    document.total_incl_tax = raw_data.get("_total")
    if document_type == "CREDIT_NOTE":
        document.amount_due = raw_data.get("_remaining_credit")
    else:
        document.amount_due = raw_data.get("_amount_due")
    updated_date_utc = raw_data.get("_updated_date_utc")
    if updated_date_utc:
        document.xero_last_modified = updated_date_utc
    else:
        document.xero_last_modified = document.xero_last_modified or timezone.now()
    document.xero_last_synced = timezone.now()

    # Set or create the company/supplier
    contact_data = raw_data.get("_contact", {})
    contact_id = contact_data.get("_contact_id")
    company = Company.objects.filter(xero_contact_id=contact_id).first()
    if not company:
        raise ValueError(
            f"Company not found for {document_type.lower()} {document.number}"
        )
    document.company = company

    document.save()

    # Handle line items
    line_items_data = raw_data.get("_line_items", [])
    amount_type = raw_data.get("_line_amount_types", {}).get("_value_")

    # Determine which line item model to use
    LineItemModel = (
        InvoiceLineItem
        if is_invoice
        else BillLineItem if is_bill else CreditNoteLineItem if is_credit_note else None
    )
    document_field = (
        "invoice"
        if is_invoice
        else "bill" if is_bill else "credit_note" if is_credit_note else None
    )

    for line_item_data in line_items_data:
        line_item_id = line_item_data.get("_line_item_id")
        xero_line_id = uuid.UUID(line_item_id)
        description = line_item_data.get("_description") or "No description provided"
        quantity = line_item_data.get("_quantity", 1)
        unit_price = line_item_data.get("_unit_amount", 1)

        try:
            line_amount = float(line_item_data.get("_line_amount", 0))
            tax_amount = float(line_item_data.get("_tax_amount", 0))
        except (TypeError, ValueError):
            line_amount = 0
            tax_amount = 0

        # Fix for the GST calculation bug
        if amount_type == "Inclusive":
            line_amount_excl_tax = line_amount - tax_amount
            line_amount_incl_tax = line_amount
        else:
            line_amount_excl_tax = line_amount
            line_amount_incl_tax = line_amount + tax_amount

        # Fetch the account
        account_code = line_item_data.get("_account_code")
        account = XeroAccount.objects.filter(account_code=account_code).first()

        # Sync the line item using dynamic field name
        kwargs = {document_field: document, "xero_line_id": xero_line_id}
        _line_item, _created = LineItemModel.objects.update_or_create(
            **kwargs,
            defaults={
                "quantity": quantity,
                "unit_price": unit_price,
                "description": description,
                "account": account,
                "tax_amount": tax_amount,
                "line_amount_excl_tax": line_amount_excl_tax,
                "line_amount_incl_tax": line_amount_incl_tax,
            },
        )
        # print(f"{'Created' if created else 'Updated'} Line Item: "
        #       f"Amount Excl. Tax: {line_item.line_amount_excl_tax}, "
        #       f"Tax Amount: {line_item.tax_amount}, "
        #       f"Total Incl. Tax: {line_item.line_amount_incl_tax}")


def set_company_fields(company: Company, new_from_xero: bool = False) -> None:
    """
    Set company fields from raw_json.
    If new_from_xero is True, it means the company was just created from Xero data.
    """
    raw_json = company.raw_json
    if not raw_json:
        logger.warning(f"Company {company.id} has no raw_json to process.")
        # BUG BUG BUG
        # Multiple breaches of 'fail early'.  REMOVE.
        # Do not allow 'or ' with fallbacks
        # DO not allow # type
        # Do not continue after logging a warning.  This is a data integrity issue.
        # Ensure essential fields are not None if raw_json is missing
        company.name = company.name or "Unnamed Company"
        company.xero_last_modified = company.xero_last_modified or timezone.now()
        company.save()
        return

    # Capture old values for change tracking (only for updates, not new clients)
    tracked_fields = [
        "name",
        "email",
        "address",
        "is_account_customer",
        "xero_archived",
    ]
    old_values = {}
    if not new_from_xero:
        old_values = {field: getattr(company, field, None) for field in tracked_fields}

    company.name = raw_json.get("_name", company.name or "Unnamed Company")
    # This is the general email for the contact/company
    company.email = raw_json.get("_email_address", company.email)

    # Update xero_contact_id from raw_json if available
    # This ensures the link to the Xero contact is maintained or established.
    xero_contact_id_from_json = raw_json.get("_contact_id")
    if xero_contact_id_from_json:
        company.xero_contact_id = xero_contact_id_from_json

    # Check for archived/merged status from raw_json
    contact_status = raw_json.get("_contact_status", "ACTIVE")
    if contact_status == "ARCHIVED":
        company.xero_archived = True
        company.allow_jobs = False
        # FIXME: asymmetric -- un-archiving in Xero does not reset either
        # flag. If a contact is archived then un-archived, `xero_archived`
        # and `allow_jobs` stay in the archived state until an admin toggles
        # `allow_jobs` back on via the company detail UI. The un-archive
        # path is rare enough that we accepted the asymmetry rather than
        # introduce a "manually set" protection flag. If un-archive becomes
        # common, revisit: (a) auto-reset both flags, which overwrites any
        # manual admin-set `allow_jobs=False`; or (b) track admin overrides
        # separately so they survive a sync.

    # Check for merge information
    merged_to_contact_id = raw_json.get("_merged_to_contact_id")
    if merged_to_contact_id:
        company.xero_merged_into_id = merged_to_contact_id

    # Attempt to get address from the 'STREET' address entry if available
    street_address = ""
    if isinstance(raw_json.get("_addresses"), list):
        for address_entry in raw_json.get("_addresses", []):
            # Bug.  Bare if must only be if <unhappy case>.  Anything else needs else
            # isinstance looks like it's trying to check a data contract
            if (
                isinstance(address_entry, dict)
                and address_entry.get("_address_type") == "STREET"
            ):
                # Concatenate address lines, city, region, postal code, country if they
                # exist
                parts = [
                    address_entry.get("_address_line1"),
                    address_entry.get("_address_line2"),
                    address_entry.get("_address_line3"),
                    address_entry.get("_address_line4"),
                    address_entry.get("_city"),
                    address_entry.get("_region"),
                    address_entry.get("_postal_code"),
                    address_entry.get("_country"),
                ]
                street_address = ", ".join(filter(None, parts))
                break  # Found street address
    company.address = (
        street_address or company.address
    )  # Use street_address if found, else keep existing or empty

    # Create SupplierPickupAddress from Xero STREET address for any company
    if isinstance(raw_json.get("_addresses"), list):
        for address_entry in raw_json.get("_addresses", []):
            if (
                isinstance(address_entry, dict)
                and address_entry.get("_address_type") == "STREET"
            ):
                # Extract individual address components
                line1 = address_entry.get("_address_line1") or ""
                line2 = address_entry.get("_address_line2") or ""
                line3 = address_entry.get("_address_line3") or ""
                line4 = address_entry.get("_address_line4") or ""
                city = address_entry.get("_city") or ""

                # Combine address lines for street field
                street_parts = [p for p in [line1, line2, line3, line4] if p]
                street = ", ".join(street_parts)

                # Only create if we have both street and city (required fields)
                if street and city:
                    SupplierPickupAddress.objects.get_or_create(
                        company=company,
                        name="Xero Address",
                        defaults={
                            "street": street,
                            "city": city,
                            "state": address_entry.get("_region") or None,
                            "postal_code": address_entry.get("_postal_code") or None,
                            "country": address_entry.get("_country") or "New Zealand",
                            "is_primary": True,
                        },
                    )
                break  # Only process first STREET address

    company.is_account_customer = raw_json.get(
        "_is_customer", company.is_account_customer
    )

    # Handle xero_last_modified
    updated_date_utc_str = raw_json.get("_updated_date_utc")
    if updated_date_utc_str:
        try:
            parsed_last_modified = parse_datetime(updated_date_utc_str)
            if parsed_last_modified is None:
                # parse_datetime returns None for malformed input instead of
                # raising; normalize both failure modes into the except arm.
                raise ValueError(f"unparseable datetime {updated_date_utc_str!r}")
            company.xero_last_modified = parsed_last_modified
        except ValueError:
            logger.error(
                f"Could not parse _updated_date_utc: {updated_date_utc_str} "
                f"for company {company.id}"
            )
            company.xero_last_modified = company.xero_last_modified or timezone.now()
    else:
        company.xero_last_modified = company.xero_last_modified or timezone.now()

    company.xero_last_synced = timezone.now()
    # Keep the company write and its phone sync atomic: a cross-company phone
    # conflict raised by sync_xero_phone_methods must roll back this company's
    # field update too, rather than leaving it committed without its numbers.
    with transaction.atomic():
        company.save()
        created_numbers = sync_xero_phone_methods(company)
    if created_numbers:
        # Numbers imported from Xero must rematch historical calls just like
        # UI-edited numbers do. Dispatch after the DB work is committed so the
        # task sees the new rows.
        transaction.on_commit(lambda: rematch_phone_calls_task.delay(created_numbers))

    if new_from_xero:
        logger.info(
            f"[XERO-WEBHOOK] Company {company.name} (ID: {company.id}) "
            f"created from Xero data."
        )
    else:
        # Compare old and new values to report changes
        changes = []
        for field in tracked_fields:
            old_val = old_values.get(field)
            new_val = getattr(company, field, None)
            if old_val != new_val:
                changes.append(f"{field}: {old_val!r} → {new_val!r}")

        if changes:
            logger.info(
                f"Company {company.name} (ID: {company.id}) updated from Xero data. "
                f"Changes: {', '.join(changes)}"
            )
        else:
            logger.info(
                f"Company {company.name} (ID: {company.id}) synced from Xero (no changes)."
            )


def reprocess_invoices():
    """Reprocess all existing invoices to set fields based on raw JSON."""
    for invoice in Invoice.objects.all():
        try:
            set_invoice_or_bill_fields(invoice, "INVOICE")
            logger.info(f"Reprocessed invoice: {invoice.number}")
        except Exception as e:
            logger.error(f"Error reprocessing invoice {invoice.number}: {str(e)}")


def reprocess_bills():
    """Reprocess all existing bills to set fields based on raw JSON."""
    for bill in Bill.objects.all():
        try:
            set_invoice_or_bill_fields(bill, "BILL")
            logger.info(f"Reprocessed bill: {bill.number}")
        except Exception as e:
            logger.error(f"Error reprocessing bill {bill.number}: {str(e)}")


def reprocess_credit_notes():
    """Reprocess all existing credit notes to set fields based on raw JSON."""
    for credit_note in CreditNote.objects.all():
        try:
            set_invoice_or_bill_fields(credit_note, "CREDIT NOTE")
            logger.info(f"Reprocessed credit note: {credit_note.number}")
        except Exception as e:
            logger.error(
                f"Error reprocessing credit note {credit_note.number}: {str(e)}"
            )


def reprocess_companies():
    """Reprocess all existing clients to set fields based on raw JSON."""
    for company in Company.objects.all():
        try:
            set_company_fields(company)
            logger.info(f"Reprocessed company: {company.name}")
        except Exception as e:
            logger.error(f"Error reprocessing company {company.name}: {str(e)}")


def reprocess_all():
    """Reprocesses all data to set fields based on raw JSON."""
    # NOte, we don't have a reprocess accounts because it just feels too weird.
    # If you break accounts, you probably want to handle it manually
    reprocess_companies()
    reprocess_invoices()
    reprocess_bills()
    reprocess_credit_notes()
