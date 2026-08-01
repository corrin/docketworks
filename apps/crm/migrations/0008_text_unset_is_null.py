"""Give crm's remaining text columns a single spelling of "unset".

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
        ("crm", "0007_forbid_blank_text"),
    ]

    operations = [
        migrations.AlterField(
            model_name="phonecallrecord",
            name="call_type",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AlterField(
            model_name="phonecallrecord",
            name="description",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="phonecallrecord",
            name="destination",
            field=models.CharField(blank=True, max_length=150, null=True),
        ),
        migrations.AlterField(
            model_name="phonecallrecord",
            name="external_number",
            field=models.CharField(blank=True, max_length=150, null=True),
        ),
        migrations.AlterField(
            model_name="phonecallrecord",
            name="normalized_destination",
            field=models.CharField(blank=True, max_length=150, null=True),
        ),
        migrations.AlterField(
            model_name="phonecallrecord",
            name="normalized_origin",
            field=models.CharField(blank=True, max_length=150, null=True),
        ),
        migrations.AlterField(
            model_name="phonecallrecord",
            name="origin",
            field=models.CharField(blank=True, max_length=150, null=True),
        ),
        migrations.AlterField(
            model_name="phonecallrecord",
            name="our_number",
            field=models.CharField(blank=True, max_length=150, null=True),
        ),
        migrations.AlterField(
            model_name="phonecallrecord",
            name="status",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AlterField(
            model_name="phonecallrecording",
            name="archive_error",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="phonecallrecording",
            name="content_type",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AlterField(
            model_name="phonecallrecording",
            name="filename",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name="phonecallrecording",
            name="provider_delete_error",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="phonecallrecording",
            name="sha256",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name="phonecallrecording",
            name="storage_path",
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        migrations.AlterField(
            model_name="phoneendpoint",
            name="provider_account_code",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AlterField(
            model_name="phoneprovidersettings",
            name="account_code",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.RunSQL(
            sql='UPDATE crm_phoneendpoint SET "provider_account_code" = NULL WHERE "provider_account_code" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE crm_phoneprovidersettings SET "account_code" = NULL WHERE "account_code" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE crm_phonecallrecord SET "call_type" = NULL WHERE "call_type" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE crm_phonecallrecord SET "status" = NULL WHERE "status" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE crm_phonecallrecord SET "description" = NULL WHERE "description" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE crm_phonecallrecord SET "origin" = NULL WHERE "origin" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE crm_phonecallrecord SET "destination" = NULL WHERE "destination" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE crm_phonecallrecord SET "normalized_origin" = NULL WHERE "normalized_origin" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE crm_phonecallrecord SET "normalized_destination" = NULL WHERE "normalized_destination" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE crm_phonecallrecord SET "our_number" = NULL WHERE "our_number" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE crm_phonecallrecord SET "external_number" = NULL WHERE "external_number" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE crm_phonecallrecording SET "filename" = NULL WHERE "filename" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE crm_phonecallrecording SET "storage_path" = NULL WHERE "storage_path" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE crm_phonecallrecording SET "content_type" = NULL WHERE "content_type" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE crm_phonecallrecording SET "sha256" = NULL WHERE "sha256" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE crm_phonecallrecording SET "archive_error" = NULL WHERE "archive_error" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='UPDATE crm_phonecallrecording SET "provider_delete_error" = NULL WHERE "provider_delete_error" = \'\'',
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
