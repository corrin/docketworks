"""Xero sync error model.

Its multi-table-inheritance parent ``AppError`` lives in ``apps.core``, below
this app in the layer contract, so the concrete import is legal. The child and
parent tables retain their existing names through explicit ``db_table`` pins.
"""

from django.db import models

from apps.core.models import AppError


class XeroError(AppError):
    """Specialised error raised during Xero synchronisation."""

    entity = models.CharField(max_length=100)
    reference_id = models.CharField(max_length=255)
    kind = models.CharField(max_length=50)

    class Meta:
        db_table = "workflow_xeroerror"  # v1 home was the workflow app
        verbose_name = "Xero Error"
        verbose_name_plural = "Xero Errors"
