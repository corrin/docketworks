"""Browse the MSM Google Drive layout (Shared Drives included).

Read-only. Prints the Shared Drives visible to the delegated user and, when
given a driveId, walks that drive's folder/file tree.

The content we care about (the Operations Manual) lives in a Shared Drive, not
in anyone's My Drive, so this must impersonate a real Workspace user and pass
the Shared-Drive flags on every call — raw service-account creds see only the
service account's empty My Drive, and `root`/`about` never expose Shared Drives.

Auth follows the app convention (apps/job/importers/google_sheets.py): the
service-account key comes from the GCP_CREDENTIALS env var and the impersonated
subject defaults to CompanyDefaults.company_email — the per-instance Workspace
user domain-wide delegation acts as. Set GCP_DELEGATED_SUBJECT to override the
subject when pointing at a Drive whose real user differs from this instance's
company_email (e.g. a dev box browsing a client's Shared Drive — the dev DB's
company_email is a demo placeholder that is not a real Workspace user). Both the
key and the resolved subject fail loud if missing. Domain-wide delegation matches
scope strings literally.

Usage:
    GCP_CREDENTIALS=<key.json> python scripts/explore_google_drive.py
    GCP_CREDENTIALS=<key.json> python scripts/explore_google_drive.py <driveId>
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from google.oauth2 import service_account
from googleapiclient.discovery import build

from apps.workflow.models import CompanyDefaults

SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME = "application/vnd.google-apps.folder"


def build_drive():
    """Authenticated Drive client, impersonating CompanyDefaults.company_email."""
    key_file = os.getenv("GCP_CREDENTIALS")
    if not key_file:
        raise RuntimeError("GCP_CREDENTIALS environment variable not set")
    if not os.path.exists(key_file):
        raise RuntimeError(f"Google service account key file not found: {key_file}")
    subject = (
        os.getenv("GCP_DELEGATED_SUBJECT") or CompanyDefaults.get_solo().company_email
    )
    if not subject:
        raise RuntimeError(
            "No impersonation subject: set GCP_DELEGATED_SUBJECT or populate "
            "CompanyDefaults.company_email in Settings. Google Workspace "
            "domain-wide delegation needs a real Workspace user to impersonate."
        )
    creds = service_account.Credentials.from_service_account_file(
        key_file, scopes=SCOPES
    ).with_subject(subject)
    return build("drive", "v3", credentials=creds)


drive = build_drive()


def list_shared_drives() -> None:
    """Print every Shared Drive the delegated user can see."""
    print("=== SHARED DRIVES ===")
    token = None
    while True:
        resp = (
            drive.drives()
            .list(
                pageSize=100, fields="nextPageToken, drives(id, name)", pageToken=token
            )
            .execute()
        )
        for d in resp.get("drives", []):
            print(f"{d['name']}\t{d['id']}")
        token = resp.get("nextPageToken")
        if not token:
            break
    print("\nRun again with a driveId to walk that drive's tree.")


def children(parent_id: str, drive_id: str) -> list:
    """All non-trashed children of parent_id within a Shared Drive, paged."""
    items = []
    token = None
    while True:
        resp = (
            drive.files()
            .list(
                q=f"'{parent_id}' in parents and trashed = false",
                corpora="drive",
                driveId=drive_id,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                pageSize=1000,
                fields="nextPageToken, files(id, name, mimeType)",
                orderBy="folder,name",
                pageToken=token,
            )
            .execute()
        )
        items.extend(resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            break
    return items


def walk(parent_id: str, drive_id: str, depth: int) -> None:
    """Print an indented tree of parent_id's descendants."""
    for item in children(parent_id, drive_id):
        indent = "  " * depth
        is_folder = item["mimeType"] == FOLDER_MIME
        marker = "📁" if is_folder else "  "
        print(f"{indent}{marker} {item['name']}\t{item['id']}\t{item['mimeType']}")
        if is_folder:
            walk(item["id"], drive_id, depth + 1)


def walk_drive(drive_id: str) -> None:
    meta = drive.drives().get(driveId=drive_id, fields="id, name").execute()
    print(f"=== {meta['name']} ({drive_id}) ===")
    walk(drive_id, drive_id, 0)


def main() -> None:
    if len(sys.argv) > 1:
        walk_drive(sys.argv[1])
    else:
        list_shared_drives()


if __name__ == "__main__":
    main()
