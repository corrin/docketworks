from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0002_phonenumberclientmapping"),
    ]

    operations = [
        migrations.AddField(
            model_name="phonecallrecording",
            name="archive_error",
            field=models.TextField(blank=True),
        ),
    ]
