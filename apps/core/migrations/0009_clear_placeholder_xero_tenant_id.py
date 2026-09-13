"""Clear the all-zero placeholder Xero tenant id.

Opus: the seeded bootstrap fixture shipped ``00000000-0000-0000-0000-000000000000``
as ``xero_tenant_id``, so every instance created from it and not yet finalised, and
every dev or demo database restored from one, holds an organisation id Xero never
issued. ``get_tenant_id()`` treats it as configured and sends it in the
``xero-tenant-id`` header, which draws a vendor rejection in place of the
configuration error an unset value raises. NULL is the state the application
already understands, so the old shape is migrated to it rather than tolerated on
the read side (ADR 0059).

The filter is exact and cannot reach a bound instance: ``manage.py xero --setup``
overwrites the column with the id it discovers from the connection, and Xero does
not issue the zero UUID as a tenant. The reverse is a no-op — a rollback must never
re-fabricate an organisation id.

The literal is hardcoded rather than imported from ``apps.xero.constants``: ``core``
sits below ``xero`` in the layer contract, and a migration is the one place that is
supposed to know a shape the application no longer produces.
"""

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

PLACEHOLDER_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def clear_placeholder_tenant_id(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    company_defaults = apps.get_model("core", "CompanyDefaults")
    company_defaults.objects.filter(xero_tenant_id=PLACEHOLDER_TENANT_ID).update(
        xero_tenant_id=None
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_release_integration_settings"),
    ]

    operations = [
        migrations.RunPython(clear_placeholder_tenant_id, migrations.RunPython.noop),
    ]
