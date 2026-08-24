"""Core router: the build-id endpoint (v1 ``/api/build-id/``).

The frontend polls this to detect when the backend has been redeployed while a
tab was left open; on mismatch with its own compiled-in build ID it
hard-reloads. Sources, in v1 order: ``DOCKETWORKS_BUILD_SHA`` env var, a
``.release-sha`` file at the repo root, then ``git rev-parse HEAD``.

v1 computed ``settings.BUILD_ID`` at settings import (fail-fast at boot). Here
the read is cached per process instead (same deploy semantics — a gunicorn
restart re-reads — but the first request, not boot, surfaces a bad SHA).
config can call ``read_build_id()`` at startup to restore the fail-fast if
desired.
"""

import os
import re
import shutil
import subprocess
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Literal

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction
from django.http import HttpRequest, HttpResponse
from ninja import File, ModelSchema, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile
from pydantic import ConfigDict, model_validator

from apps.core.auth import CookieJWTAuth, SuperuserCookieJWTAuth
from apps.core.models import CompanyDefaults, IntegrationSettings
from apps.core.schemas import NullableText, derived_response, drop_model_defaults, omittable
from apps.core.settings_metadata import CompanyDefaultsSchemaOut, build_company_defaults_schema
from apps.core.uploads import delete_stored_image, validate_image_upload

router = Router(tags=["build-id"])


class BuildId(Schema):
    """Response body for /api/build-id/: the deployed backend's git SHA."""

    build_id: str


def _validate_sha(value: str, source: str) -> str:
    """Return value as a 40-char hex git SHA, or fail fast.

    Every build-id source is a full git SHA; a malformed value would propagate
    into /api/build-id/ and silently break the frontend version-check reload, so
    validate upfront and crash rather than serve a bad id.
    """
    sha = value.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ImproperlyConfigured(f"{source} must be a 40-character hex git SHA, got: {value!r}")
    return sha


@lru_cache(maxsize=1)
def read_build_id() -> str:
    """Return the release SHA for this running process."""
    env_sha = os.environ.get("DOCKETWORKS_BUILD_SHA", "").strip()
    if env_sha:
        return _validate_sha(env_sha, "DOCKETWORKS_BUILD_SHA")

    base_dir = Path(settings.BASE_DIR)
    release_sha_file = base_dir / ".release-sha"
    if release_sha_file.exists():
        return _validate_sha(release_sha_file.read_text(), str(release_sha_file))

    git = shutil.which("git")
    if git is None:
        raise ImproperlyConfigured(
            "No DOCKETWORKS_BUILD_SHA, no .release-sha file, and no git executable "
            "on PATH — cannot determine the build id."
        )
    return _validate_sha(
        subprocess.run(  # noqa: S603 -- fixed argv; executable resolved via shutil.which, no user input
            [git, "rev-parse", "HEAD"],
            cwd=base_dir,
            check=True,
            capture_output=True,
            text=True,
        ).stdout,
        "git rev-parse HEAD",
    )


@router.get(
    "/build-id/",
    response=BuildId,
    auth=None,
    url_name="build_id",
    operation_id="build_id_retrieve",
)
def build_id_retrieve(request: HttpRequest, response: HttpResponse) -> BuildId:
    """Return the git SHA of the running backend process."""
    # "BUILD_ID_DISABLED" is the feature-disabled sentinel. Real SHAs are
    # 40 hex chars so this cannot collide. The frontend matches on this
    # exact string and skips the reload flow.
    # SKIP_VERSION_CHECK is defined by config once its env plumbing lands;
    # absent means the check is on (v1 required the env var explicitly).
    skip_version_check = bool(getattr(settings, "SKIP_VERSION_CHECK", False))
    build_id = "BUILD_ID_DISABLED" if skip_version_check else read_build_id()
    response["Cache-Control"] = "no-store"
    return BuildId(build_id=build_id)


# ── Company defaults ─────────────────────────────────────────────────────
#
# The singleton the whole app reads: markups, GST, wage rate, Xero terms, the
# company logo. The SPA loads it into a store on boot and JobViewTabs renders
# JobEstimateTab only when it is present, so the entire job cluster is dark
# without this endpoint — it blocks far more than its own settings screen.


