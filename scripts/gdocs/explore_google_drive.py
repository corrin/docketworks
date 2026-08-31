"""Browse the company Google Drive layout (Shared Drives included).

Read-only. Prints the Shared Drives visible to the delegated user and, when
given a driveId, walks that drive's folder/file tree.

The content we care about (the Operations Manual) lives in a Shared Drive, not
in anyone's My Drive, so every call passes the Shared-Drive flags and the
client impersonates a real Workspace user (see apps/core/gauth.py for the
credential and subject rules).

Usage:
    GCP_CREDENTIALS=<key.json> uv run python -m scripts.gdocs.explore_google_drive
    GCP_CREDENTIALS=<key.json> uv run python -m scripts.gdocs.explore_google_drive <driveId>
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from scripts.gdocs.gauth import build_delegated_drive  # noqa: E402

if TYPE_CHECKING:
    from googleapiclient._apis.drive.v3.resources import DriveResource
    from googleapiclient._apis.drive.v3.schemas import File

FOLDER_MIME = "application/vnd.google-apps.folder"


def list_shared_drives(drive: DriveResource) -> None:
    """Print every Shared Drive the delegated user can see."""
    print("=== SHARED DRIVES ===")
    token: str | None = None
    while True:
        resp = (
            drive.drives()
            .list(pageSize=100, fields="nextPageToken, drives(id, name)", pageToken=token)
            .execute()
        )
        for d in resp.get("drives", []):
            print(f"{d['name']}\t{d['id']}")
        token = resp.get("nextPageToken")
        if not token:
            break
    print("\nRun again with a driveId to walk that drive's tree.")


def children(drive: DriveResource, parent_id: str, drive_id: str) -> list[File]:
    """All non-trashed children of parent_id within a Shared Drive, paged."""
    items: list[File] = []
    token: str | None = None
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


def walk(drive: DriveResource, parent_id: str, drive_id: str, depth: int) -> None:
    """Print an indented tree of parent_id's descendants."""
    for item in children(drive, parent_id, drive_id):
        indent = "  " * depth
        is_folder = item["mimeType"] == FOLDER_MIME
        marker = "dir " if is_folder else "    "
        print(f"{indent}{marker}{item['name']}\t{item['id']}\t{item['mimeType']}")
        if is_folder:
            walk(drive, item["id"], drive_id, depth + 1)


def walk_drive(drive: DriveResource, drive_id: str) -> None:
    """Print the whole tree of one Shared Drive."""
    meta = drive.drives().get(driveId=drive_id, fields="id, name").execute()
    print(f"=== {meta['name']} ({drive_id}) ===")
    walk(drive, drive_id, drive_id, 0)


def main() -> None:
    """Entry point: no args lists Shared Drives, one arg walks that drive."""
    drive = build_delegated_drive()
    if len(sys.argv) > 1:
        walk_drive(drive, sys.argv[1])
    else:
        list_shared_drives(drive)


if __name__ == "__main__":
    main()
