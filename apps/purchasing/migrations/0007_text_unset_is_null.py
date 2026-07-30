"""Give purchasing's remaining text columns a single spelling of "unset".

These columns were NOT NULL with blank=True, so "" was their empty value
while their nullable siblings used NULL — the same fact spelled two ways
across the schema. They become nullable, their "" rows become NULL, and a
CHECK constraint keeps them that way (see CLAUDE.md).

Irreversible: reverse cannot tell a row that was "" from one that was
already NULL, so it is a no-op rather than a wrong restore.
"""


from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("purchasing", "0006_stock_location_nullable"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchaseordersupplierquote",
            name="mime_type",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.RunSQL(
            sql='UPDATE purchasing_purchaseordersupplierquote SET "mime_type" = NULL WHERE "mime_type" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
