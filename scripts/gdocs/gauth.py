"""Client builders shared by the Google Docs/Drive authoring scripts.

The credential builders live in ``apps/platform/integrations/google/credentials.py``
(ADR 0039: scripts consume the application's adapter, never the reverse).
This module keeps the Drive/Docs client constructors and scope constants the
authoring toolchain shares.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from googleapiclient.discovery import build

from apps.platform.integrations.google.credentials import (
    delegated_credentials,
    delegated_subject,
    service_account_credentials,
)

if TYPE_CHECKING:
    from google.oauth2 import service_account
    from googleapiclient._apis.docs.v1.resources import DocsResource
    from googleapiclient._apis.drive.v3.resources import DriveResource

__all__ = [
    "DOCS_SCOPE",
    "DRIVE_SCOPE",
    "SHEETS_SCOPE",
    "build_delegated_drive",
    "build_delegated_drive_and_docs",
    "build_drive",
    "build_service_account_drive",
]

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
DOCS_SCOPE = "https://www.googleapis.com/auth/documents"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


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
    from apps.core.models import CompanyDefaults

    return build_drive(
        delegated_credentials(
            [DRIVE_SCOPE], delegated_subject(CompanyDefaults.get_solo().company_email)
        )
    )


def build_delegated_drive_and_docs() -> tuple[DriveResource, DocsResource]:
    """Drive + Docs client pair sharing one set of delegated credentials."""
    from apps.core.models import CompanyDefaults

    creds = delegated_credentials(
        [DRIVE_SCOPE, DOCS_SCOPE], delegated_subject(CompanyDefaults.get_solo().company_email)
    )
    return build_drive(creds), build("docs", "v1", credentials=creds)
