from decimal import Decimal, InvalidOperation

from django.db import migrations


def _normalize_multiplier(value):
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None


def reconcile_time_xero_pay_items(apps, schema_editor):
    CostLine = apps.get_model("job", "CostLine")
    XeroPayItem = apps.get_model("workflow", "XeroPayItem")

    pay_items_by_multiplier = {
        item.multiplier.quantize(Decimal("0.01")): item.id
        for item in XeroPayItem.objects.filter(
            uses_leave_api=False,
            multiplier__isnull=False,
        )
    }

    lines = CostLine.objects.filter(
        cost_set__kind="actual",
        kind="time",
    ).only("id", "meta", "xero_pay_item")

    for line in lines.iterator():
        meta = line.meta if isinstance(line.meta, dict) else {}
        multiplier = _normalize_multiplier(meta.get("wage_rate_multiplier"))
        if multiplier is None:
            continue

        pay_item_id = pay_items_by_multiplier.get(multiplier)
        if pay_item_id is None:
            raise RuntimeError(
                "Cannot reconcile CostLine.xero_pay_item: no non-leave "
                f"XeroPayItem exists for wage_rate_multiplier={multiplier}."
            )

        if line.xero_pay_item_id != pay_item_id:
            CostLine.objects.filter(pk=line.pk).update(xero_pay_item_id=pay_item_id)


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0082_drop_jobevent_description"),
    ]

    operations = [
        migrations.RunPython(
            reconcile_time_xero_pay_items,
            migrations.RunPython.noop,
        ),
    ]
