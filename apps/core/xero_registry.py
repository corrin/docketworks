"""Registry-based access to apps.xero models from below the layer boundary.

The import-linter contract places ``apps.xero`` ABOVE the domain apps, so a
domain service that reads a Xero mirror table (pay runs for the timesheet
payroll list, pay slips for the accounting reconciliation) cannot import it.
Each consumer declares its own narrow Protocol for the rows/queryset surface
it actually reads — those stay per-consumer deliberately (they differ) — and
resolves the manager through this one seam.
"""

from django.apps import apps as django_apps
from django.db import models


def xero_model_manager(model_name: str) -> "models.Manager[models.Model]":
    """Resolve a xero-app model's default manager through the app registry."""
    manager: models.Manager[models.Model] = django_apps.get_model(
        "xero", model_name
    )._default_manager
    return manager
