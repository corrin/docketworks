"""Audit the Google service account's own Drive storage.

Prints the storage quota, the largest files, and a file-type breakdown for the
service account's My Drive. A service account has a fixed quota it can never
expand, and every file v1 created *as* the account (rather than impersonating
a Workspace user) counts against it forever — this is how v1's Drive writes
started failing. Run this when Drive writes fail with quota errors, or before
deleting service-account-owned leftovers.

Uses raw service-account credentials on purpose — see
``gauth.build_service_account_drive`` for why delegation would audit the wrong
storage. No Django required.

Usage:
    GCP_CREDENTIALS=<key.json> uv run python -m scripts.gdocs.drive_storage_check
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts.gdocs.gauth import build_service_account_drive

if TYPE_CHECKING:
    from googleapiclient._apis.drive.v3.resources import DriveResource

TOP_FILES = 15


def _gb(raw: str | None) -> float:
    """Drive reports byte counts as decimal strings; absent means zero."""
    if raw is None:
        return 0.0
    return round(int(raw) / 1024**3, 2)


def print_quota(drive: DriveResource) -> None:
    """Print the account's storage quota and how full it is."""
    about = drive.about().get(fields="storageQuota, user").execute()
    quota = about["storageQuota"]

    limit = _gb(quota.get("limit"))
    usage = _gb(quota.get("usage"))
    drive_usage = _gb(quota.get("usageInDrive"))

    print("=== STORAGE QUOTA ===")
    print(f"Total used: {usage} GB")
    print(f"Drive used: {drive_usage} GB")
    if not limit:
        print("Limit: unlimited")
    else:
        percentage = round(usage / limit * 100, 1)
        print(f"Limit: {limit} GB ({percentage}% used)")
        if percentage > 95:
            print("CRITICAL: storage almost full — Drive writes will start failing")
        elif percentage > 80:
            print("WARNING: storage getting full")
        else:
            print("Storage OK")


def print_largest_files(drive: DriveResource) -> None:
    """Print the largest quota-consuming files the account owns."""
    resp = (
        drive.files()
        .list(
            pageSize=50,
            fields="files(id, name, size, mimeType, createdTime)",
            orderBy="quotaBytesUsed desc",
        )
        .execute()
    )
    files = resp.get("files", [])

    print(f"\n=== TOP {min(TOP_FILES, len(files))} LARGEST FILES ===")
    total_bytes = 0
    for i, file in enumerate(files[:TOP_FILES], start=1):
        size = int(file.get("size", "0"))
        total_bytes += size
        size_mb = round(size / 1024**2, 2)
        created = file.get("createdTime", "unknown")[:10]
        name = file.get("name", "(unnamed)")
        if len(name) > 40:
            name = name[:37] + "..."
        print(f"{i:2}. {name:40} {size_mb:8.2f} MB  {created}  {file.get('id', '')}")
    print(f"Top {TOP_FILES} files total: {round(total_bytes / 1024**2, 2)} MB")


def print_type_breakdown(drive: DriveResource) -> None:
    """Print file counts by simplified mime type."""
    resp = drive.files().list(pageSize=1000, fields="files(mimeType)").execute()
    files = resp.get("files", [])

    type_counts: dict[str, int] = {}
    for file in files:
        mime_type = file.get("mimeType", "unknown")
        if "folder" in mime_type:
            file_type = "Folders"
        elif "spreadsheet" in mime_type:
            file_type = "Spreadsheets"
        elif "document" in mime_type:
            file_type = "Documents"
        elif "presentation" in mime_type:
            file_type = "Presentations"
        else:
            file_type = "Other"
        type_counts[file_type] = type_counts.get(file_type, 0) + 1

    print("\n=== FILE COUNTS BY TYPE ===")
    for file_type, count in sorted(type_counts.items()):
        print(f"{file_type:15}: {count:4} files")
    print(f"Total files: {len(files)}")


def main() -> None:
    drive = build_service_account_drive()
    print_quota(drive)
    print_largest_files(drive)
    print_type_breakdown(drive)


if __name__ == "__main__":
    main()
