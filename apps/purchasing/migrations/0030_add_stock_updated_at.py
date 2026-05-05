from django.db import migrations, models
from django.utils import timezone


def backfill_updated_at(apps, schema_editor):
    Stock = apps.get_model("purchasing", "Stock")
    Stock.objects.filter(updated_at__isnull=True).update(updated_at=timezone.now())


class Migration(migrations.Migration):

    dependencies = [
        ("purchasing", "0029_alter_purchaseorder_table_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="stock",
            name="updated_at",
            field=models.DateTimeField(
                auto_now=True,
                help_text=(
                    "Auto-bumped on every save(); feeds the "
                    "/api/data-versions/ freshness signal so the frontend "
                    "stockStore can detect catalogue changes (e.g. Xero "
                    "unit_cost updates) and refetch."
                ),
                null=True,
            ),
        ),
        migrations.RunPython(backfill_updated_at, migrations.RunPython.noop),
    ]
