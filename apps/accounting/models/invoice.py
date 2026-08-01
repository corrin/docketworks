"""Xero invoice-like documents (invoices, bills, credit notes) and their line items.

Ported verbatim from v1 ``apps/accounting/models/invoice.py``. The only change
is the line-item account FK target string: v1's ``workflow.XeroAccount`` now
lives in the xero integration app, so the lazy reference is ``xero.XeroAccount``
(the table itself is unchanged — xero pins ``workflow_xeroaccount``).
"""

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar

from django.db import models
from django.utils import timezone

from apps.accounting.enums import InvoiceStatus

if TYPE_CHECKING:
    from django.db.models.fields.related_descriptors import RelatedManager

    from apps.company.models import Company


class BaseXeroInvoiceDocument(models.Model):
    """Abstract base for Xero invoice-like documents (Invoices, Bills, Credit Notes).

    These are financial documents that have line items and tax calculations.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    xero_id = models.UUIDField(unique=True)
    xero_tenant_id = models.CharField(  # noqa: DJ001
        max_length=255, null=True, blank=True
    )  # For reference only - we are not fully multi-tenant yet
    number = models.CharField(max_length=255)
    company = models.ForeignKey("company.Company", on_delete=models.PROTECT)
    date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=50, choices=InvoiceStatus.choices, default=InvoiceStatus.DRAFT
    )
    total_excl_tax = models.DecimalField(max_digits=10, decimal_places=2)
    tax = models.DecimalField(max_digits=10, decimal_places=2)
    total_incl_tax = models.DecimalField(max_digits=10, decimal_places=2)
    amount_due = models.DecimalField(max_digits=10, decimal_places=2)
    xero_last_modified = models.DateTimeField()
    xero_last_synced = models.DateTimeField(null=True, blank=True, default=timezone.now)
    raw_json = models.JSONField()
    django_created_at = models.DateTimeField(auto_now_add=True)
    django_updated_at = models.DateTimeField(auto_now=True)

    if TYPE_CHECKING:
        # Reverse manager declared on each concrete subclass's line-item FK
        # (related_name="line_items"); declared here so total_amount type-checks.
        line_items: "RelatedManager[BaseLineItem]"

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"{self.number} - {self.company.name}"

    @property
    def total_amount(self) -> Decimal:
        """Calculate the total amount by summing up the related line items."""
        return sum(
            (item.line_amount_excl_tax or Decimal("0.00")) for item in self.line_items.all()
        ) or Decimal("0.00")


class BaseLineItem(models.Model):
    """Abstract base for all line items (Invoice, Bill, Credit Note items)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    xero_line_id = models.UUIDField(unique=True, default=uuid.uuid4)
    description = models.TextField()
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, default=Decimal("1.00")
    )
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    line_amount_excl_tax = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    line_amount_incl_tax = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    account = models.ForeignKey(
        "xero.XeroAccount", on_delete=models.SET_NULL, null=True, blank=True
    )
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"{self.description} - {self.line_amount_excl_tax}"

    @property
    def total_price(self) -> Decimal:
        """Compute the total price of the line item including tax."""
        return (self.unit_price or Decimal("0.00")) * (self.quantity or Decimal("1.00"))


# Concrete Document Classes


class Invoice(BaseXeroInvoiceDocument):
    """A Xero sales invoice, optionally linked to a job."""

    job = models.ForeignKey(
        "job.Job",
        on_delete=models.PROTECT,
        related_name="invoices",
        null=True,
        blank=True,
    )
    online_url = models.URLField(null=True, blank=True)  # noqa: DJ001
    billing_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Invoice"
        verbose_name_plural = "Invoices"
        ordering: ClassVar[list[str]] = ["-date", "number"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~models.Q(online_url=""),
                name="accounting_invoice_online_url_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(xero_tenant_id=""),
                name="accounting_invoice_xero_tenant_id_not_blank",
            ),
        ]

    @property
    def paid(self) -> bool:
        """Whether this invoice has been paid, as reported by Xero."""
        return self.status == "PAID"


class Bill(BaseXeroInvoiceDocument):
    """A Xero bill (accounts payable document)."""

    class Meta:
        verbose_name = "Bill"
        verbose_name_plural = "Bills"
        ordering: ClassVar[list[str]] = ["-date", "number"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~models.Q(xero_tenant_id=""),
                name="accounting_bill_xero_tenant_id_not_blank",
            ),
        ]

    @property
    def supplier(self) -> "Company":
        """Return the company as 'supplier' for bills."""
        return self.company

    @supplier.setter
    def supplier(self, value: "Company") -> None:
        self.company = value


class CreditNote(BaseXeroInvoiceDocument):
    """A Xero credit note.

    Note that Xero has a few extra fields we don't have mapped (allocations,
    fully_paid_on_date, maybe more). We can add them as needed.
    """

    class Meta:
        verbose_name = "Credit Note"
        verbose_name_plural = "Credit Notes"
        ordering: ClassVar[list[str]] = ["-date"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~models.Q(xero_tenant_id=""),
                name="accounting_creditnote_xero_tenant_id_not_blank",
            ),
        ]

    def __str__(self) -> str:
        return f"Credit Note {self.number} ({self.status})"


# Concrete Line Item Classes


class InvoiceLineItem(BaseLineItem):
    """A line item on an Invoice."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="line_items")

    class Meta:
        verbose_name = "Invoice Line Item"
        verbose_name_plural = "Invoice Line Items"


class BillLineItem(BaseLineItem):
    """A line item on a Bill."""

    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name="line_items")

    class Meta:
        verbose_name = "Bill Line Item"
        verbose_name_plural = "Bill Line Items"


class CreditNoteLineItem(BaseLineItem):
    """A line item on a Credit Note."""

    credit_note = models.ForeignKey(CreditNote, on_delete=models.CASCADE, related_name="line_items")

    class Meta:
        verbose_name = "Credit Note Line Item"
        verbose_name_plural = "Credit Note Line Items"
