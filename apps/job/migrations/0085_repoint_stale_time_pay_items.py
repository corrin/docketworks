from decimal import Decimal, InvalidOperation

from django.db import migrations


def _normalized_multiplier(value):
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None


def repoint_stale_time_pay_items(apps, schema_editor):
    CostLine = apps.get_model("job", "CostLine")
    XeroPayItem = apps.get_model("workflow", "XeroPayItem")

    ordinary_time = XeroPayItem.objects.filter(
        name="Ordinary Time",
        uses_leave_api=False,
        xero_id__isnull=False,
    ).first()
    time_and_half = XeroPayItem.objects.filter(
        name="Time and one half",
        uses_leave_api=False,
        xero_id__isnull=False,
    ).first()
    double_time = XeroPayItem.objects.filter(
        name="Double Time",
        uses_leave_api=False,
        xero_id__isnull=False,
    ).first()
    pay_items_by_multiplier = {}
    if ordinary_time is not None:
        pay_items_by_multiplier[Decimal("1.00")] = ordinary_time.id
    if time_and_half is not None:
        pay_items_by_multiplier[Decimal("1.50")] = time_and_half.id
    if double_time is not None:
        pay_items_by_multiplier[Decimal("2.00")] = double_time.id

    if not pay_items_by_multiplier:
        return

    lines = CostLine.objects.filter(
        cost_set__kind="actual",
        kind="time",
    ).only("id", "meta", "xero_pay_item")

    for line in lines.iterator():
        meta = line.meta if isinstance(line.meta, dict) else {}
        multiplier = _normalized_multiplier(meta.get("wage_rate_multiplier"))
        if multiplier is None:
            continue

        pay_item_id = pay_items_by_multiplier.get(multiplier)
        if pay_item_id is None:
            continue

        if line.xero_pay_item_id != pay_item_id:
            CostLine.objects.filter(pk=line.pk).update(xero_pay_item_id=pay_item_id)


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0084_backfill_time_rate_multipliers"),
    ]

    operations = [
        migrations.RunPython(
            repoint_stale_time_pay_items,
            migrations.RunPython.noop,
        ),
    ]