class CompanyDefaultsOut(ModelSchema):
    """Every stored default, plus the two derived logo URLs.

    Derived from the model rather than hand-listed. 67 fields transcribed by
    hand is 67 chances to disagree with the column, and the disagreement would
    only surface as a runtime validation failure in the SPA.

    The image fields themselves are excluded: they are write-only in the
    contract, and a client wants a URL it can put in an <img>, not a storage
    path it cannot resolve.
    """

    logo_url: str | None = None
    logo_wide_url: str | None = None

    model_config = ConfigDict(json_schema_extra=derived_response)

    class Meta:
        model = CompanyDefaults
        exclude: ClassVar[list[str]] = ["logo", "logo_wide"]

    @staticmethod
    def resolve_logo_url(obj: CompanyDefaults) -> str | None:
        """Return the square logo's URL, or None when none is uploaded."""
        return _logo_url(obj, "logo")

    @staticmethod
    def resolve_logo_wide_url(obj: CompanyDefaults) -> str | None:
        """Return the wide logo's URL, or None when none is uploaded."""
        return _logo_url(obj, "logo_wide")


def _nullable_text_field_names() -> frozenset[str]:
    return frozenset(
        field.name
        for field in CompanyDefaults._meta.get_fields()
        if isinstance(field, models.CharField | models.TextField) and field.null
    )


_NULLABLE_TEXT_FIELDS = _nullable_text_field_names()


class CompanyDefaultsPatchIn(ModelSchema):
    """Partial update: every field optional, presence read from the payload."""

    model_config = ConfigDict(json_schema_extra=drop_model_defaults)

    class Meta:
        model = CompanyDefaults
        # created_at/updated_at are auto-managed; without this exclusion the
        # setattr loop would happily rewrite created_at on update.
        exclude: ClassVar[list[str]] = ["id", "logo", "logo_wide", "created_at", "updated_at"]
        fields_optional = "__all__"

    @model_validator(mode="after")
    def _blank_is_not_a_value(self) -> "CompanyDefaultsPatchIn":
        # ADR 0040: nullable text columns never store ""; null is how a client
        # clears a value. Enforced generically rather than via NullableText per
        # field because this schema is derived with fields_optional="__all__".
        for name in self.model_fields_set & _NULLABLE_TEXT_FIELDS:
            if getattr(self, name) == "":
                raise ValueError(f"{name}: blank is not a value; send null to clear")
        return self


def _logo_url(instance: CompanyDefaults, field_name: str) -> str | None:
    """Build the logo path relative to the site root, or None when unset.

    Relative on purpose. The browser resolves it against its own origin, so one
    stored value is correct behind ngrok in dev and behind the proxy in
    production. An absolute URL built from the request leaks the internal host
    wherever forwarded-host headers are not trusted, and the browser then
    refuses to load the image.
    """
    field_file = getattr(instance, field_name, None)
    if not field_file:
        return None
    return str(field_file.url)


@router.get(
    "/company-defaults/",
    auth=CookieJWTAuth(),
    operation_id="company_defaults_retrieve",
    response=CompanyDefaultsOut,
    summary="Read the company defaults singleton",
    tags=["company-defaults"],
)
def company_defaults_retrieve(request: HttpRequest) -> CompanyDefaults:
    """Return the singleton."""
    return CompanyDefaults.get_solo()


# Opus: superuser, not office staff — this PATCH sets wage rates, markups, GST and
# Xero identity; v1's effective gate was the superuser /admin route guard, and the
# admin nav + leave-settings use the same class. GET stays any-staff: company
# defaults is app-shell boot data for every user.
# Opus: If-Match rejected here — ADR 0003 scopes optimistic concurrency to Job/PO;
# the dirty-fields-only payload (exclude_unset) means concurrent editors of
# different fields never clobber each other, and same-field conflict on a
# rarely-edited singleton is accepted last-write-wins (ruling in
# docs/rewrite-history.md, 2026-08-22).
@router.patch(
    "/company-defaults/",
    auth=SuperuserCookieJWTAuth(),
    operation_id="company_defaults_partial_update",
    response=CompanyDefaultsOut,
    summary="Update some of the company defaults",
    tags=["company-defaults"],
)
def company_defaults_partial_update(
    request: HttpRequest, payload: CompanyDefaultsPatchIn
) -> CompanyDefaults:
    """Apply only the fields the caller sent.

    Presence comes from ``model_fields_set``, so omitting a field leaves the
    stored value alone — the whole point of a settings screen that submits one
    section at a time.
    """
    instance = CompanyDefaults.get_solo()
    # by_alias=True: ninja's ModelSchema names the FK's pydantic attribute
    # ``shop_company`` (alias ``shop_company_id``, the wire key). Dumping by
    # attribute name would yield {"shop_company": <uuid>}, and setattr on a
    # Django FK descriptor with a raw UUID (not a model instance) raises
    # ValueError before full_clean ever runs — a 500 for a legal payload.
    # Dumping by alias yields {"shop_company_id": <uuid>}, a real attname
    # setattr and update_fields both accept; every other field's alias equals
    # its attribute name, so this is a no-op for them. model_fields_set (used
    # by _blank_is_not_a_value above) is keyed by attribute name regardless of
    # by_alias, so that validator is unaffected.
    supplied = payload.model_dump(exclude_unset=True, by_alias=True)
    if not supplied:
        # An empty PATCH body has nothing to apply; save(update_fields=None)
        # would fall back to a full-row write for zero benefit.
        return instance
    for field, value in supplied.items():
        setattr(instance, field, value)
    try:
        instance.full_clean()
    except DjangoValidationError as exc:
        # Converted rather than left to escape: an unhandled model
        # ValidationError is a 500, and a rejected settings value is the
        # caller's to fix. NOTE: four apps carry a private copy of this
        # flattening (job, purchasing, timesheet, company); it belongs in
        # apps/core beside the envelope, and consolidating it is its own change.
        raise HttpError(400, "; ".join(exc.messages)) from exc
    instance.save(update_fields=[*supplied, "updated_at"])
    return instance


