from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0004_drop_orphaned_company_name_index"),
    ]

    operations = [
        migrations.RenameField(
            model_name="companydefaults",
            old_name="shop_client",
            new_name="shop_company",
        ),
        migrations.RenameField(
            model_name="companydefaults",
            old_name="test_client_name",
            new_name="test_company_name",
        ),
    ]
