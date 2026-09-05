"""Google service-account credentials for the whole codebase.

One credential builder (ADR 0039) — v1 carried a near-identical copy in every
script, and the Docs/Drive authoring scripts under ``scripts/gdocs/`` now
import these from here. Moved out of ``scripts/`` when the password-reset
email gave application code its first Google call (Gmail send,
``apps/core/gmail.py``); apps must never import from ``scripts``.

The service-account key file comes from the ``GCP_CREDENTIALS`` env var.
Callers that act on Workspace data (Shared Drive, Gmail) must impersonate a
real Workspace user via domain-wide delegation — raw service-account
credentials see only the service account's own empty world. The impersonated
subject is ``GCP_DELEGATED_SUBJECT`` when set, otherwise
``CompanyDefaults.company_email`` — the per-instance Workspace user delegation
acts as. The env override exists for a dev box pointed at a client's
Workspace: the dev DB's ``company_email`` is a demo placeholder, not a real
Workspace user. Key and subject both fail loud when missing (ADR 0015).
Domain-wide delegation matches scope strings literally.
"""

import os
from pathlib import Path

from google.oauth2 import service_account


def service_account_credentials(scopes: list[str]) -> service_account.Credentials:
    """Raw service-account credentials (no impersonation) for the given scopes."""
    key_file = os.environ.get("GCP_CREDENTIALS")
    if not key_file:
        raise RuntimeError("GCP_CREDENTIALS environment variable not set")
    if not Path(key_file).exists():
        raise RuntimeError(f"Google service account key file not found: {key_file}")
    return service_account.Credentials.from_service_account_file(key_file, scopes=scopes)


def delegated_subject() -> str:
    """Resolve the Workspace user domain-wide delegation impersonates here.

    The caller must have run ``django.setup()`` first: the subject falls back
    from ``GCP_DELEGATED_SUBJECT`` to ``CompanyDefaults.company_email``.
    """
    # Imported here, not at module top, so Django-free scripts (get_gapi_token,
    # create_master_template) can import this module without a configured
    # Django and a database.
    from apps.core.models import CompanyDefaults  # noqa: PLC0415

    subject = os.environ.get("GCP_DELEGATED_SUBJECT") or CompanyDefaults.get_solo().company_email
    if not subject:
        raise RuntimeError(
            "No impersonation subject: set GCP_DELEGATED_SUBJECT or populate "
            "CompanyDefaults.company_email in Settings. Google Workspace "
            "domain-wide delegation needs a real Workspace user to impersonate."
        )
    return subject


def delegated_credentials(
    scopes: list[str], subject: str | None = None
) -> service_account.Credentials:
    """Credentials impersonating ``subject``, or the resolved Workspace subject.

    An explicit subject is how work is done AS a particular person rather than
    as the company: a draft belongs in the mailbox of whoever will send it, and
    they can only be looking at the screen that made it because they signed in
    with that Workspace address.
    """
    return service_account_credentials(scopes).with_subject(subject or delegated_subject())
