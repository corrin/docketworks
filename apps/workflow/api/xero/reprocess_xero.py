# workflow/xero/reprocess_xero.py
import logging
import uuid
from decimal import Decimal

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
from apps.client.models import Client, ClientContact, SupplierPickupAddress
from apps.workflow.models import XeroAccount, XeroJournal, XeroJournalLineItem
from apps.workflow.services.error_persistence import persist_and_raise

logger = logging.getLogger("xero")


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

    # Set or create the client/supplier
    contact_data = raw_data.get("_contact", {})
    contact_id = contact_data.get("_contact_id")
    client = Client.objects.filter(xero_contact_id=contact_id).first()
    if not client:
        raise ValueError(
            f"Client not found for {document_type.lower()} {document.number}"
        )
    document.client = client

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
        line_item, created = LineItemModel.objects.update_or_create(
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


def set_client_fields(client, new_from_xero=False):
    """
    Set client fields from raw_json.
    If new_from_xero is True, it means the client was just created from Xero data.
    """
    raw_json = client.raw_json
    if not raw_json:
        logger.warning(f"Client {client.id} has no raw_json to process.")
        # Ensure essential fields are not None if raw_json is missing
        client.name = client.name or "Unnamed Client"
        client.xero_last_modified = client.xero_last_modified or timezone.now()
        client.save()
        return

    # Capture old values for change tracking (only for updates, not new clients)
    tracked_fields = [
        "name",
        "email",
        "phone",
        "address",
        "is_account_customer",
        "primary_contact_name",
        "primary_contact_email",
        "xero_archived",
    ]
    old_values = {}
    if not new_from_xero:
        old_values = {field: getattr(client, field, None) for field in tracked_fields}

    client.name = raw_json.get("_name", client.name or "Unnamed Client")
    # This is the general email for the contact/company
    client.email = raw_json.get("_email_address", client.email)

    # Update xero_contact_id from raw_json if available
    # This ensures the link to the Xero contact is maintained or established.
    xero_contact_id_from_json = raw_json.get("_contact_id")
    if xero_contact_id_from_json:
        client.xero_contact_id = xero_contact_id_from_json

    # Check for archived/merged status from raw_json
    contact_status = raw_json.get("_contact_status", "ACTIVE")
    if contact_status == "ARCHIVED":
        client.xero_archived = True
        client.allow_jobs = False

    # Check for merge information
    merged_to_contact_id = raw_json.get("_merged_to_contact_id")
    if merged_to_contact_id:
        client.xero_merged_into_id = merged_to_contact_id

    # Attempt to get phone number from the 'DEFAULT' phone entry if available
    default_phone = ""
    if isinstance(raw_json.get("_phones"), list):
        for phone_entry in raw_json.get("_phones", []):
            if (
                isinstance(phone_entry, dict)
                and phone_entry.get("_phone_type") == "DEFAULT"
            ):
                number = phone_entry.get("_phone_number", "")
                area_code = phone_entry.get("_phone_area_code", "")
                country_code = phone_entry.get("_phone_country_code", "")
                default_phone = f"{country_code} {area_code} {number}".strip()
                break  # Found default, no need to check further
    client.phone = (
        default_phone or client.phone
    )  # Use default_phone if found, else keep existing or empty

    # Attempt to get address from the 'STREET' address entry if available
    street_address = ""
    if isinstance(raw_json.get("_addresses"), list):
        for address_entry in raw_json.get("_addresses", []):
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
    client.address = (
        street_address or client.address
    )  # Use street_address if found, else keep existing or empty

    # Create SupplierPickupAddress from Xero STREET address for any client
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
                        client=client,
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

    client.is_account_customer = raw_json.get(
        "_is_customer", client.is_account_customer
    )

    contact_first_name = raw_json.get("_first_name", None)
    contact_last_name = raw_json.get("_last_name", None)

    match (contact_first_name, contact_last_name):
        case (str() as first, str() as last) if first and last:
            client.primary_contact_name = f"{first} {last}"
        case (str() as first, None) if first:
            client.primary_contact_name = first
        case (None, str() as last) if last:
            client.primary_contact_name = last
        case _:
            client.primary_contact_name = "Unnamed Contact"

    contact_email = raw_json.get("_email_address", None)
    if contact_email:
        client.primary_contact_email = contact_email

    additional_persons = raw_json.get("_contact_persons", [])
    if len(additional_persons) > 0:
        client.additional_contact_persons = [
            {
                "name": (person.get("_first_name") or "")
                + (" " + person.get("_last_name") if person.get("_last_name") else ""),
                "email": person.get("_email_address"),
            }
            for person in additional_persons
            if isinstance(person, dict)
        ]
        for person in additional_persons:
            if isinstance(person, dict):
                first_name = person.get("_first_name") or ""
                last_name = person.get("_last_name") or ""
                name = (first_name + (" " + last_name if last_name else "")).strip()

                # Skip contacts with empty names - they're pointless
                if not name:
                    logger.debug(
                        f"Skipping contact with empty name for client {client.name}"
                    )
                    continue

                # Use None instead of empty string for nullable fields
                email = person.get("_email_address") or None

                try:
                    contact, created = ClientContact.objects.get_or_create(
                        client=client,
                        name=name,
                        defaults={"email": email},
                    )
                    # Update email if contact exists and email changed
                    if not created and contact.email != email:
                        contact.email = email
                        contact.save()
                except ClientContact.MultipleObjectsReturned as exc:
                    # Should NEVER happen after migrations + constraint.
                    # If we hit this, data integrity is broken - fail fast.
                    persist_and_raise(
                        exc,
                        additional_context={
                            "operation": "set_client_fields_duplicate_contact",
                            "client_id": str(client.id),
                            "contact_name": name,
                        },
                    )

    phones = raw_json.get("_phones", [])
    if phones:
        client.all_phones = [
            {
                "type": phone.get("_phone_type"),
                "number": phone.get("_phone_number"),
                "_phone_area_code": phone.get("_phone_area_code"),
                "_phone_country_code": phone.get("_phone_country_code"),
            }
            for phone in phones
            if isinstance(phone, dict) and phone.get("_phone_number")
        ]

    # Handle xero_last_modified
    updated_date_utc_str = raw_json.get("_updated_date_utc")
    if updated_date_utc_str:
        try:
            client.xero_last_modified = parse_datetime(updated_date_utc_str)
        except ValueError:
            logger.error(
                f"Could not parse _updated_date_utc: {updated_date_utc_str} "
                f"for client {client.id}"
            )
            client.xero_last_modified = client.xero_last_modified or timezone.now()
    else:
        client.xero_last_modified = client.xero_last_modified or timezone.now()

    client.xero_last_synced = timezone.now()
    client.save()

    if new_from_xero:
        logger.info(
            f"[XERO-WEBHOOK] Client {client.name} (ID: {client.id}) "
            f"created from Xero data."
        )
    else:
        # Compare old and new values to report changes
        changes = []
        for field in tracked_fields:
            old_val = old_values.get(field)
            new_val = getattr(client, field, None)
            if old_val != new_val:
                changes.append(f"{field}: {old_val!r} → {new_val!r}")

        if changes:
            logger.info(
                f"Client {client.name} (ID: {client.id}) updated from Xero data. "
                f"Changes: {', '.join(changes)}"
            )
        else:
            logger.info(
                f"Client {client.name} (ID: {client.id}) synced from Xero (no changes)."
            )


def set_journal_fields(journal: XeroJournal):
    """
    Read the raw_json from a XeroJournal record and set all fields and line items.
    Similar to set_invoice_or_bill_fields, but for journals.
    """
    raw_data = journal.raw_json
    if not raw_data:
        raise ValueError("Journal raw_json is empty. Cannot process fields.")

    # Adjust keys to match the underscore-prefixed structure you provided
    xero_id = raw_data.get("_journal_id")
    created_date_utc = raw_data.get("_created_date_utc")
    journal_number = raw_data.get("_journal_number")
    journal_date = raw_data.get("_journal_date")
    reference = raw_data.get("_reference")
    source_id = raw_data.get("_source_id")
    source_type = raw_data.get("_source_type")

    # Use created_date_utc as xero_last_modified if no separate field
    # Keeping consistent with other models
    xero_last_modified = created_date_utc

    # Verify xero_id matches the journal's stored xero_id
    if xero_id and str(journal.xero_id) != str(xero_id):
        # This would be unusual. Raise an error to detect data mismatches early.
        raise ValueError(
            f"XeroJournal {journal.id} has xero_id={journal.xero_id}, "
            f"but raw_json has {xero_id}."
        )

    journal.journal_date = journal_date
    journal.created_date_utc = created_date_utc
    journal.journal_number = journal_number
    journal.reference = reference
    journal.source_id = source_id
    journal.source_type = source_type
    journal.xero_last_modified = xero_last_modified

    # Save changes to the journal before processing line items
    journal.save()

    # Handle JournalLines
    line_items_data = raw_data.get("_journal_lines", [])

    for line_item_data in line_items_data:
        line_id = line_item_data.get("_journal_line_id")

        # Convert amounts from strings to Decimal
        net_amount_str = line_item_data.get("_net_amount", "0")
        gross_amount_str = line_item_data.get("_gross_amount", "0")
        tax_amount_str = line_item_data.get("_tax_amount", "0")

        # Convert to Decimal
        net_amount = Decimal(net_amount_str)
        gross_amount = Decimal(gross_amount_str)
        tax_amount = Decimal(tax_amount_str)

        account_code = line_item_data.get("_account_code")
        description = line_item_data.get("_description")
        tax_type = line_item_data.get("_tax_type")
        tax_name = line_item_data.get("_tax_name")

        # Fetch the account if available
        account = XeroAccount.objects.filter(account_code=account_code).first()

        XeroJournalLineItem.objects.update_or_create(
            xero_line_id=line_id,
            journal=journal,
            defaults={
                "account": account,
                "description": description,
                "net_amount": net_amount,
                "gross_amount": gross_amount,
                "tax_amount": tax_amount,
                "tax_type": tax_type,
                "tax_name": tax_name,
                "raw_json": line_item_data,
            },
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


def reprocess_clients():
    """Reprocess all existing clients to set fields based on raw JSON."""
    for client in Client.objects.all():
        try:
            set_client_fields(client)
            logger.info(f"Reprocessed client: {client.name}")
        except Exception as e:
            logger.error(f"Error reprocessing client {client.name}: {str(e)}")


def reprocess_journals():
    """
    Iterate over all XeroJournal records and re-run the set_journal_fields().
    Useful if we've tweaked mapping logic and want to re-derive fields from stored
    raw_json.
    """
    from apps.workflow.models import XeroJournal

    for jrnl in XeroJournal.objects.all():
        try:
            set_journal_fields(jrnl)
            logger.info(f"Reprocessed journal: {jrnl.journal_number or jrnl.xero_id}")
        except Exception as e:
            logger.error(
                f"Error reprocessing journal "
                f"{jrnl.journal_number or jrnl.xero_id}: {str(e)}"
            )


def reprocess_all():
    """Reprocesses all data to set fields based on raw JSON."""
    # NOte, we don't have a reprocess accounts because it just feels too weird.
    # If you break accounts, you probably want to handle it manually
    reprocess_clients()
    reprocess_invoices()
    reprocess_bills()
    reprocess_credit_notes()
    reprocess_journals()
