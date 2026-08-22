"""Service-account auth shared by the Google Docs/Drive authoring scripts.

One credential builder for the whole toolchain (ADR 0039) — v1 carried a
near-identical copy of this in every script.

The service-account key file comes from the ``GCP_CREDENTIALS`` env var.
Scripts that touch the company Shared Drive must impersonate a real Workspace
user via domain-wide delegation — raw service-account credentials see only the
service account's empty My Drive, and ``root``/``about`` never expose Shared
Drives. The impersonated subject is ``GCP_DELEGATED_SUBJECT`` when set,
otherwise ``CompanyDefaults.company_email`` — the per-instance Workspace user
delegation acts as. The env override exists for a dev box pointed at a
client's Shared Drive: the dev DB's ``company_email`` is a demo placeholder,
not a real Workspace user. Key and subject both fail loud when missing
(ADR 0015). Domain-wide delegation matches scope strings literally.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from google.oauth2 import service_account
from googleapiclient.discovery import build

if TYPE_CHECKING:
    from googleapiclient._apis.docs.v1.resources import DocsResource
    from googleapiclient._apis.drive.v3.resources import DriveResource

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
DOCS_SCOPE = "https://www.googleapis.com/auth/documents"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


def service_account_credentials(scopes: list[str]) -> service_account.Credentials:
    """Raw service-account credentials (no impersonation) for the given scopes."""
    key_file = os.environ.get("GCP_CREDENTIALS")
    if not key_file:
        raise RuntimeError("GCP_CREDENTIALS environment variable not set")
    if not Path(key_file).exists():
        raise RuntimeError(f"Google service account key file not found: {key_file}")
    return service_account.Credentials.from_service_account_file(key_file, scopes=scopes)


def delegated_credentials(scopes: list[str]) -> service_account.Credentials:
    """Credentials impersonating the resolved Workspace subject.

    The caller must have run ``django.setup()`` first: the subject falls back
    from ``GCP_DELEGATED_SUBJECT`` to ``CompanyDefaults.company_email``.
    """
    # Imported here, not at module top, so Django-free scripts (get_gapi_token,
    # create_master_template) can import this module without a configured
    # Django and a database.
    from apps.core.models import CompanyDefaults

    subject = os.environ.get("GCP_DELEGATED_SUBJECT") or CompanyDefaults.get_solo().company_email
    if not subject:
        raise RuntimeError(
            "No impersonation subject: set GCP_DELEGATED_SUBJECT or populate "
            "CompanyDefaults.company_email in Settings. Google Workspace "
            "domain-wide delegation needs a real Workspace user to impersonate."
        )
    return service_account_credentials(scopes).with_subject(subject)


def build_drive(credentials: service_account.Credentials) -> DriveResource:
    """The one Drive client constructor (ADR 0039).

    Fable: ``cache_discovery=False`` because the discovery-document cache
    uses ``oauth2client`` when present and logs a warning per client
    otherwise; the probe builds one client per worker thread and would log
    sixteen.
    """
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def build_service_account_drive() -> DriveResource:
    """Drive client as the service account itself (no impersonation).

    Deliberately NOT delegated: this sees only the service account's own My
    Drive, which is exactly the view drive_storage_check needs — files v1
    created as the service account count against its fixed quota, and a
    delegated client would audit the impersonated user's storage instead.
    """
    return build_drive(service_account_credentials([DRIVE_SCOPE]))


def build_delegated_drive() -> DriveResource:
    """Drive client impersonating the resolved Workspace subject."""
    return build_drive(delegated_credentials([DRIVE_SCOPE]))


def build_delegated_drive_and_docs() -> tuple[DriveResource, DocsResource]:
    """Drive + Docs client pair sharing one set of delegated credentials."""
    creds = delegated_credentials([DRIVE_SCOPE, DOCS_SCOPE])
    return build_drive(creds), build("docs", "v1", credentials=creds)
