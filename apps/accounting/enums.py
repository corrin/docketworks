"""Status enums for accounting documents."""

from django.db import models
from django.utils.translation import gettext_lazy


class QuoteStatus(models.TextChoices):
    """Status options for quotes."""

    DRAFT = "DRAFT", gettext_lazy("Draft")
    SENT = "SENT", gettext_lazy("Sent")
    DECLINED = "DECLINED", gettext_lazy("Declined")
    ACCEPTED = "ACCEPTED", gettext_lazy("Accepted")
    INVOICED = "INVOICED", gettext_lazy("Invoiced")
    DELETED = "DELETED", gettext_lazy("Deleted")


class InvoiceStatus(models.TextChoices):
    """Status options for invoices."""

    DRAFT = "DRAFT", gettext_lazy("Draft")
    SUBMITTED = "SUBMITTED", gettext_lazy("Submitted")
    AUTHORISED = "AUTHORISED", gettext_lazy("Authorised")
    DELETED = "DELETED", gettext_lazy("Deleted")
    VOIDED = "VOIDED", gettext_lazy("Voided")
    PAID = "PAID", gettext_lazy("Paid")
