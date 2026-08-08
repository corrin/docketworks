"""Derive model fields from a record's stored Xero ``raw_json``.

The field-setting half of v1's ``reprocess_xero.py`` — consumed by the sync
transforms and the webhook single-resource paths. The other half (the bulk
``reprocess_*`` repair commands) is a recorded slice-2 deferral: after a
transform bug-fix, recovery is re-running the deep sync, which the per-entity
cursors make cheap.
"""

import logging
import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.accounting.models import (
    BillLineItem,
    CreditNoteLineItem,
    InvoiceLineItem,
)
from apps.company.models import Company, ContactMethod, SupplierPickupAddress
from apps.core.errors import AppErrorContext, persist_app_error
from apps.xero.models import XeroAccount

if TYPE_CHECKING:
    from apps.accounting.models.invoice import BaseXeroInvoiceDocument

logger = logging.getLogger(__name__)


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
    # A merged company's numbers live on the company it was merged into. Its
    # archived Xero contact keeps the phones (and is still fetched with
    # include_archived=True), so syncing it would collide with the winner's
    # rows under the one-number-one-company rule.
    if company.merged_into_id:
        return []
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
        phone_type = phone_entry.get("_phone_type") or ""  # "" only compared, never stored
        try:
            _, created = ContactMethod.objects.get_or_create(
                company=company,
                method_type=ContactMethod.MethodType.PHONE,
                normalized_value=normalized,
                defaults={
                    "value": value,
                    # or None: label carries a not-blank CHECK; "" would
                    # surface as an IntegrityError the except below misses.
                    "label": phone_type or None,
                    "is_primary": phone_type == "DEFAULT",
                    "source": ContactMethod.Source.IMPORTED,
                },
            )
        except ValidationError as exc:
            # Enrich and raise; persistence happens in set_company_fields
            # AFTER its transaction rolls back — a row written here, inside
            # the caller's atomic block, would be rolled back with it.
            raise ValidationError(
                f"Xero phone sync for company '{company.name}' ({company.id}) "
                f"rejected number '{value}' ({normalized}): "
                f"{'; '.join(exc.messages)}"
            ) from exc
        if created:
            created_numbers.append(normalized)
    return created_numbers


