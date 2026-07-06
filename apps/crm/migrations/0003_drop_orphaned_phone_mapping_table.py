"""Drop the orphaned crm_phonenumberclientmapping table.

Created by a since-renumbered historic migration (its ledger row survives as
a ghost); the model was removed without a DeleteModel ever running, leaving
an empty, code-unreferenced table on live databases. The baseline schema
does not create it, so this migration normalises existing databases to
match. Fresh databases no-op via IF EXISTS. Irreversible cleanup: reverse
is a no-op.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0002_seed_phone_call_schedules"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS crm_phonenumberclientmapping",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
