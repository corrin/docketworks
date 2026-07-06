"""Seed the labour subtype catalogue.

Creates the final catalogue directly (the net effect of the pre-squash
job/0093 + 0098 + 0099 chain). Rates: Onsite has its own default; every
other subtype starts at the historical fresh-install default and is tuned
per instance via the labour-rates admin UI. Per-job JobLabourRate rows are
seeded at job creation by the service layer, so no job backfill is needed
on a fresh database. Idempotent; reverse deletes the catalogue.
"""

from decimal import Decimal

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

BASE_RATE = Decimal("105.00")
ONSITE_RATE = Decimal("165.00")

SUBTYPES = [
    # (name, display_order, is_workshop, counts_for_scheduling, rate)
    ("Workshop", 10, True, True, BASE_RATE),
    ("Admin", 20, False, False, BASE_RATE),
    ("Quoting", 30, False, False, BASE_RATE),
    ("Onsite quoting", 35, False, False, BASE_RATE),
    ("Onsite", 40, False, True, ONSITE_RATE),
    ("Supervision", 50, False, True, BASE_RATE),
    ("Delivery", 60, False, False, BASE_RATE),
]


def seed_subtypes(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    LabourSubtype = apps.get_model("job", "LabourSubtype")
    for name, display_order, is_workshop, counts_for_scheduling, rate in SUBTYPES:
        LabourSubtype.objects.update_or_create(
            name=name,
            defaults={
                "display_order": display_order,
                "is_active": True,
                "is_workshop": is_workshop,
                "counts_for_scheduling": counts_for_scheduling,
                "default_charge_out_rate": rate,
            },
        )


def unseed_subtypes(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    LabourSubtype = apps.get_model("job", "LabourSubtype")
    LabourSubtype.objects.filter(name__in=[s[0] for s in SUBTYPES]).delete()


class Migration(migrations.Migration):
    replaces = [
        ("job", "0093_seed_labour_subtypes"),
        ("job", "0098_clean_labour_subtype_catalogue"),
        ("job", "0099_add_onsite_quoting_and_reactivate_delivery"),
    ]

    dependencies = [
        ("job", "0001_baseline"),
    ]

    operations = [
        migrations.RunPython(seed_subtypes, unseed_subtypes),
    ]
