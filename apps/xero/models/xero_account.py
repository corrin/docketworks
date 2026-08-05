"""Xero chart-of-accounts model."""

import uuid
from typing import ClassVar

from django.db import models
from django.utils import timezone


class XeroAccount(models.Model):
    """A Xero chart-of-accounts entry synced from the Xero API."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # Internal UUID
    xero_id = models.UUIDField(
        unique=True, null=False, blank=False
    )  # Xero's UUID for the account, required
    xero_tenant_id = models.CharField(  # noqa: DJ001
        max_length=255, null=True, blank=True
    )  # For reference only - we are not fully multi-tenant yet
    account_code = models.CharField(  # noqa: DJ001
        max_length=20, null=True, blank=True
    )  # Optional since some accounts don't have codes
    account_name = models.CharField(
        max_length=255, null=False, blank=False, unique=True
    )  # Non-null to help catch duplicates
    description = models.TextField(null=True, blank=True)  # noqa: DJ001
    account_type = models.CharField(  # noqa: DJ001
        max_length=50, null=True, blank=True
    )  # For account type enum values
    tax_type = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001
    enable_payments = models.BooleanField(default=False)  # Boolean for enable payments to account
    xero_last_modified = models.DateTimeField(null=False, blank=False)
    xero_last_synced = models.DateTimeField(null=True, blank=True, default=timezone.now)
    raw_json = models.JSONField()  # Store the raw API response for reference
    django_created_at = models.DateTimeField(auto_now_add=True)
    django_updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workflow_xeroaccount"  # v1 home was the workflow app
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~models.Q(account_code=""),
                name="workflow_xeroaccount_account_code_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(account_type=""), name="account_type_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(description=""),
                name="workflow_xeroaccount_description_not_blank",
            ),
            models.CheckConstraint(condition=~models.Q(tax_type=""), name="tax_type_not_blank"),
            models.CheckConstraint(
                condition=~models.Q(xero_tenant_id=""),
                name="workflow_xeroaccount_xero_tenant_id_not_blank",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.account_name} ({self.account_code})"
