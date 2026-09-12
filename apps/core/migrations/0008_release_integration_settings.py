"""Release model state without touching the table adopted by integrations."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("core", "0007_retention_and_quote_expiry_settings")]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[migrations.DeleteModel(name="IntegrationSettings")],
        ),
    ]
