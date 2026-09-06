"""Superuser-only, write-only-secret integration configuration."""

from datetime import datetime

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http import HttpRequest
from ninja import Router, Schema
from ninja.errors import HttpError

from apps.core.auth import SuperuserCookieJWTAuth
from apps.core.schemas import NullableText, omittable
from apps.platform.integrations.models import IntegrationSettings

router = Router(tags=["build-id"])


class IntegrationSettingsOut(Schema):
    """Every non-secret column, plus presence flags for the secrets."""

    id: int
    chatkit_domain_key: str | None
    has_google_maps_api_key: bool
    phone_provider_enabled: bool
    phone_provider_recording_deletion_enabled: bool
    phone_provider_base_url: str | None
    has_phone_provider_username: bool
    has_phone_provider_password: bool
    phone_provider_account_code: str | None
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_has_google_maps_api_key(obj: IntegrationSettings) -> bool:
        """Report whether a key is stored (the value never leaves the server)."""
        return obj.google_maps_api_key is not None

    @staticmethod
    def resolve_has_phone_provider_username(obj: IntegrationSettings) -> bool:
        """Report whether a username is stored (the value never leaves the server)."""
        return obj.phone_provider_username is not None

    @staticmethod
    def resolve_has_phone_provider_password(obj: IntegrationSettings) -> bool:
        """Report whether a password is stored (the value never leaves the server)."""
        return obj.phone_provider_password is not None


class IntegrationSettingsPatchIn(Schema):
    """Partial update: omitted fields keep their stored value, ``null`` clears."""

    chatkit_domain_key: NullableText = omittable(None)
    google_maps_api_key: NullableText = omittable(None)
    phone_provider_enabled: bool = omittable(False)
    phone_provider_recording_deletion_enabled: bool = omittable(False)
    phone_provider_base_url: NullableText = omittable(None)
    phone_provider_username: NullableText = omittable(None)
    phone_provider_password: NullableText = omittable(None)
    phone_provider_account_code: NullableText = omittable(None)


@router.get(
    "/integration-settings/",
    auth=SuperuserCookieJWTAuth(),
    operation_id="integration_settings_retrieve",
    response=IntegrationSettingsOut,
    summary="Read the integration settings singleton",
    tags=["integration-settings"],
)
def integration_settings_retrieve(request: HttpRequest) -> IntegrationSettings:
    """Return the singleton; secrets appear only as has_* booleans."""
    return IntegrationSettings.get_solo()


@router.patch(
    "/integration-settings/",
    auth=SuperuserCookieJWTAuth(),
    operation_id="integration_settings_partial_update",
    response=IntegrationSettingsOut,
    summary="Update some of the integration settings",
    tags=["integration-settings"],
)
def integration_settings_partial_update(
    request: HttpRequest, payload: IntegrationSettingsPatchIn
) -> IntegrationSettings:
    """Apply only the fields the caller sent.

    Fable: same discipline as company defaults — presence comes from the
    payload, so a settings screen can submit one section without touching the
    others, and an omitted secret is left exactly as stored.
    """
    supplied = payload.model_dump(exclude_unset=True)
    if not supplied:
        return IntegrationSettings.get_solo()
    # Fable: the row lock keeps two concurrent PATCHes from interleaving their
    # read-modify-write on the same singleton; CompanyDefaults accepts
    # last-write-wins instead (its ruling at company_defaults_partial_update),
    # and a credential row is where a lost write is least acceptable.
    with transaction.atomic():
        instance = IntegrationSettings.objects.select_for_update().filter(pk=1).first()
        if instance is None:
            instance = IntegrationSettings.get_solo()  # raises: the row is missing
        for field, value in supplied.items():
            setattr(instance, field, value)
        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            raise HttpError(400, "; ".join(exc.messages)) from exc
        instance.save(update_fields=[*supplied, "updated_at"])
    return instance
