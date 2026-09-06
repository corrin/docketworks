"""The shared write and verification rules for admin and instance bootstrap."""

from typing import Annotated

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from litellm.exceptions import (
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import BaseModel, ConfigDict, Field

from apps.ai.enums import AIProviderTypes
from apps.ai.models import AIProvider
from apps.ai.services.llm_client import LLMConfigurationError, chat_completion, resolve_target
from apps.core.errors import InvalidInputError
from apps.core.schemas import NonBlankText, NullableText, omittable

ProviderName = Annotated[NonBlankText, Field(max_length=100)]
ModelName = Annotated[NullableText, Field(max_length=100)]
ProviderKey = Annotated[NullableText, Field(max_length=255, repr=False)]


class ProviderCreate(BaseModel):
    """Require a usable new entry; unset values belong to explicit edits."""

    model_config = ConfigDict(extra="forbid")
    name: ProviderName
    provider_type: AIProviderTypes
    model_name: Annotated[NonBlankText, Field(max_length=100)]
    api_key: Annotated[NonBlankText, Field(max_length=255, repr=False)]


class ProviderPatch(BaseModel):
    """Omitted fields retain their value; null clears model or credentials."""

    model_config = ConfigDict(extra="forbid")
    name: ProviderName = omittable("")
    provider_type: AIProviderTypes = omittable(AIProviderTypes.OPENAI)
    model_name: ModelName = omittable(None)
    api_key: ProviderKey = omittable(None)


def _save(provider: AIProvider) -> AIProvider:
    """Validate all persisted fields without reporting credential values."""
    try:
        provider.full_clean()
    except ValidationError as exc:
        raise InvalidInputError("; ".join(exc.messages)) from exc
    provider.save()
    return provider


def create_provider(payload: ProviderCreate) -> AIProvider:
    """Create a provider without implicitly changing the application default."""
    return _save(AIProvider(**payload.model_dump()))


@transaction.atomic
def update_provider(provider_id: int, payload: ProviderPatch) -> AIProvider:
    """Serialize edits to an existing row and change only supplied fields."""
    provider = get_object_or_404(AIProvider.objects.select_for_update(), pk=provider_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(provider, field, value)
    return _save(provider)


@transaction.atomic
def set_default_provider(provider_id: int) -> AIProvider:
    """Lock the catalogue in ID order and atomically select one usable default."""
    providers = list(AIProvider.objects.select_for_update().order_by("pk"))
    provider = next((row for row in providers if row.pk == provider_id), None)
    if provider is None:
        raise Http404("AI provider not found")
    try:
        resolve_target(provider=provider)
    except LLMConfigurationError as exc:
        raise InvalidInputError(str(exc)) from exc
    AIProvider.objects.filter(default=True).exclude(pk=provider_id).update(default=False)
    provider.default = True
    provider.save(update_fields=["default"])
    return provider


def verify_provider(provider: AIProvider) -> str:
    """Prove saved credentials/model through the same metered gateway used by features."""
    try:
        chat_completion("Reply with the single word ready.", provider=provider, max_tokens=512)
    except LLMConfigurationError as exc:
        raise InvalidInputError(str(exc)) from exc
    except (AuthenticationError, PermissionDeniedError) as exc:
        raise InvalidInputError(
            "The provider rejected these credentials or model permissions."
        ) from exc
    except (NotFoundError, BadRequestError) as exc:
        raise InvalidInputError(
            "The provider rejected this model or chat request configuration."
        ) from exc
    except RateLimitError as exc:
        raise InvalidInputError("The provider's quota or rate limit prevented this test.") from exc
    return resolve_target(provider=provider).model
