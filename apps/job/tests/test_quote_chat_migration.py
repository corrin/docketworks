"""Preserve the v1 chat transcript and metadata when adopting SDK storage."""

import pytest
from chatkit.types import AssistantMessageItem, UserMessageItem
from django.db import connection, migrations
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone

from apps.job.chat.store import ITEM_ADAPTER
from apps.job.models import Job, JobQuoteChat, JobQuoteChatThread

pytestmark = pytest.mark.django_db


def test_legacy_messages_keep_ids_text_timestamps_and_metadata(job: Job) -> None:
    """Run the actual data migration over its historical ORM shape."""
    loader = MigrationLoader(connection)
    migration = loader.disk_migrations[("job", "0006_migrate_quote_chat")]
    state = loader.project_state([("job", "0005_chatkit_conversations")])
    transform = next(op for op in migration.operations if isinstance(op, migrations.RunPython))
    historical = state.apps.get_model("job", "JobQuoteChat")
    timestamp = timezone.now()
    # GPT: PostgreSQL rolls this historical schema setup back with the test's
    # transaction; reversing the destructive production migration would lose SDK items.
    with connection.schema_editor() as editor:
        for name in ("job", "role", "content", "metadata"):
            editor.add_field(historical, historical._meta.get_field(name))
        for name in ("thread", "payload"):
            editor.alter_field(
                JobQuoteChat,
                next(field for field in JobQuoteChat._meta.local_fields if field.name == name),
                historical._meta.get_field(name),
            )
    for role, text in (("user", "Price a stainless bench"), ("assistant", "What thickness?")):
        row = historical.objects.create(
            job_id=job.id,
            message_id=f"legacy-{role}",
            role=role,
            content=text,
            metadata={"author": "Legacy operator", "mode": "PRICE"},
        )
        historical.objects.filter(pk=row.pk).update(timestamp=timestamp)
    with connection.schema_editor() as editor:
        transform.code(state.apps, editor)
    thread = JobQuoteChatThread.objects.get(job=job)
    items = [
        ITEM_ADAPTER.validate_python(row.payload)
        for row in JobQuoteChat.objects.order_by("message_id")
    ]
    assistant, user = items
    assert isinstance(user, UserMessageItem) and isinstance(assistant, AssistantMessageItem)
    assert user.id == "legacy-user" and assistant.id == "legacy-assistant"
    assert user.created_at == timestamp and assistant.created_at == timestamp
    assert user.content[0].text == "Price a stainless bench"
    assert assistant.content[0].text == "What thickness?"
    assert thread.payload["metadata"]["legacy_message_metadata"][user.id] == {
        "author": "Legacy operator",
        "mode": "PRICE",
    }


def test_rollback_only_allows_an_empty_chat_store(job: Job) -> None:
    loader = MigrationLoader(connection)
    migration = loader.disk_migrations[("job", "0006_migrate_quote_chat")]
    state = loader.project_state([("job", "0005_chatkit_conversations")])
    transform = next(op for op in migration.operations if isinstance(op, migrations.RunPython))
    assert transform.reverse_code is not None
    with connection.schema_editor() as editor:
        transform.reverse_code(state.apps, editor)
    JobQuoteChatThread.objects.create(
        id="thr_retained", job=job, created_at=timezone.now(), payload={}
    )
    with connection.schema_editor() as editor, pytest.raises(IrreversibleError):
        transform.reverse_code(state.apps, editor)
    assert JobQuoteChatThread.objects.filter(id="thr_retained").exists()
