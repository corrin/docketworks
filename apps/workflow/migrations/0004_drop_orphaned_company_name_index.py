"""Drop the orphaned varchar_pattern_ops index on companydefaults.company_name.

Old Django versions created a companion `_like` index for indexed varchar
columns; when the column's index/unique was later removed the companion was
left behind on live databases (and the historic graph reproduced it). The
model declares no index on company_name and the baseline schema creates
none, so this migration normalises existing databases to match. Fresh
databases no-op via IF EXISTS. Irreversible cleanup: reverse is a no-op.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0003_seed_celery_beat_schedules"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "DROP INDEX IF EXISTS "
                "workflow_companydefaults_company_name_c3a41743_like"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
