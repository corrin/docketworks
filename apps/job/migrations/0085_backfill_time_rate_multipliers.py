from decimal import Decimal

from django.db import migrations


def backfill_time_rate_multipliers(apps, schema_editor):
    CostLine = apps.get_model("job", "CostLine")

    lines = (
        CostLine.objects.filter(
            cost_set__kind="actual",
            kind="time",
            meta__wage_rate_multiplier__isnull=True,
            xero_pay_item__multiplier__isnull=False,
        )
        .select_related("xero_pay_item")
        .only("id", "meta", "unit_rev", "xero_pay_item__multiplier")
    )

    for line in lines.iterator():
        meta = line.meta if isinstance(line.meta, dict) else {}
        multiplier = Decimal(line.xero_pay_item.multiplier).quantize(Decimal("0.01"))
        meta["wage_rate_multiplier"] = float(multiplier)
        meta.setdefault("bill_rate_multiplier", float(multiplier))
        meta.setdefault("is_billable", line.unit_rev > Decimal("0.00"))
        CostLine.objects.filter(pk=line.pk).update(meta=meta)


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0084_reconcile_time_xero_pay_items"),
    ]

    operations = [
        migrations.RunPython(
            backfill_time_rate_multipliers,
            migrations.RunPython.noop,
        ),
    ]