def set_invoice_or_bill_fields(  # noqa: C901, PLR0912, PLR0915 -- ported v1 shape; the branch count IS the document-type matrix
    document: "BaseXeroInvoiceDocument", document_type: str, new_from_xero: bool = False
) -> None:
    """Set an Invoice/Bill/CreditNote's fields (and line items) from raw_json.

    Args:
        document: The Invoice, Bill or CreditNote instance.
        document_type: "INVOICE", "BILL" or "CREDIT_NOTE".
        new_from_xero: True when the row was just created from Xero data
            (webhook path) — only affects logging.
    """
    if not document.raw_json:
        raise ValueError(
            f"{document_type.title()} raw_json is empty. We better not try to process it"
        )

    if new_from_xero:
        logger.info(
            "[XERO-WEBHOOK] Setting fields for new %s from Xero data: %s (Xero ID: %s)",
            document_type.lower(),
            document.number,
            document.xero_id,
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
    else:
        raise ValueError(
            f"Document {document.xero_id} raw_json carries unknown _type "
            f"{document.raw_json.get('_type')!r}"
        )

    if document_type != json_document_type:
        raise ValueError(
            f"Document type mismatch. Got {document_type} "
            f"but document appears to be a {json_document_type}"
        )

    raw_data = document.raw_json

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

    contact_data = raw_data.get("_contact", {})
    contact_id = contact_data.get("_contact_id")
    company = Company.objects.filter(xero_contact_id=contact_id).first()
    if not company:
        raise ValueError(f"Company not found for {document_type.lower()} {document.number}")
    document.company = company

    document.save()

    line_items_data = raw_data.get("_line_items", [])
    amount_type = raw_data.get("_line_amount_types", {}).get("_value_")

    if is_invoice:
        line_item_model: type[InvoiceLineItem | BillLineItem | CreditNoteLineItem] = InvoiceLineItem
        document_field = "invoice"
    elif is_bill:
        line_item_model = BillLineItem
        document_field = "bill"
    else:
        line_item_model = CreditNoteLineItem
        document_field = "credit_note"

    for line_item_data in line_items_data:
        line_item_id = line_item_data.get("_line_item_id")
        xero_line_id = uuid.UUID(line_item_id)
        # Defaults exist because Xero permits description-only lines (no
        # quantity or amount); rejecting them would brick documents Xero
        # itself accepted. Real money lines always carry both.
        description = line_item_data.get("_description") or "No description provided"
        quantity = line_item_data.get("_quantity", 1)
        unit_price = line_item_data.get("_unit_amount", 1)

        try:
            line_amount = float(line_item_data.get("_line_amount", 0))
            tax_amount = float(line_item_data.get("_tax_amount", 0))
        # deliberate-swallow: description-only lines carry no amounts (see
        # above) — zero is their true value, and one malformed money line
        # must not fail the whole document sync
        except (TypeError, ValueError):
            line_amount = 0
            tax_amount = 0

        # Xero reports _line_amount in the document's amount type; normalise
        # both directions so the stored pair is always (excl, incl).
        if amount_type == "Inclusive":
            line_amount_excl_tax = line_amount - tax_amount
            line_amount_incl_tax = line_amount
        else:
            line_amount_excl_tax = line_amount
            line_amount_incl_tax = line_amount + tax_amount

        account_code = line_item_data.get("_account_code")
        account = XeroAccount.objects.filter(account_code=account_code).first()

        kwargs: dict[str, Any] = {document_field: document, "xero_line_id": xero_line_id}
        line_item_model.objects.update_or_create(
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


def set_company_fields(  # noqa: C901, PLR0912, PLR0915 -- ported v1 shape; each branch is one Xero payload quirk
    company: Company, new_from_xero: bool = False
) -> None:
    """Set company fields from raw_json (name, email, address, archive state, phones)."""
    raw_json = company.raw_json
    if not raw_json:
        # v1 carried a self-confessed "BUG BUG BUG" fallback block here that
        # invented "Unnamed Company". A company without raw_json in this path
        # is a sync defect — fail it (ADR 0015), don't invent data.
        raise ValueError(f"Company {company.id} has no raw_json to process")

    tracked_fields = [
        "name",
        "email",
        "address",
        "is_account_customer",
        "xero_archived",
    ]
    old_values: dict[str, object] = {}
    if not new_from_xero:
        old_values = {field: getattr(company, field, None) for field in tracked_fields}

    # No invented names: a payload without _name keeps the existing name; a
    # company with neither is malformed remote data and fails its sync
    # (ADR 0015 — the ledger records the removal of v1's "Unnamed Company").
    payload_name = raw_json.get("_name")
    if not payload_name and not company.name:
        raise ValueError(f"Company {company.id} has no name in raw_json and none stored")
    company.name = payload_name or company.name
    # Xero sends "" for contacts with no email; NULL is our only unset (ADR 0040).
    company.email = raw_json.get("_email_address", company.email) or None

    # Keep the Xero-contact link established/maintained from the payload.
    xero_contact_id_from_json = raw_json.get("_contact_id")
    if xero_contact_id_from_json:
        company.xero_contact_id = xero_contact_id_from_json

    # xero_archived mirrors Xero in both directions. allow_jobs follows only
    # on the transitions — archiving disables it, un-archiving restores it —
    # never on a steady-state sync, so a manual block on an active company
    # survives routine syncs (ADR 0034). A merged tombstone stays blocked
    # regardless: its jobs belong to the winner.
    # No fallback for a missing status: guessing ACTIVE would un-archive the
    # company and re-open it for jobs. Malformed data fails this company's
    # sync (ADR 0015 — consumers stay strict). GDPRREQUEST is deliberately
    # not accepted: it should never occur on an NZ org, and treating it as
    # active would re-enable jobs for an erased contact — if it ever appears,
    # fail loudly and decide its handling then.
    contact_status = raw_json.get("_contact_status")
    if contact_status not in ("ACTIVE", "ARCHIVED"):
        raise ValueError(
            f"Company {company.id} raw_json has missing or unhandled "
            f"_contact_status {contact_status!r}"
        )
    was_archived = bool(company.xero_archived)
    company.xero_archived = contact_status == "ARCHIVED"
    if company.xero_archived:
        company.allow_jobs = False
    elif was_archived and not company.merged_into_id:
        company.allow_jobs = True
    else:
        pass  # no archive transition; leave allow_jobs as the admin set it

    merged_to_contact_id = raw_json.get("_merged_to_contact_id")
    if merged_to_contact_id:
        company.xero_merged_into_id = merged_to_contact_id

    # Address from the STREET entry, if present.
    street_address = ""
    addresses = raw_json.get("_addresses")
    if isinstance(addresses, list):
        for address_entry in addresses:
            if not isinstance(address_entry, dict):
                continue
            if address_entry.get("_address_type") != "STREET":
                continue
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
            break
    # Use street_address if found, else keep existing; "" is never stored.
    company.address = street_address or company.address or None

    # Mirror the STREET address as a pickup address for any company.
    if isinstance(addresses, list):
        for address_entry in addresses:
            if not isinstance(address_entry, dict):
                continue
            if address_entry.get("_address_type") != "STREET":
                continue
            line1 = address_entry.get("_address_line1") or ""
            line2 = address_entry.get("_address_line2") or ""
            line3 = address_entry.get("_address_line3") or ""
            line4 = address_entry.get("_address_line4") or ""
            city = address_entry.get("_city") or ""

            street_parts = [p for p in [line1, line2, line3, line4] if p]
            street = ", ".join(street_parts)

            # Both street and city are required fields on the model.
            if street and city:
                SupplierPickupAddress.objects.get_or_create(
                    company=company,
                    name="Xero Address",
                    defaults={
                        "street": street,
                        "city": city,
                        "state": address_entry.get("_region") or None,
                        "postal_code": address_entry.get("_postal_code") or None,
                        # Non-null column; the install is NZ-only, so the
                        # default is a fact, not a guess.
                        "country": address_entry.get("_country") or "New Zealand",
                        "is_primary": True,
                    },
                )
            break  # Only process first STREET address

    company.is_account_customer = raw_json.get("_is_customer", company.is_account_customer)

    updated_date_utc_str = raw_json.get("_updated_date_utc")
    if updated_date_utc_str:
        try:
            parsed_last_modified = parse_datetime(updated_date_utc_str)
            if parsed_last_modified is None:
                # parse_datetime returns None for malformed input instead of
                # raising; normalize both failure modes into the except arm.
                raise ValueError(f"unparseable datetime {updated_date_utc_str!r}")
            company.xero_last_modified = parsed_last_modified
        # deliberate-swallow: v1 contract — a malformed timestamp falls back
        # to the existing value; the record itself still syncs
        except ValueError:
            logger.error(
                "Could not parse _updated_date_utc: %s for company %s",
                updated_date_utc_str,
                company.id,
            )
            company.xero_last_modified = company.xero_last_modified or timezone.now()
    else:
        company.xero_last_modified = company.xero_last_modified or timezone.now()

    company.xero_last_synced = timezone.now()
    # Keep the company write and its phone sync atomic: a cross-company phone
    # conflict raised by sync_xero_phone_methods must roll back this company's
    # field update too, rather than leaving it committed without its numbers.
    try:
        with transaction.atomic():
            company.save()
            created_numbers = sync_xero_phone_methods(company)
    except ValidationError as exc:
        # Persist AFTER the rollback: a row written inside the atomic block
        # would be rolled back with the company update, leaving the operator
        # no trace of why this company's sync failed.
        persist_app_error(
            exc,
            AppErrorContext(
                additional_context={
                    "operation": "sync_xero_phone_methods_duplicate_owner",
                    "client_id": str(company.id),
                }
            ),
        )
        raise
    if created_numbers:
        # Numbers imported from Xero must rematch historical calls just like
        # UI-edited numbers do. Dispatch after the DB work is committed so the
        # task sees the new rows.
        # Call-time import: avoids loading celery task modules at import.
        from apps.crm.tasks import rematch_phone_calls_task  # noqa: PLC0415

        transaction.on_commit(lambda: rematch_phone_calls_task.delay(created_numbers))

    if new_from_xero:
        logger.info(
            "[XERO-WEBHOOK] Company %s (ID: %s) created from Xero data.",
            company.name,
            company.id,
        )
    else:
        changes = []
        for field in tracked_fields:
            old_val = old_values.get(field)
            new_val = getattr(company, field, None)
            if old_val != new_val:
                changes.append(f"{field}: {old_val!r} → {new_val!r}")

        if changes:
            logger.info(
                "Company %s (ID: %s) updated from Xero data. Changes: %s",
                company.name,
                company.id,
                ", ".join(changes),
            )
        else:
            logger.info(
                "Company %s (ID: %s) synced from Xero (no changes).", company.name, company.id
            )
