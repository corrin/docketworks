"""Xero sync error model, ported from v1 ``apps/workflow/models/app_error.py``.

Only ``XeroError`` lives here; its multi-table-inheritance parent ``AppError``
was ported to ``apps.core`` (below this app in the layer contract), so the
concrete import is allowed. The child table keeps its v1 name via the
``db_table`` pin; inherited columns stay on ``workflow_apperror``.
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
