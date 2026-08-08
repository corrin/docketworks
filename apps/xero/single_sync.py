"""Per-resource sync paths, dispatched by webhook events.

v1 kept these in ``seed.py`` beside the greenfield seeding they do not
belong with; the rest of that file (``seed_xero_from_database`` and friends)
is dev tooling and stays unported.

Webhooks never touch sync cursors — a webhook is a point update, and cursor
advancement belongs to the hourly loop that can prove it covered a range.
"""

import logging
import time
from typing import Any

from django.utils import timezone
from xero_python.accounting import AccountingApi

from apps.accounting.models import Bill, Invoice
from apps.company.models import Company
from apps.xero.auth import get_api_client
from apps.xero.constants import SLEEP_TIME
from apps.xero.models import XeroPayRun
from apps.xero.payroll_sync import get_pay_run
from apps.xero.raw_fields import set_company_fields, set_invoice_or_bill_fields
from apps.xero.transforms import process_xero_data, resolve_pending_merge, transform_pay_run

logger = logging.getLogger(__name__)


def sync_single_contact(tenant_id: str, contact_id: str) -> None:
    """Fetch and sync a single contact from Xero by ID."""
    if not contact_id:
        raise ValueError("No contact_id provided")

    accounting_api = AccountingApi(get_api_client())
    response = accounting_api.get_contacts(tenant_id, i_ds=[contact_id], include_archived=True)
    time.sleep(SLEEP_TIME)

    if not response or not response.contacts:
        raise ValueError(f"No contact found with ID {contact_id}")

    contact = response.contacts[0]
    raw_json = process_xero_data(contact)

    # xero_archived is NOT written here: set_company_fields below owns the
    # archive-state derivation, and pre-writing it destroys the was_archived
    # transition its allow_jobs restore keys off — the same ordering defect
    # fixed on the batch path (ledgered; v1 had it on both paths).
    company, created = Company.objects.update_or_create(
        xero_contact_id=contact.contact_id,
        defaults={
            "raw_json": raw_json,
            "xero_last_modified": timezone.now(),
            "xero_merged_into_id": getattr(contact, "merged_to_contact_id", None),
        },
    )

    set_company_fields(company, new_from_xero=created)

    # Merge resolution shares the batch path's implementation (ADR 0039).
    resolve_pending_merge(company, logger_prefix="[webhook] ")

    logger.info("Synced contact %s from webhook", contact_id)


def sync_single_invoice(tenant_id: str, invoice_id: str) -> None:
    """Fetch and sync a single invoice (or bill) from Xero by ID."""
    if not invoice_id:
        raise ValueError("No invoice_id provided")

    accounting_api = AccountingApi(get_api_client())
    response = accounting_api.get_invoice(tenant_id, invoice_id=invoice_id)
    time.sleep(SLEEP_TIME)

    if not response or not response.invoices:
        raise ValueError(f"No invoice found with ID {invoice_id}")

    xero_invoice = response.invoices[0]
    raw_json = process_xero_data(xero_invoice)

    # Route to the correct model based on type.
    if xero_invoice.type == "ACCPAY":
        bill, created = Bill.objects.update_or_create(
            xero_id=xero_invoice.invoice_id,
            defaults={
                "raw_json": raw_json,
                "xero_last_modified": xero_invoice._updated_date_utc,
                "xero_last_synced": timezone.now(),
            },
        )
        set_invoice_or_bill_fields(bill, "BILL", new_from_xero=created)
        logger.info("Synced bill %s from webhook", invoice_id)

    elif xero_invoice.type == "ACCREC":
        invoice, created = Invoice.objects.update_or_create(
            xero_id=xero_invoice.invoice_id,
            defaults={
                "raw_json": raw_json,
                "xero_last_modified": xero_invoice._updated_date_utc,
                "xero_last_synced": timezone.now(),
            },
        )
        set_invoice_or_bill_fields(invoice, "INVOICE", new_from_xero=created)
        logger.info("Synced invoice %s from webhook", invoice_id)
    else:
        raise ValueError(f"Unknown invoice type {xero_invoice.type} for {invoice_id}")


def sync_single_pay_run(pay_run_id: str) -> XeroPayRun:
    """Fetch and sync a single pay run from Xero by ID."""
    if not pay_run_id:
        raise ValueError("No pay_run_id provided")

    xero_pay_run: Any = get_pay_run(pay_run_id)
    if not xero_pay_run:
        raise ValueError(f"No pay run found with ID {pay_run_id}")

    pay_run, status = transform_pay_run(xero_pay_run, pay_run_id)
    logger.info("Synced pay run %s: %s", pay_run_id, status)
    return pay_run
