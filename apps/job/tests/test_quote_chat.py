"""Quoting conversations retain history and enforce job, office and CSRF scope."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from asgiref.sync import async_to_sync
from chatkit.store import NotFoundError
from chatkit.types import InferenceOptions, ThreadMetadata, UserMessageItem, UserMessageTextContent
from django.db import IntegrityError, transaction
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.ai.models import AIProvider
from apps.ai.services.llm_client import LLMConfigurationError
from apps.company.tests.conftest import authenticate
from apps.company.tests.job_fixtures import make_job
from apps.core.models import AppError
from apps.job.chat.server import selected_target
from apps.job.chat.store import ChatContext, JobChatStore
from apps.job.models import Job, JobQuoteChat

pytestmark = pytest.mark.django_db


def create_thread(job: Job, count: int = 1) -> tuple[ChatContext, ThreadMetadata]:
    """Persist enough real SDK messages to cross history pagination boundaries."""
    context = ChatContext(job_id=job.id)
    store = JobChatStore()
    thread = ThreadMetadata(id=f"thr_{uuid4().hex}", created_at=timezone.now())
    async_to_sync(store.save_thread)(thread, context)
    for index in range(count):
        item = UserMessageItem(
            id=f"msg_{uuid4().hex}",
            thread_id=thread.id,
            created_at=thread.created_at + timedelta(seconds=index),
            content=[UserMessageTextContent(text=f"Material {index}")],
            inference_options=InferenceOptions(),
        )
        async_to_sync(store.add_thread_item)(thread.id, item, context)
    return context, thread


def test_history_pages_survive_a_new_store_instance(job: Job) -> None:
    """Prove persisted history crosses page boundaries without missing or repeated items."""
    context, thread = create_thread(job, 31)
    store = JobChatStore()
    first = async_to_sync(store.load_thread_items)(thread.id, None, 20, "asc", context)
    second = async_to_sync(store.load_thread_items)(thread.id, first.after, 20, "asc", context)
    assert first.has_more and not second.has_more
    assert len(first.data) == 20 and len(second.data) == 11
    assert len({item.id for item in first.data + second.data}) == 31
    reverse = async_to_sync(store.load_thread_items)(thread.id, None, 20, "desc", context)
    assert reverse.data[0] == second.data[-1]
    assert JobQuoteChat.objects.count() == 31


def test_foreign_job_cannot_read_modify_or_delete_conversation(job: Job) -> None:
    """Possession of a thread ID must not permit access from another job."""
    context, thread = create_thread(job)
    assert job.company is not None and job.created_by is not None
    other = ChatContext(job_id=make_job(job.company, job.created_by, name="Other job").id)
    store = JobChatStore()
    with pytest.raises(NotFoundError):
        async_to_sync(store.load_thread)(thread.id, other)
    with pytest.raises(NotFoundError):
        async_to_sync(store.delete_thread)(thread.id, other)
    with transaction.atomic(), pytest.raises(IntegrityError):
        async_to_sync(store.save_thread)(thread, other)
    page = async_to_sync(store.load_threads)(20, None, "desc", other)
    assert page.data == []
    assert async_to_sync(store.load_thread)(thread.id, context) == thread
    assert JobQuoteChat.objects.count() == 1


def test_sdk_endpoint_requires_office_login_and_csrf(
    job: Job, office_staff: Staff, workshop_staff: Staff
) -> None:
    """Exercise cookie roles and real CSRF enforcement before accepting SDK requests."""
    path = f"/api/job/jobs/{job.id}/quote-chat/"
    config_path = f"{path}config/"
    client = Client(enforce_csrf_checks=True)
    assert client.get(config_path).status_code == 401
    authenticate(client, workshop_staff)
    assert client.get(config_path).status_code == 403
    authenticate(client, office_staff)
    config = client.get(config_path)
    assert config.status_code == 200
    body = {"type": "threads.list", "params": {}}
    assert client.post(path, body, content_type="application/json").status_code == 403
    response = client.post(
        path, body, content_type="application/json", HTTP_X_CSRFTOKEN=config.json()["csrf_token"]
    )
    assert response.status_code == 200
    assert response.json()["data"] == []


def test_sdk_history_rejects_foreign_thread_id(job: Job, office_staff: Staff) -> None:
    """Reject cross-job reads through the HTTP transport without altering stored messages."""
    _, thread = create_thread(job)
    assert job.company is not None and job.created_by is not None
    other = make_job(job.company, job.created_by, name="Other job")
    client = Client()
    authenticate(client, office_staff)
    response = client.post(
        f"/api/job/jobs/{other.id}/quote-chat/",
        {"type": "threads.get_by_id", "params": {"thread_id": thread.id}},
        content_type="application/json",
    )
    assert response.status_code == 404
    assert JobQuoteChat.objects.count() == 1


@pytest.mark.parametrize(
    "failure_site",
    [
        "apps.job.chat.api.authenticate_stream_request",
        "django.db.models.query.QuerySet.aexists",
    ],
)
def test_preprocessing_failures_are_persisted_and_reraised(
    job: Job, office_staff: Staff, failure_site: str
) -> None:
    """Failures before SDK processing retain their diagnostic record and job context."""
    client = Client()
    authenticate(client, office_staff)
    with (
        patch(failure_site, side_effect=RuntimeError("Chat preprocessing failed")),
        pytest.raises(RuntimeError, match="Chat preprocessing failed"),
    ):
        client.post(
            f"/api/job/jobs/{job.id}/quote-chat/",
            {"type": "threads.list", "params": {}},
            content_type="application/json",
        )
    error = AppError.objects.get(message="Chat preprocessing failed")
    assert error.job_id == job.id


def test_missing_job_remains_a_normal_refusal(office_staff: Staff) -> None:
    """An absent job produces a 404 without recording a programming failure."""
    client = Client()
    authenticate(client, office_staff)
    response = client.post(
        f"/api/job/jobs/{uuid4()}/quote-chat/",
        {"type": "threads.list", "params": {}},
        content_type="application/json",
    )
    assert response.status_code == 404
    assert not AppError.objects.exists()


def test_model_picker_lists_configured_providers_and_uses_application_default(
    superuser_api: Client,
    job: Job,
) -> None:
    """Selection exposes names, never credentials, and accepts a different vendor per turn."""

    instant = AIProvider.objects.create(
        name="Instant",
        provider_type="OpenAI",
        model_name="chat-latest",
        api_key="private-openai",
    )
    thinking = AIProvider.objects.create(
        name="Thinking",
        provider_type="Claude",
        model_name="claude-model",
        api_key="private-claude",
        default=True,
    )
    AIProvider.objects.create(name="Unset", provider_type="Gemini", model_name="model")
    response = superuser_api.get(f"/api/job/jobs/{job.id}/quote-chat/config/")
    assert response.status_code == 200
    assert response.json()["models"] == [
        {
            "id": str(instant.pk),
            "label": "Instant",
            "description": "OpenAI · chat-latest",
            "default": False,
        },
        {
            "id": str(thinking.pk),
            "label": "Thinking",
            "description": "Claude · claude-model",
            "default": True,
        },
    ]
    assert "private-" not in response.content.decode()
    context = ChatContext(job_id=job.id)
    assert selected_target(None, context).provider_name == "Thinking"
    assert selected_target(str(instant.pk), context).provider_name == "Instant"
    assert selected_target(str(thinking.pk), context).provider_name == "Thinking"
    removed_id = str(thinking.pk)
    thinking.delete()
    with pytest.raises(LLMConfigurationError, match="removed"):
        selected_target(removed_id, context)
