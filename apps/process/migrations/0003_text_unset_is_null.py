"""Give process's remaining text columns a single spelling of "unset".

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
        ("process", "0002_forbid_blank_text"),
    ]

    operations = [
        migrations.AlterField(
            model_name="historicalprocedure",
            name="google_doc_id",
            field=models.CharField(
                blank=True,
                help_text="Google Docs document ID",
                max_length=100,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="historicalprocedure",
            name="google_doc_url",
            field=models.URLField(
                blank=True,
                help_text="URL to edit the document in Google Docs",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="historicalprocedure",
            name="site_location",
            field=models.CharField(
                blank=True, help_text="Work site location", max_length=500, null=True
            ),
        ),
        migrations.AlterField(
            model_name="procedure",
            name="google_doc_id",
            field=models.CharField(
                blank=True,
                help_text="Google Docs document ID",
                max_length=100,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="procedure",
            name="google_doc_url",
            field=models.URLField(
                blank=True,
                help_text="URL to edit the document in Google Docs",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="procedure",
            name="site_location",
            field=models.CharField(
                blank=True, help_text="Work site location", max_length=500, null=True
            ),
        ),
        migrations.RunSQL(
            sql='UPDATE process_procedure SET "site_location" = NULL WHERE "site_location" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE process_procedure SET "google_doc_id" = NULL WHERE "google_doc_id" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE process_procedure SET "google_doc_url" = NULL WHERE "google_doc_url" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
