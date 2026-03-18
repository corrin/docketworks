"""
Smart script to create/manage Google Sheets templates.
Searches for existing templates and creates new ones if necessary.
"""

import json
import os
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_drive_service():
    """Initializes the Google Drive service."""
    key_file = os.getenv("GCP_CREDENTIALS")
    if not key_file:
        raise RuntimeError("GCP_CREDENTIALS environment variable not set")
    if not os.path.exists(key_file):
        raise RuntimeError(f"Google service account key file not found: {key_file}")
    creds = service_account.Credentials.from_service_account_file(
        key_file, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def find_or_create_templates_folder(service):
    """Searches for or creates the 'Templates' folder in the root of the drive."""
    try:
        # Search for existing Templates folder
        query = "name='Templates' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = (
            service.files()
            .list(q=query, fields="files(id, name, webViewLink)")
            .execute()
        )

        folders = results.get("files", [])

        if folders:
            folder = folders[0]
            print(f"📁 Templates folder found: {folder['name']}")
            print(f"   ID: {folder['id']}")
            print(f"   Link: {folder.get('webViewLink', 'N/A')}")
            return folder

        # Create Templates folder if it doesn't exist
        print("📁 Creating 'Templates' folder...")
        folder_metadata = {
            "name": "Templates",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": ["root"],
        }

        folder = (
            service.files()
            .create(body=folder_metadata, fields="id, name, webViewLink")
            .execute()
        )

        print(f"✅ Templates folder created: {folder['name']}")
        print(f"   ID: {folder['id']}")
        print(f"   Link: {folder.get('webViewLink', 'N/A')}")
        return folder

    except Exception as e:
        print(f"❌ Error searching/creating Templates folder: {e}")
        return None


def search_existing_template(service, template_name):
    """Searches for existing template by name."""
    try:
        query = f"name contains '{template_name}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"

        results = (
            service.files()
            .list(
                q=query,
                fields="files(id, name, webViewLink, createdTime, modifiedTime)",
            )
            .execute()
        )

        templates = results.get("files", [])

        if templates:
            print(f"📋 Templates found with '{template_name}':")
            for template in templates:
                print(f"   Name: {template['name']}")
                print(f"   ID: {template['id']}")
                print(f"   Link: {template.get('webViewLink', 'N/A')}")
                print(f"   Created: {template.get('createdTime', 'N/A')}")
                print(f"   Modified: {template.get('modifiedTime', 'N/A')}")
                print("-" * 50)

        return templates

    except Exception as e:
        print(f"❌ Error searching for templates: {e}")
        return []


def create_template(service, folder_id, template_name, source_file_path):
    """Creates a new template in Google Sheets."""
    try:
        print(f"📤 Uploading template '{template_name}'...")

        file_metadata = {
            "name": template_name,
            "mimeType": "application/vnd.google-apps.spreadsheet",
            "parents": [folder_id],
        }

        media = MediaFileUpload(
            source_file_path,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            resumable=True,
        )

        file = (
            service.files()
            .create(
                body=file_metadata, media_body=media, fields="id, webViewLink, name"
            )
            .execute()
        )

        print("✅ Template created successfully!")
        print(f"   Name: {file.get('name')}")
        print(f"   ID: {file.get('id')}")
        print(f"   Link: {file.get('webViewLink')}")

        return file

    except Exception as e:
        print(f"❌ Error creating template: {e}")
        return None


def save_template_info(template_data, templates_folder, existing_templates):
    """Saves template information to a JSON file."""
    try:
        template_info = {
            "timestamp": datetime.now().isoformat(),
            "templates_folder": {
                "id": templates_folder.get("id"),
                "name": templates_folder.get("name"),
                "link": templates_folder.get("webViewLink"),
            },
            "new_template": template_data,
            "existing_templates": existing_templates,
        }

        info_file = "template_info.json"
        with open(info_file, "w", encoding="utf-8") as f:
            json.dump(template_info, f, indent=2, ensure_ascii=False)

        print(f"💾 Information saved in '{info_file}'")

    except Exception as e:
        print(f"❌ Error saving information: {e}")


def main():
    """Main function."""
    print("🚀 Google Sheets Template Manager")
    print("=" * 60)

    # Settings
    template_name = "Quote Spreadsheet Template 2025 - Master"
    source_file = "quote_template.xlsx"

    # Check if source file exists
    if not os.path.exists(source_file):
        print(f"❌ Source file not found: {source_file}")
        return

    service = get_drive_service()

    # 1. Search/create Templates folder
    templates_folder = find_or_create_templates_folder(service)
    if not templates_folder:
        return

    # 2. Search for existing templates
    print("\n🔍 Searching for existing templates...")
    existing_templates = search_existing_template(service, "Quote")

    # 3. Ask if should create new template if there are existing ones
    if existing_templates:
        response = input(
            f"\n❓ {len(existing_templates)} existing templates found. Create new anyway? (y/n): "
        )
        if response.lower() != "y":
            print("⏹️  Operation cancelled by user.")
            save_template_info(None, templates_folder, existing_templates)
            return

    # 4. Create new template
    print("\n📋 Creating new template...")
    new_template = create_template(
        service, templates_folder["id"], template_name, source_file
    )

    if new_template:
        # 5. Save information
        save_template_info(new_template, templates_folder, existing_templates)

        print("\n" + "=" * 60)
        print("✅ OPERATION SUMMARY")
        print(f"📁 Templates Folder: {templates_folder['id']}")
        print(f"📋 New Template: {new_template['id']}")
        print(f"🔗 Template Link: {new_template['webViewLink']}")
        print("=" * 60)


if __name__ == "__main__":
    main()
