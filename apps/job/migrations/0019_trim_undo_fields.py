"""Name on each undoable job event only the fields its save changed.

Events written before Job._record_change_event trimmed them name every field
the delta carried, including ones it did not change; delta_before holds only
the changed ones, so undo of such an event failed looking the others up.
"""

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

# The delta protocol's names for model attributes, as job_service maps them.
_ATTRIBUTE = {"job_status": "status"}


def trim_fields(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    events = apps.get_model("job", "JobEvent").objects.using(schema_editor.connection.alias)
    changed = []
    for event in events.filter(schema_version=1, delta_meta__has_key="fields").iterator():
        fields = event.delta_meta["fields"]
        kept = [name for name in fields if _ATTRIBUTE.get(name, name) in event.delta_before]
        if kept != fields:
            event.delta_meta = {**event.delta_meta, "fields": kept}
            changed.append(event)
    events.bulk_update(changed, ["delta_meta"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("job", "0018_job_status_valid")]

    operations = [migrations.RunPython(trim_fields, migrations.RunPython.noop)]
