"""Approve an invoice in Xero, as office staff do there. Development and E2E only.

Docketworks raises invoices as drafts and never approves one: approving
happens in Xero's own screen. An E2E spec of what follows approval (the void
offer on delete) needs an approved invoice, so this command makes the one
write a person would, then refreshes the invoice into Docketworks the way
Xero's webhook does (``sync_single_invoice``). Against the fake or the dev
organisation alike; never a production target.

A Xero refusal raises: the spec's state is not what it set up, and the run
stops there rather than testing something else.
"""

from django.core.management.base import BaseCommand, CommandParser
from xero_python.accounting import AccountingApi

from apps.accounting.models import Invoice
from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.operator_guards import assert_not_production_target, assert_xero_writes_enabled
from apps.xero.single_sync import sync_single_invoice


class Command(BaseCommand):
    """Approve one draft invoice in Xero and bring the approval into Docketworks."""

    help = "Approve a draft invoice in Xero (development and E2E only)."

    def add_arguments(self, parser: CommandParser) -> None:
        """Take the invoice's Xero id, as the create response returns it."""
        parser.add_argument("xero_invoice_id")

    def handle(self, *_args: object, **options: object) -> None:
        """Send the approval, then sync the invoice back."""
        xero_id = options["xero_invoice_id"]
        if not isinstance(xero_id, str):
            raise TypeError("The xero_invoice_id argument must be a string")
        assert_not_production_target()
        assert_xero_writes_enabled("approve_xero_invoice")

        invoice = Invoice.objects.select_related("company").get(xero_id=xero_id)
        contact_id = invoice.company.xero_contact_id
        if contact_id is None:
            raise ValueError(f"Invoice {invoice.number} names a company not linked to Xero")
        tenant_id = get_tenant_id()
        # recordings/invoice_approve.json: id, status, contact and date.
        AccountingApi(get_api_client()).update_or_create_invoices(
            tenant_id,
            invoices={
                "Invoices": [
                    {
                        "InvoiceID": xero_id,
                        "Status": "AUTHORISED",
                        "Contact": {"ContactID": contact_id},
                        "Date": invoice.date.isoformat(),
                    }
                ]
            },
        )
        sync_single_invoice(tenant_id, xero_id)
        invoice.refresh_from_db()
        if invoice.status != "AUTHORISED":
            raise ValueError(
                f"Xero accepted the approval but {invoice.number} synced as {invoice.status}"
            )
        self.stdout.write(f"Approved {invoice.number}")
