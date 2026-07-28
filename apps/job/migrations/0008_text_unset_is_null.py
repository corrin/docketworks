"""Give job's remaining text columns a single spelling of "unset".

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
        ("job", "0007_forbid_blank_text"),
    ]

    operations = [
        migrations.AlterField(
            model_name="costline",
            name="desc",
            field=models.CharField(
                blank=True,
                help_text="Description of this cost line",
                max_length=255,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="jobdeltarejection",
            name="checksum",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.AlterField(
            model_name="jobdeltarejection",
            name="detail",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="jobdeltarejection",
            name="request_etag",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.AlterField(
            model_name="jobevent",
            name="delta_checksum",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.AlterField(
            model_name="jobfile",
            name="mime_type",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.RunSQL(
            sql='UPDATE job_costline SET "desc" = NULL WHERE "desc" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE job_jobevent SET "delta_checksum" = NULL WHERE "delta_checksum" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE job_jobdeltarejection SET "detail" = NULL WHERE "detail" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE job_jobdeltarejection SET "checksum" = NULL WHERE "checksum" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE job_jobdeltarejection SET "request_etag" = NULL WHERE "request_etag" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE job_jobfile SET "mime_type" = NULL WHERE "mime_type" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
