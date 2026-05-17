"""Data migration to set unit_cost on labour-like service stock entries.

The rule is: revenue $110/hr (or equivalent) -> $32/hr cost; revenue above
$110/hr -> $40/hr cost. Per-15-minute entries scale at 1/4 of the hourly
cost.

These all had unit_cost=$0.00, which produced bogus margins on jobs.
"""

from decimal import Decimal

from django.db import migrations

SERVICE_COSTS = {
    # $110/hr equivalents -> $32/hr cost
    "ADMIN FEE": Decimal("32.00"),
    "QUOTING": Decimal("32.00"),
    # $27.50/15min == $110/hr -> $8.00/15min cost
    "PICK UP FEE": Decimal("8.00"),
    "DELIVERY FEE": Decimal("8.00"),
    # Above $110/hr -> $40/hr cost
    "SITE VISIT HOURLY": Decimal("40.00"),
    "Quote Onsite": Decimal("40.00"),
}


def set_service_costs(apps, schema_editor):
    Stock = apps.get_model("purchasing", "Stock")
    for item_code, cost in SERVICE_COSTS.items():
        stock = Stock.objects.get(item_code=item_code)
        stock.unit_cost = cost
        stock.save(update_fields=["unit_cost"])


def reverse_set_service_costs(apps, schema_editor):
    Stock = apps.get_model("purchasing", "Stock")
    for item_code in SERVICE_COSTS:
        stock = Stock.objects.get(item_code=item_code)
        stock.unit_cost = Decimal("0.00")
        stock.save(update_fields=["unit_cost"])


class Migration(migrations.Migration):

    dependencies = [
        ("purchasing", "0034_set_labour_costs"),
    ]

    operations = [
        migrations.RunPython(set_service_costs, reverse_set_service_costs),
    ]
