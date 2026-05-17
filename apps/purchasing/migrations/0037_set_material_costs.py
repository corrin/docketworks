"""Data migration to set unit_cost on material stock entries.

Sheet/material markup is ~20% across the catalog, so cost = revenue / 1.2.
Applied to the remaining materials that still have unit_cost=$0.00 against
non-zero unit_revenue.

Excluded from this pass:
- service/labour entries (FREIGHT, MIG WELDING, SITE VISIT KM, "Welding")
- a "Corrin testing stock" row that appears to be a test artefact
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db import migrations

MATERIAL_ITEM_CODES = [
    "SS-316",
    "STK-69ff6937",
    "STK-be20c8d0",
    "STK-d0bb0277",
    "SHT-2.0-AL5005-1200X2400",
    "SHT-1.6-AL5005H32-1200x2400",
    "STK-d384e165",
    "FB-50x4.5-6060T5-5M",
    "ELBOW-180DEG",
    "MS-4L",
    "STK-a688dd52",
    "STK-ba0c57f0",
    "BRKT-ALI-5MM-C766",
    "HN-M8-ZN-CL8",
]

MARKUP_DIVISOR = Decimal("1.2")
CENT = Decimal("0.01")


def set_material_costs(apps, schema_editor):
    Stock = apps.get_model("purchasing", "Stock")
    for item_code in MATERIAL_ITEM_CODES:
        stock = Stock.objects.get(item_code=item_code)
        stock.unit_cost = (stock.unit_revenue / MARKUP_DIVISOR).quantize(
            CENT, rounding=ROUND_HALF_UP
        )
        stock.save(update_fields=["unit_cost"])


def reverse_set_material_costs(apps, schema_editor):
    Stock = apps.get_model("purchasing", "Stock")
    for item_code in MATERIAL_ITEM_CODES:
        stock = Stock.objects.get(item_code=item_code)
        stock.unit_cost = Decimal("0.00")
        stock.save(update_fields=["unit_cost"])


class Migration(migrations.Migration):

    dependencies = [
        ("purchasing", "0036_set_finished_goods_costs"),
    ]

    operations = [
        migrations.RunPython(set_material_costs, reverse_set_material_costs),
    ]
