"""Status enums for accounting documents."""

from django.db import models


class QuoteStatus(models.TextChoices):
    """Status options for quotes."""

    DRAFT = "DRAFT", "Draft"
    SENT = "SENT", "Sent"
    DECLINED = "DECLINED", "Declined"
    ACCEPTED = "ACCEPTED", "Accepted"
    INVOICED = "INVOICED", "Invoiced"
    DELETED = "DELETED", "Deleted"


class InvoiceStatus(models.TextChoices):
    """Status options for invoices."""

    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    AUTHORISED = "AUTHORISED", "Authorised"
    DELETED = "DELETED", "Deleted"
    VOIDED = "VOIDED", "Voided"
    PAID = "PAID", "Paid"
