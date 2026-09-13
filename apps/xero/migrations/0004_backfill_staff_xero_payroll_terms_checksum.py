"""Staff whose payroll terms were synced before the checksum existed get theirs.

Those rows read the old shape instead — a branch on ``xero_fields_checksum`` that
ADR 0059 says to migrate away rather than keep. The value is derived here by the
same two functions the reader calls, imported rather than copied: a copy would be
a second implementation of the contract (ADR 0039) that drifts the first time the
projection changes, and this runs once. It lives in the Xero context, beside the functions it calls,
because a domain app may not import an integration (the layer contract), and
the checksum is Xero's contract rather than accounts'.

The column stays nullable: NULL means payroll terms have never been synced, the
same meaning ``xero_fields_checksum`` carries, and a staff row is created before
any sync. Only rows that hold terms are backfilled; the rest are genuinely unsynced
and the reader treats a missing checksum as "re-derive from Xero", which is the
safe direction.
"""

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

from apps.xero.payroll_employees import _current_employee_projection, _xero_fields_checksum


def record_the_terms_checksum(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    staff_model = apps.get_model("accounts", "Staff")
    for staff in staff_model.objects.filter(
        xero_payroll_terms_checksum__isnull=True, payroll_terms__isnull=False
    ).distinct():
        terms = _current_employee_projection(staff)["payroll_terms"]
        staff.xero_payroll_terms_checksum = _xero_fields_checksum(terms)
        staff.save(update_fields=["xero_payroll_terms_checksum"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0014_staff_staff_xero_payroll_terms_checksum_not_blank"),
        ("xero", "0003_xerodetailrefresh"),
    ]

    operations = [
        migrations.RunPython(record_the_terms_checksum, migrations.RunPython.noop),
    ]