@router.get(
    "/company-defaults/schema/",
    auth=CookieJWTAuth(),
    operation_id="company_defaults_schema_retrieve",
    response=CompanyDefaultsSchemaOut,
    summary="Describe the company defaults as sections for the settings screen",
    tags=["company-defaults"],
)
def company_defaults_schema_retrieve(request: HttpRequest) -> CompanyDefaultsSchemaOut:
    """Serve the section/field registry the settings screen renders from."""
    return build_company_defaults_schema()


# ── Company logo upload/delete ───────────────────────────────────────────
#
# Opus: Field name in the path, not the multipart body (v1 put it in the body and
# fetched raw, because "Zodios can't multipart") — so hey-api generates a
# typed multipart client here too (precedent: uploadJobFiles, apps/job/api.py).

LogoFieldName = Literal["logo", "logo_wide"]


@router.post(
    "/company-defaults/logo/{field_name}/",
    auth=SuperuserCookieJWTAuth(),
    operation_id="company_defaults_logo_update",
    response=CompanyDefaultsOut,
    summary="Upload a company logo",
    tags=["company-defaults"],
)
def company_defaults_logo_update(
    request: HttpRequest, field_name: LogoFieldName, file: File[UploadedFile]
) -> CompanyDefaults:
    """Save the uploaded file and delete the file it replaces."""
    validate_image_upload(file, label="Logo")
    instance = CompanyDefaults.get_solo()
    # Opus: save the new file before unlinking the old one — a save failure
    # (full_clean, disk-full, whatever) must not leave the row pointing at a file
    # that no longer exists. ``replaced`` is captured before setattr rebinds the
    # descriptor, so it still names the pre-upload file.
    replaced = getattr(instance, field_name)
    setattr(instance, field_name, file)
    instance.save(update_fields=[field_name, "updated_at"])
    delete_stored_image(replaced, allowed_prefix="company_logos")
    return instance


@router.delete(
    "/company-defaults/logo/{field_name}/",
    auth=SuperuserCookieJWTAuth(),
    operation_id="company_defaults_logo_destroy",
    response=CompanyDefaultsOut,
    summary="Remove a company logo",
    tags=["company-defaults"],
)
def company_defaults_logo_destroy(
    request: HttpRequest, field_name: LogoFieldName
) -> CompanyDefaults:
    """Clear the named logo field and delete the stored file."""
    instance = CompanyDefaults.get_solo()
    # Opus: clear + save before unlinking, mirroring the upload endpoint above —
    # a save failure must not leave the file deleted while the row still points
    # at it. ``removed`` is captured before setattr clears the descriptor, so it
    # still names the file to delete once the row is safely persisted.
    removed = getattr(instance, field_name)
    setattr(instance, field_name, None)
    instance.save(update_fields=[field_name, "updated_at"])
    delete_stored_image(removed, allowed_prefix="company_logos")
    return instance


# ---------------------------------------------------------------------------
# Integration settings (ADR 0053)
#
# The credentials the install uses to reach external services. Superuser on
# both verbs: nothing in the app shell reads this, and the non-secret columns
# (a portal URL, an account code) are still configuration nobody else needs.
# Secrets never leave the server — the response carries ``has_*`` booleans and
# the request accepts a value to set or ``null`` to clear.


class IntegrationSettingsOut(Schema):
    """Every non-secret column, plus presence flags for the secrets."""

    id: int
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
