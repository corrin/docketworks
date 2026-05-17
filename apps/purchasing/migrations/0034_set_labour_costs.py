"""Data migration to set unit_cost on labour stock entries.

LABOUR and LABOUR ONSITE both had unit_cost=$0.00 against non-zero
unit_revenue, which produced incorrect margin/cost reporting whenever the
lines were used on a job. Set the true costs:
- LABOUR:        $32/hr (revenue $110)
- LABOUR ONSITE: $40/hr (revenue $165)
"""

from decimal import Decimal

from django.db import migrations

LABOUR_COSTS = {
    "LABOUR": Decimal("32.00"),
    "LABOUR ONSITE": Decimal("40.00"),
}


def set_labour_costs(apps, schema_editor):
    Stock = apps.get_model("purchasing", "Stock")
    for item_code, cost in LABOUR_COSTS.items():
        stock = Stock.objects.get(item_code=item_code)
        stock.unit_cost = cost
        stock.save(update_fields=["unit_cost"])


def reverse_set_labour_costs(apps, schema_editor):
    Stock = apps.get_model("purchasing", "Stock")
    for item_code in LABOUR_COSTS:
        stock = Stock.objects.get(item_code=item_code)
        stock.unit_cost = Decimal("0.00")
        stock.save(update_fields=["unit_cost"])


class Migration(migrations.Migration):

    dependencies = [
        ("purchasing", "0033_use_aluminium_metal_type"),
    ]

    operations = [
        migrations.RunPython(set_labour_costs, reverse_set_labour_costs),
    ]
