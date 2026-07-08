from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0003_drop_orphaned_phone_mapping_table"),
    ]

    operations = [
        # The index is removed BEFORE the field rename and re-added after:
        # index ops render their field list against the state they run in, so
        # the reverse direction of a RenameField/RemoveIndex/AddIndex ordering
        # would re-add the index against the renamed field and fail.
        migrations.RemoveIndex(
            model_name="phonecallrecord",
            name="crm_phone_client_call_idx",
        ),
        migrations.RenameField(
            model_name="phonecallrecord",
            old_name="client",
            new_name="company",
        ),
        migrations.AddIndex(
            model_name="phonecallrecord",
            index=models.Index(
                fields=["company", "-call_datetime"],
                name="crm_phone_company_call_idx",
            ),
        ),
    ]
