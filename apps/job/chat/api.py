"""Configuration uses Ninja; the library-owned ChatKit stream uses Django ASGI."""

from uuid import UUID

from asgiref.sync import sync_to_async
from chatkit.server import StreamingResult
from chatkit.store import NotFoundError
from django.http import HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse
from django.http.response import HttpResponseBase
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from ninja import Router, Schema
from pydantic import ValidationError

from apps.ai.models import AIProvider
from apps.ai.services.llm_client import LLMConfigurationError, resolve_target
from apps.core.auth import OfficeStaffCookieJWTAuth, StaffPermissions
from apps.core.errors import AppErrorContext, persist_app_error
from apps.core.events import authenticate_stream_request
from apps.job.chat.server import chat_server
from apps.job.chat.store import ChatContext
from apps.job.models import Job
from apps.platform.integrations.models import IntegrationSettings

router = Router(tags=["Jobs"])


class QuotingChatModelOut(Schema):
    """Public model-picker metadata; credentials remain in the gateway."""

    id: str
    label: str
    description: str
    default: bool


class QuotingChatConfigOut(Schema):
    """Public embed configuration and Django's masked CSRF token."""

    domain_key: str | None
    csrf_token: str
    configuration_error: str | None
    model: str | None
    models: list[QuotingChatModelOut]
    can_configure: bool


@router.get(
    "/{job_id}/quote-chat/config/",
    auth=OfficeStaffCookieJWTAuth(),
    response=QuotingChatConfigOut,
    operation_id="job_quote_chat_config_retrieve",
)
def quote_chat_config(request: HttpRequest, job_id: UUID) -> QuotingChatConfigOut:
    """Read configuration; the domain key is public, vendor API keys stay server-side."""
    get_object_or_404(Job, id=job_id)
    domain_key = IntegrationSettings.get_solo().chatkit_domain_key
    issue = None
    model = None
    try:
        model = resolve_target().model
    # deliberate-swallow: display missing configuration before starting a conversation.
    except LLMConfigurationError as exc:
        issue = str(exc)
    if domain_key is None:
        issue = "Configure the ChatKit domain key in Integrations to enable quoting chat."
    return QuotingChatConfigOut(
        domain_key=domain_key,
        models=[
            QuotingChatModelOut(
                id=str(provider.pk),
                label=provider.name,
                description=f"{provider.provider_type} · {provider.model_name}",
                default=provider.default,
            )
            for provider in AIProvider.objects.filter(
                api_key__isnull=False, model_name__isnull=False
            ).order_by("name", "pk")
        ],
        configuration_error=issue,
        model=model,
        can_configure=isinstance(request.user, StaffPermissions) and request.user.is_superuser,
        csrf_token=get_token(request),
    )


@require_POST
async def quote_chat(request: HttpRequest, job_id: UUID) -> HttpResponseBase:
    """Authenticate and pass the SDK's request/response through without reimplementing it."""
    try:
        refusal = await sync_to_async(authenticate_stream_request)(
            request, OfficeStaffCookieJWTAuth()
        )
        if refusal is not None:
            return refusal
        if not await Job.objects.filter(id=job_id).aexists():
            return JsonResponse({"detail": "Job not found"}, status=404)
        result = await chat_server.process(request.body, ChatContext(job_id=job_id))
    # deliberate-swallow: a missing or differently scoped SDK resource is a normal 404.
    except NotFoundError as exc:
        return JsonResponse({"detail": str(exc)}, status=404)
    # deliberate-swallow: malformed ChatKit input is a request error, before model execution.
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    except Exception as exc:
        await sync_to_async(persist_app_error)(exc, AppErrorContext(job_id=job_id))
        raise
    if isinstance(result, StreamingResult):
        response = StreamingHttpResponse(result, content_type="text/event-stream")
        response["Content-Encoding"] = "identity"
        response["Cache-Control"] = "no-cache, no-store"
        response["X-Accel-Buffering"] = "no"
        return response
    return HttpResponse(result.json, content_type="application/json")
