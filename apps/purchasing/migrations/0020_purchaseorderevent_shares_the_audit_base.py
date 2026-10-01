"""PurchaseOrderEvent subclasses the shared AuditEvent base.

Its one event kind was a typed note held in a bespoke ``description`` column.
JobEvent already stores a typed note as ``event_type="manual_note"`` with the
text in ``detail.note_text`` and renders it from there, so every existing row
takes that shape and the column goes. The reverse copies the note text back.
"""

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


def notes_into_detail(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    PurchaseOrderEvent = apps.get_model("purchasing", "PurchaseOrderEvent")
    for event in PurchaseOrderEvent.objects.all():
        event.event_type = "manual_note"
        event.detail = {"note_text": event.description}
        event.save(update_fields=["event_type", "detail"])


def notes_back_into_description(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    PurchaseOrderEvent = apps.get_model("purchasing", "PurchaseOrderEvent")
    for event in PurchaseOrderEvent.objects.all():
        event.description = str(event.detail.get("note_text", ""))
        event.save(update_fields=["description"])


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0019_purchaseorder_created_by_not_null"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaseorderevent",
            name="delta_after",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="purchaseorderevent",
            name="delta_before",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="purchaseorderevent",
            name="detail",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="purchaseorderevent",
            name="event_type",
            field=models.CharField(default="manual_note", max_length=100),
            preserve_default=False,
        ),
        migrations.RunPython(notes_into_detail, notes_back_into_description),
        migrations.RemoveField(
            model_name="purchaseorderevent",
            name="description",
        ),
    ]
