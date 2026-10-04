"""Record the organisation on every company that carries a Xero contact id.

``xero_tenant_id`` arrived after most companies were already linked, and only a
sync that touches a company stamps it. The sync is incremental, so a contact
nobody has edited in Xero since is never revisited: production held 3,920
linked companies with no tenant against 321 with one (census, 2026-10-04).

An instance talks to one Xero organisation, the one ``CompanyDefaults`` names,
and every stamped row there carries exactly that id. So the missing value has
one right answer and this writes it. Nothing is deleted: these are real
customers and suppliers, most of them with invoices.

Where linked companies exist and no organisation is configured there is no
answer to write, and the constraint in the next migration would refuse the same
rows with an error that names nothing. This stops first and says what to do.

The reverse is a no-op: the stamp is true, and removing it would only restore
the gap.
"""

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


def stamp_tenant_on_linked_companies(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    company = apps.get_model("company", "Company")
    company_defaults = apps.get_model("core", "CompanyDefaults")

    unstamped = company.objects.filter(xero_contact_id__isnull=False, xero_tenant_id__isnull=True)
    count = unstamped.count()
    if count == 0:
        return

    defaults = company_defaults.objects.first()
    if defaults is None or not defaults.xero_tenant_id:
        raise RuntimeError(
            f"{count} companies carry a Xero contact id and no organisation, and "
            "CompanyDefaults.xero_tenant_id is not set, so there is nothing to record "
            "them against. Bind the organisation first (manage.py xero --setup), then "
            "run migrate again."
        )
    unstamped.update(xero_tenant_id=str(defaults.xero_tenant_id))


class Migration(migrations.Migration):
    dependencies = [
        ("company", "0001_initial"),
        ("core", "0010_kpi_help_text"),
    ]

    operations = [
        migrations.RunPython(stamp_tenant_on_linked_companies, migrations.RunPython.noop),
    ]
