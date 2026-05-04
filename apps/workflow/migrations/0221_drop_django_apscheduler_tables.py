"""Drop the django_apscheduler tables.

Once django_apscheduler is removed from INSTALLED_APPS, Django stops managing
these tables. Drop them explicitly so the schema doesn't accumulate dead
tables. Reverse migration is a no-op — re-adding the tables would require
re-installing django_apscheduler.
"""

from django.db import migrations


def drop_tables(apps, schema_editor):
    schema_editor.execute(
        "DROP TABLE IF EXISTS django_apscheduler_djangojobexecution CASCADE;"
    )
    schema_editor.execute("DROP TABLE IF EXISTS django_apscheduler_djangojob CASCADE;")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0220_seed_celery_beat_schedule"),
    ]

    operations = [
        migrations.RunPython(drop_tables, noop),
    ]
