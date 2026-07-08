from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0002_seed_labour_subtypes"),
    ]

    operations = [
        migrations.RenameField(
            model_name="job",
            old_name="client",
            new_name="company",
        ),
    ]
