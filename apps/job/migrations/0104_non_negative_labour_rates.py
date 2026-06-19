from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


def assert_no_negative_rates(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    LabourSubtype = apps.get_model("job", "LabourSubtype")
    JobLabourRate = apps.get_model("job", "JobLabourRate")

    negative_subtypes: list[dict[str, Any]] = list(
        LabourSubtype.objects.filter(default_charge_out_rate__lt=Decimal("0"))
        .order_by("id")
        .values("id", "name", "default_charge_out_rate")[:10]
    )
    negative_job_rates: list[dict[str, Any]] = list(
        JobLabourRate.objects.filter(charge_out_rate__lt=Decimal("0"))
        .order_by("id")
        .values("id", "job_id", "labour_subtype_id", "charge_out_rate")[:10]
    )

    if negative_subtypes or negative_job_rates:
        raise RuntimeError(
            "Cannot add non-negative labour-rate constraints while negative "
            "rates exist. Fix the data before migrating. "
            f"LabourSubtype examples: {negative_subtypes}; "
            f"JobLabourRate examples: {negative_job_rates}"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0103_add_job_is_urgent"),
    ]

    operations = [
        migrations.RunPython(assert_no_negative_rates, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="laboursubtype",
            constraint=models.CheckConstraint(
                condition=models.Q(default_charge_out_rate__gte=0),
                name="laboursubtype_default_rate_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="joblabourrate",
            constraint=models.CheckConstraint(
                condition=models.Q(charge_out_rate__gte=0),
                name="joblabourrate_charge_out_rate_non_negative",
            ),
        ),
    ]
