"""PhoneProviderSettings leaves the crm app's model state.

State only: the table ``crm_phoneprovidersettings`` stays exactly where it is
and core/0002 adopts it as ``IntegrationSettings`` (ADR 0053). A database
operation here would drop a table that still holds the production row.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="PhoneProviderSettings")],
            database_operations=[],
        ),
    ]
