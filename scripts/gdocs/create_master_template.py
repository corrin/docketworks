"""Create/manage the master Google Sheets quote template.

Uploads quote_template.xlsx as a Google Sheet into a 'Templates' folder in the
service account's own Drive (creating the folder if absent), after showing any
existing quote templates and asking before creating a duplicate. The resulting
sheet id is what CompanyDefaults.master_quote_template_id points at.

Runs as the raw service account (no Workspace impersonation) because the
template lives in the service account's My Drive, not the company Shared Drive.
Failures crash: a Drive error here has no business context to persist and
nothing downstream can proceed without the template (ADR 0015).

Usage (from a directory containing quote_template.xlsx):
    GCP_CREDENTIALS=<key.json> uv run python -m scripts.gdocs.create_master_template
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from googleapiclient.http import MediaFileUpload

from scripts.gdocs.gauth import build_service_account_drive

if TYPE_CHECKING:
    from googleapiclient._apis.drive.v3.resources import DriveResource
    from googleapiclient._apis.drive.v3.schemas import File

TEMPLATE_NAME = "Quote Spreadsheet Template 2025 - Master"
SOURCE_FILE = Path("quote_template.xlsx")
INFO_FILE = Path("template_info.json")
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"


def find_or_create_templates_folder(drive: DriveResource) -> File:
    """Return the 'Templates' folder in the Drive root, creating it if absent."""
    query = f"name='Templates' and mimeType='{FOLDER_MIME}' and trashed=false"
    folders = (
        drive.files()
        .list(q=query, fields="files(id, name, webViewLink)")
        .execute()
        .get("files", [])
    )
    if folders:
        folder = folders[0]
        print(f"Templates folder found: {folder['name']}")
        print(f"   ID: {folder['id']}")
        print(f"   Link: {folder.get('webViewLink', 'N/A')}")
        return folder

    print("Creating 'Templates' folder...")
    folder = (
        drive.files()
        .create(
            body={"name": "Templates", "mimeType": FOLDER_MIME, "parents": ["root"]},
            fields="id, name, webViewLink",
        )
        .execute()
    )
    print(f"Templates folder created: {folder['name']}")
    print(f"   ID: {folder['id']}")
    print(f"   Link: {folder.get('webViewLink', 'N/A')}")
    return folder


def search_existing_templates(drive: DriveResource, name_fragment: str) -> list[File]:
    """List existing spreadsheets whose name contains name_fragment."""
    query = f"name contains '{name_fragment}' and mimeType='{SHEET_MIME}' and trashed=false"
    templates = (
        drive.files()
        .list(q=query, fields="files(id, name, webViewLink, createdTime, modifiedTime)")
        .execute()
        .get("files", [])
    )
    if templates:
        print(f"Templates found with '{name_fragment}':")
        for template in templates:
            print(f"   Name: {template['name']}")
            print(f"   ID: {template['id']}")
            print(f"   Link: {template.get('webViewLink', 'N/A')}")
            print(f"   Created: {template.get('createdTime', 'N/A')}")
            print(f"   Modified: {template.get('modifiedTime', 'N/A')}")
            print("-" * 50)
    return templates


def create_template(drive: DriveResource, folder_id: str, name: str, source: Path) -> File:
    """Upload the xlsx as a Google Sheet named `name` inside `folder_id`."""
    print(f"Uploading template '{name}'...")
    media = MediaFileUpload(str(source), mimetype=XLSX_MIME, resumable=True)
    created = (
        drive.files()
        .create(
            body={"name": name, "mimeType": SHEET_MIME, "parents": [folder_id]},
            media_body=media,
            fields="id, webViewLink, name",
        )
        .execute()
    )
    print("Template created successfully.")
    print(f"   Name: {created['name']}")
    print(f"   ID: {created['id']}")
    print(f"   Link: {created['webViewLink']}")
    return created


def save_template_info(
    new_template: File | None, templates_folder: File, existing_templates: list[File]
) -> None:
    """Record what exists / what was created so the run leaves an audit file."""
    info = {
        "timestamp": datetime.now(UTC).isoformat(),
        "templates_folder": {
            "id": templates_folder.get("id"),
            "name": templates_folder.get("name"),
            "link": templates_folder.get("webViewLink"),
        },
        "new_template": new_template,
        "existing_templates": existing_templates,
    }
    INFO_FILE.write_text(json.dumps(info, indent=2, ensure_ascii=False))
    print(f"Information saved in '{INFO_FILE}'")


def main() -> None:
    """Find/create the Templates folder, then upload the master quote template."""
    print("Google Sheets Template Manager")
    print("=" * 60)

    if not SOURCE_FILE.exists():
        raise RuntimeError(f"Source file not found: {SOURCE_FILE.resolve()}")

    drive = build_service_account_drive()
    templates_folder = find_or_create_templates_folder(drive)

    print("\nSearching for existing templates...")
    existing_templates = search_existing_templates(drive, "Quote")

    if existing_templates:
        response = input(
            f"\n{len(existing_templates)} existing templates found. Create new anyway? (y/n): "
        )
        if response.lower() != "y":
            print("Operation cancelled by user.")
            save_template_info(None, templates_folder, existing_templates)
            return

    print("\nCreating new template...")
    new_template = create_template(drive, templates_folder["id"], TEMPLATE_NAME, SOURCE_FILE)
    save_template_info(new_template, templates_folder, existing_templates)

    print("\n" + "=" * 60)
    print("OPERATION SUMMARY")
    print(f"Templates Folder: {templates_folder['id']}")
    print(f"New Template: {new_template['id']}")
    print(f"Template Link: {new_template['webViewLink']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
