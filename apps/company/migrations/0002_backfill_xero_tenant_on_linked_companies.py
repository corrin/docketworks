"""Record the organisation on every company that carries a Xero contact id.

``xero_tenant_id`` arrived after most companies were already linked, and only a
sync that touches a company stamps it. The sync is incremental, so a contact
nobody has edited in Xero since is never revisited: production held 3,920
linked companies with no tenant against 321 with one (census, 2026-10-04).

An instance's companies come from one Xero organisation, so the unstamped ones
belong to the organisation the stamped ones name. That is where the value is
taken from. ``CompanyDefaults.xero_tenant_id`` is the answer only when no
company is stamped at all, and it is not consulted first for a reason: on a
restored copy that has been bound to its own demo organisation but not yet
re-seeded, the contact ids are still the source installation's, and stamping
them with the newly bound tenant would tell the restore seed the mirror is
already this organisation's. It would then skip its clear and send documents
against contacts the organisation has never held.

Nothing is deleted: these are real customers and suppliers, most of them with
invoices. Where the rows give no single answer the migration stops and says
what it found; the constraint in the next migration would refuse the same rows
with an error that names nothing.

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

    linked = company.objects.filter(xero_contact_id__isnull=False)
    unstamped = linked.filter(xero_tenant_id__isnull=True)
    count = unstamped.count()
    if count == 0:
        return

    stamped_tenants = sorted(
        linked.filter(xero_tenant_id__isnull=False)
        .values_list("xero_tenant_id", flat=True)
        .distinct()
    )
    if len(stamped_tenants) > 1:
        raise RuntimeError(
            f"{count} companies carry a Xero contact id and no organisation, and the "
            f"stamped companies name {len(stamped_tenants)} different organisations "
            f"({', '.join(stamped_tenants)}), so the rows do not say which one the "
            "unstamped contacts belong to. Nothing was changed."
        )
    if stamped_tenants:
        unstamped.update(xero_tenant_id=stamped_tenants[0])
        return

    defaults = company_defaults.objects.first()
    if defaults is None or not defaults.xero_tenant_id:
        raise RuntimeError(
            f"{count} companies carry a Xero contact id and no organisation, no company "
            "is stamped with one, and CompanyDefaults.xero_tenant_id is not set, so "
            "nothing says which organisation these contacts belong to. Nothing was "
            "changed. Do not bind an organisation just to get past this: if the contact "
            "ids came from another installation (a restored copy), binding this one's "
            "organisation would record them against the wrong Xero."
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
