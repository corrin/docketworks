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
from functools import lru_cache
from pathlib import Path
from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpRequest, HttpResponse
from ninja import ModelSchema, Router, Schema
from ninja.errors import HttpError

from apps.core.auth import CookieJWTAuth
from apps.core.models import CompanyDefaults

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


class CompanyDefaultsPatchIn(ModelSchema):
    """Partial update: every field optional, presence read from the payload."""

    class Meta:
        model = CompanyDefaults
        exclude: ClassVar[list[str]] = ["id", "logo", "logo_wide"]
        fields_optional = "__all__"


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


def _company_defaults() -> CompanyDefaults:
    """Return the singleton, or an error saying why it is not there.

    Deliberately not ``get_solo()``, which CREATES the row when missing —
    ``shop_company`` is NOT NULL with no default, so that create dies with an
    IntegrityError naming a column instead of the problem. The row arrives with
    the data restore; its absence means the install was never seeded, which is
    an operator action, not something a request can fix (ADR 0038).
    """
    defaults = CompanyDefaults.objects.first()
    if defaults is None:
        raise HttpError(
            500,
            "Company defaults have not been created. They come from the v1 data "
            "restore; on a fresh install create the row with a shop_company set.",
        )
    return defaults


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
    return _company_defaults()


@router.patch(
    "/company-defaults/",
    auth=CookieJWTAuth(),
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
    instance = _company_defaults()
    supplied = payload.model_dump(exclude_unset=True)
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
    instance.save(update_fields=[*supplied, "updated_at"] if supplied else None)
    return instance
