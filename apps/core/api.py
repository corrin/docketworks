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

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse
from ninja import Router, Schema

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
