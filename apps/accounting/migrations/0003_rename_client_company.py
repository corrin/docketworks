from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0002_baseline"),
    ]

    operations = [
        migrations.RenameField(
            model_name="invoice",
            old_name="client",
            new_name="company",
        ),
        migrations.RenameField(
            model_name="bill",
            old_name="client",
            new_name="company",
        ),
        migrations.RenameField(
            model_name="creditnote",
            old_name="client",
            new_name="company",
        ),
        migrations.RenameField(
            model_name="quote",
            old_name="client",
            new_name="company",
        ),
    ]
