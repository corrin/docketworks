"""Give workflow's remaining text columns a single spelling of "unset".

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
        ("workflow", "0016_forbid_blank_text"),
    ]

    operations = [
        migrations.AlterField(
            model_name="aiprovider",
            name="model_name",
            field=models.CharField(
                blank=True,
                help_text="Model name (e.g., gemini-flash-latest)",
                max_length=100,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="searchtelemetryevent",
            name="normalized_query",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name="searchtelemetryevent",
            name="query",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name="searchtelemetryevent",
            name="selected_label",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name="searchtelemetryevent",
            name="selected_result_id",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name="searchtelemetryevent",
            name="source",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AlterField(
            model_name="sessionreplayrecording",
            name="user_agent",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="xeroapp",
            name="webhook_key",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.RunSQL(
            sql='UPDATE workflow_aiprovider SET "model_name" = NULL WHERE "model_name" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE workflow_searchtelemetryevent SET "source" = NULL WHERE "source" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE workflow_searchtelemetryevent SET "query" = NULL WHERE "query" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE workflow_searchtelemetryevent SET "normalized_query" = NULL WHERE "normalized_query" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE workflow_searchtelemetryevent SET "selected_result_id" = NULL WHERE "selected_result_id" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE workflow_searchtelemetryevent SET "selected_label" = NULL WHERE "selected_label" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE workflow_sessionreplayrecording SET "user_agent" = NULL WHERE "user_agent" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE workflow_xeroapp SET "webhook_key" = NULL WHERE "webhook_key" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
