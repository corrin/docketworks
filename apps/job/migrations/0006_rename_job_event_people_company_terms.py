from typing import Any

from django.db import migrations

EVENT_TYPE_RENAMES = {
    "client_changed": "company_changed",
    "contact_changed": "person_changed",
}
EVENT_TYPE_REVERSES = {value: key for key, value in EVENT_TYPE_RENAMES.items()}
DETAIL_LABEL_RENAMES = {
    "Client": "Company",
    "Contact": "Person",
}
DETAIL_LABEL_REVERSES = {value: key for key, value in DETAIL_LABEL_RENAMES.items()}


def _rename_event_types(JobEvent: Any, mapping: dict[str, str]) -> None:
    for old_value, new_value in mapping.items():
        JobEvent.objects.filter(event_type=old_value).update(event_type=new_value)


def _rename_detail_labels(JobEvent: Any, mapping: dict[str, str]) -> None:
    queryset = JobEvent.objects.filter(
        event_type__in=[
            "client_changed",
            "contact_changed",
            "company_changed",
            "person_changed",
        ]
    )
    for event in queryset.iterator():
        detail = event.detail or {}
        changed = False

        field_name = detail.get("field_name")
        if field_name in mapping:
            detail["field_name"] = mapping[field_name]
            changed = True

        changes = detail.get("changes")
        if isinstance(changes, list):
            for change in changes:
                if not isinstance(change, dict):
                    continue
                change_field_name = change.get("field_name")
                if change_field_name in mapping:
                    change["field_name"] = mapping[change_field_name]
                    changed = True

        if changed:
            event.detail = detail
            event.save(update_fields=["detail"])


def forwards(apps: Any, schema_editor: Any) -> None:
    JobEvent = apps.get_model("job", "JobEvent")
    _rename_detail_labels(JobEvent, DETAIL_LABEL_RENAMES)
    _rename_event_types(JobEvent, EVENT_TYPE_RENAMES)


def backwards(apps: Any, schema_editor: Any) -> None:
    JobEvent = apps.get_model("job", "JobEvent")
    _rename_detail_labels(JobEvent, DETAIL_LABEL_REVERSES)
    _rename_event_types(JobEvent, EVENT_TYPE_REVERSES)


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0005_remove_job_contact_alter_job_person"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
