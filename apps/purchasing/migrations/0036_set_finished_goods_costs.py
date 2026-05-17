"""Data migration to set unit_cost on finished-goods stock entries.

Finished goods are priced at ~100% markup, so cost = revenue / 2.
These all had unit_cost=$0.00, which produced bogus margins on jobs.
"""

from decimal import Decimal

from django.db import migrations

FINISHED_GOODS_COSTS = {
    "LARGE WITCH BACKBOARD": Decimal("390.00"),
    "LARGE WITCH NO BACKBOARD": Decimal("340.00"),
    "SMALL WITCH SCENE": Decimal("45.00"),
    "SMALL HAND GRAB SCENE": Decimal("37.50"),
    "FANTAIL": Decimal("14.00"),
}


def set_finished_goods_costs(apps, schema_editor):
    Stock = apps.get_model("purchasing", "Stock")
    for item_code, cost in FINISHED_GOODS_COSTS.items():
        stock = Stock.objects.get(item_code=item_code)
        stock.unit_cost = cost
        stock.save(update_fields=["unit_cost"])


def reverse_set_finished_goods_costs(apps, schema_editor):
    Stock = apps.get_model("purchasing", "Stock")
    for item_code in FINISHED_GOODS_COSTS:
        stock = Stock.objects.get(item_code=item_code)
        stock.unit_cost = Decimal("0.00")
        stock.save(update_fields=["unit_cost"])


class Migration(migrations.Migration):

    dependencies = [
        ("purchasing", "0035_set_service_labour_costs"),
    ]

    operations = [
        migrations.RunPython(
            set_finished_goods_costs, reverse_set_finished_goods_costs
        ),
    ]
