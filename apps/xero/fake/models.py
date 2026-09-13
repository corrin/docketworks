"""The fake Xero's state: every object it has been seeded with or has issued.

One table rather than a per-kind model or an in-process store, because the
E2E stack is five processes (uvicorn, worker, beat, the cleanup command, the
PDF inspector) that all have to agree on what "Xero" holds, and because the
restore that ends every run has to put it back. ``id`` IS the Xero id: the
uniqueness Xero guarantees is the primary key here, not a convention the
fake remembers to keep.
"""

from typing import ClassVar

from django.db import models


class FakeXeroObject(models.Model):
    """One Xero object as the fake will serve it, body already in wire shape."""

    class Kind(models.TextChoices):
        CONTACT = "contact", "Contact"
        INVOICE = "invoice", "Invoice"
        CREDIT_NOTE = "credit_note", "Credit note"
        QUOTE = "quote", "Quote"
        PURCHASE_ORDER = "purchase_order", "Purchase order"
        ITEM = "item", "Item"
        ACCOUNT = "account", "Account"
        TAX_RATE = "tax_rate", "Tax rate"
        ORGANISATION = "organisation", "Organisation"
        BRANDING_THEME = "branding_theme", "Branding theme"
        EMPLOYEE = "employee", "Employee"
        SALARY_AND_WAGE = "salary_and_wage", "Salary and wage"
        WORKING_PATTERN = "working_pattern", "Working pattern"
        PAY_RUN = "pay_run", "Pay run"
        PAY_SLIP = "pay_slip", "Pay slip"
        LEAVE_TYPE = "leave_type", "Leave type"
        EARNINGS_RATE = "earnings_rate", "Earnings rate"
        HISTORY_RECORD = "history_record", "History record"
        ATTACHMENT = "attachment", "Attachment"

    # No default: the fake mints every id it issues and the seed copies every
    # id the mirror holds, so a row reaching the database without one is a
    # bug to crash on, not a gap to fill.
    id = models.UUIDField(primary_key=True, editable=False)
    tenant_id = models.CharField(max_length=255)
    kind = models.CharField(max_length=32, choices=Kind.choices)
    # NULL means Xero numbers nothing of this kind (a contact, a pay slip);
    # a blank string never occurs (ADR 0040) and the CHECK below says so.
    number = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001 -- see comment
    name = models.CharField(max_length=500, null=True, blank=True)  # noqa: DJ001 -- as number
    status = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001 -- as number
    # A pay slip belongs to a pay run, a salary line to an employee, a history
    # note to a document: the one owner a child route is queried by.
    parent_id = models.UUIDField(null=True, blank=True)
    updated_date_utc = models.DateTimeField()
    body = models.JSONField()

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["tenant_id", "kind", "number"],
                condition=models.Q(number__isnull=False),
                name="fakexeroobject_number_unique_per_kind",
            ),
            models.CheckConstraint(
                condition=~models.Q(number=""), name="fakexeroobject_number_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(name=""), name="fakexeroobject_name_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(status=""), name="fakexeroobject_status_not_blank"
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["tenant_id", "kind", "updated_date_utc"],
                name="fakexero_tenant_kind_updated",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.number or self.name or self.id}"
