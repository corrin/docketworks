import django.db.models.deletion
from django.db import migrations, models


def populate_shop_client_fk(apps, schema_editor):
    CompanyDefaults = apps.get_model("workflow", "CompanyDefaults")
    Client = apps.get_model("client", "Client")

    for defaults in CompanyDefaults.objects.all():
        if not defaults.shop_client_name:
            raise ValueError(
                "CompanyDefaults.shop_client_name is not configured. "
                "Cannot migrate to shop_client FK."
            )

        clients = Client.objects.filter(name=defaults.shop_client_name)
        client_count = clients.count()
        if client_count == 0:
            raise ValueError(
                f"No shop client found with name '{defaults.shop_client_name}'"
            )
        if client_count > 1:
            raise RuntimeError(
                f"Multiple shop clients found ({client_count}) with name "
                f"'{defaults.shop_client_name}'"
            )

        defaults.shop_client_id = clients.get().id
        defaults.save(update_fields=["shop_client"])


def restore_shop_client_name(apps, schema_editor):
    CompanyDefaults = apps.get_model("workflow", "CompanyDefaults")
    Client = apps.get_model("client", "Client")

    for defaults in CompanyDefaults.objects.all():
        client = Client.objects.get(id=defaults.shop_client_id)
        defaults.shop_client_name = client.name
        defaults.save(update_fields=["shop_client_name"])


class Migration(migrations.Migration):
    dependencies = [
        ("client", "0019_client_name_fts_index"),
        ("workflow", "0230_session_replay_file_storage"),
    ]

    operations = [
        migrations.AddField(
            model_name="companydefaults",
            name="shop_client",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="client.client",
                help_text="Internal client used for tracking shop work.",
            ),
        ),
        migrations.RunPython(populate_shop_client_fk, restore_shop_client_name),
        migrations.AlterField(
            model_name="companydefaults",
            name="shop_client",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="client.client",
                help_text="Internal client used for tracking shop work.",
            ),
        ),
        migrations.RemoveField(
            model_name="companydefaults",
            name="shop_client_name",
        ),
    ]
