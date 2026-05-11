from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0223_delete_cachestate"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="apperror",
            name="app_error_resolved_msg_idx",
        ),
    ]
