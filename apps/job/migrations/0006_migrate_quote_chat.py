"""GPT: A separate transaction clears FK triggers before old columns are removed."""

from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError


def migrate_messages(apps: Apps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Retain message ids, timestamps, text and legacy metadata in one job thread."""
    message_model = apps.get_model("job", "JobQuoteChat")
    thread_model = apps.get_model("job", "JobQuoteChatThread")
    job_ids = message_model.objects.order_by().values_list("job_id", flat=True).distinct()
    for job_id in job_ids.iterator():
        messages = list(message_model.objects.filter(job_id=job_id).order_by("timestamp", "id"))
        thread_id = f"thr_legacy_{job_id.hex}"
        created_at = messages[0].timestamp
        thread_model.objects.create(
            id=thread_id,
            job_id=job_id,
            created_at=created_at,
            payload={
                "id": thread_id,
                "title": "Previous quoting conversation",
                "created_at": created_at.isoformat(),
                "status": {"type": "active"},
                "metadata": {
                    "legacy_message_metadata": {
                        message.message_id: message.metadata for message in messages
                    }
                },
            },
        )
        for message in messages:
            if message.role not in {"user", "assistant"}:
                raise ValueError(f"Unknown chat role on message {message.id}: {message.role}")
            user_message = message.role == "user"
            payload = {
                "id": message.message_id,
                "thread_id": thread_id,
                "created_at": message.timestamp.isoformat(),
                "type": "user_message" if user_message else "assistant_message",
                "content": [
                    {
                        "type": "input_text" if user_message else "output_text",
                        "text": message.content,
                    }
                ],
            }
            if user_message:
                payload["inference_options"] = {}
            message.thread_id = thread_id
            message.payload = payload
            message.save(update_fields=["thread_id", "payload"])


def reverse_empty_database(apps: Apps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Allow v1 restore preparation only before conversations exist."""
    if (
        apps.get_model("job", "JobQuoteChat").objects.exists()
        or apps.get_model("job", "JobQuoteChatThread").objects.exists()
    ):
        raise IrreversibleError("Chat conversations require restoring the pre-migration backup.")


class Migration(migrations.Migration):
    dependencies = [("job", "0005_chatkit_conversations")]

    operations = [migrations.RunPython(migrate_messages, reverse_empty_database)]
