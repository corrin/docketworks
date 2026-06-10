from decimal import Decimal

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

# Initial subtypes per the KAN-230 design. Workshop/Office/Quoting/Delivery
# default to the company charge-out rate (everything billed at one rate
# today); Installation is the onsite-labour subtype with its own rate.
ONSITE_RATE = Decimal("165.00")

SUBTYPES = [
    # (name, display_order, is_workshop, rate_override)
    ("Workshop", 10, True, None),
    ("Office/Admin", 20, False, None),
    ("Quoting", 30, False, None),
    ("Delivery", 40, False, None),
    ("Installation", 50, False, ONSITE_RATE),
]


def seed_subtypes(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    LabourSubtype = apps.get_model("job", "LabourSubtype")
    CompanyDefaults = apps.get_model("workflow", "CompanyDefaults")

    company_defaults = CompanyDefaults.objects.first()
    if company_defaults is not None:
        base_rate = company_defaults.charge_out_rate
    else:
        # Fresh install: CompanyDefaults is created after migrations run.
        # Use the CompanyDefaults.charge_out_rate field default.
        base_rate = Decimal("105.00")

    for name, display_order, is_workshop, rate_override in SUBTYPES:
        LabourSubtype.objects.create(
            name=name,
            display_order=display_order,
            is_active=True,
            is_workshop=is_workshop,
            default_charge_out_rate=(
                rate_override if rate_override is not None else base_rate
            ),
        )


def unseed_subtypes(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    LabourSubtype = apps.get_model("job", "LabourSubtype")
    LabourSubtype.objects.filter(name__in=[s[0] for s in SUBTYPES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0092_laboursubtype_joblabourrate"),
        ("workflow", "0235_searchtelemetryevent"),
    ]

    operations = [
        migrations.RunPython(seed_subtypes, unseed_subtypes),
    ]
