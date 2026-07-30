"""Make NULL the only unset for metal_type, dropping the UNSPECIFIED member.

MetalType.UNSPECIFIED was a second way of saying "no metal" alongside NULL,
and the frontend translated it back to null on display. Removing the member
leaves NULL as the single unset, in line with the rule in CLAUDE.md.

Stock.metal_type is relaxed to nullable here rather than in 0003 because it
was NOT NULL until this migration, so its rows could not be cleared earlier.
The CHECK constraint is added afterwards for the same reason: the column
only joins the nullable-text set once it is nullable.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("purchasing", "0004_forbid_blank_text"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchaseorderline",
            name="metal_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("stainless_steel", "Stainless Steel"),
                    ("mild_steel", "Mild Steel"),
                    ("aluminium", "Aluminium"),
                    ("brass", "Brass"),
                    ("copper", "Copper"),
                    ("titanium", "Titanium"),
                    ("zinc", "Zinc"),
                    ("galvanized", "Galvanized"),
                    ("other", "Other"),
                ],
                max_length=100,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="stock",
            name="metal_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("stainless_steel", "Stainless Steel"),
                    ("mild_steel", "Mild Steel"),
                    ("aluminium", "Aluminium"),
                    ("brass", "Brass"),
                    ("copper", "Copper"),
                    ("titanium", "Titanium"),
                    ("zinc", "Zinc"),
                    ("galvanized", "Galvanized"),
                    ("other", "Other"),
                ],
                help_text="Type of metal",
                max_length=100,
                null=True,
            ),
        ),
        migrations.RunSQL(
            sql=(
                "UPDATE purchasing_stock SET metal_type = NULL "
                "WHERE metal_type IN ('', 'steel', 'unspecified')"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql=(
                "ALTER TABLE purchasing_stock "
                "ADD CONSTRAINT metal_type_not_blank CHECK (metal_type <> '')"
            ),
            reverse_sql=(
                "ALTER TABLE purchasing_stock "
                "DROP CONSTRAINT IF EXISTS metal_type_not_blank"
            ),
        ),
    ]
