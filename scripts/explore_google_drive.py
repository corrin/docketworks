"""
Script to explore Google Drive folder structure
and discover the root folder and other useful information.
"""

import json
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_drive_service():
    """Initialise the Google Drive service."""
    key_file = os.getenv("GCP_CREDENTIALS")
    if not key_file:
        raise RuntimeError("GCP_CREDENTIALS environment variable not set")
    if not os.path.exists(key_file):
        raise RuntimeError(f"Google service account key file not found: {key_file}")
    creds = service_account.Credentials.from_service_account_file(
        key_file, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def get_root_folder(service):
    """Get information about the root folder."""
    try:
        # Search for the root folder
        root = (
            service.files()
            .get(fileId="root", fields="id, name, mimeType, webViewLink")
            .execute()
        )
        print("=== ROOT FOLDER ===")
        print(f"ID: {root.get('id')}")
        print(f"Name: {root.get('name')}")
        print(f"Type: {root.get('mimeType')}")
        print(f"Link: {root.get('webViewLink')}")
        print()
        return root.get("id")
    except Exception as e:
        print(f"Error searching for root folder: {e}")
        return None


def list_folders(service, parent_id="root", max_results=50):
    """List folders in a specific directory."""
    try:
        query = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"

        results = (
            service.files()
            .list(
                q=query,
                pageSize=max_results,
                fields="nextPageToken, files(id, name, mimeType, webViewLink, parents)",
            )
            .execute()
        )

        items = results.get("files", [])

        if not items:
            print(f"No folders found in {parent_id}")
            return []

        print(f"=== FOLDERS IN {parent_id} ===")
        for item in items:
            print(f"Name: {item['name']}")
            print(f"ID: {item['id']}")
            print(f"Link: {item.get('webViewLink', 'N/A')}")
            print(f"Parents: {item.get('parents', [])}")
            print("-" * 50)

        return items

    except Exception as e:
        print(f"Error listing folders: {e}")
        return []


def list_files(service, parent_id="root", max_results=20):
    """List files in a specific directory."""
    try:
        query = f"'{parent_id}' in parents and mimeType!='application/vnd.google-apps.folder' and trashed=false"

        results = (
            service.files()
            .list(
                q=query,
                pageSize=max_results,
                fields="nextPageToken, files(id, name, mimeType, webViewLink, parents)",
            )
            .execute()
        )

        items = results.get("files", [])

        if not items:
            print(f"No files found in {parent_id}")
            return []

        print(f"=== FILES IN {parent_id} ===")
        for item in items:
            print(f"Name: {item['name']}")
            print(f"ID: {item['id']}")
            print(f"Type: {item['mimeType']}")
            print(f"Link: {item.get('webViewLink', 'N/A')}")
            print("-" * 50)

        return items

    except Exception as e:
        print(f"Error listing files: {e}")
        return []


def search_by_name(service, name, file_type=None):
    """Search for files/folders by name."""
    try:
        query = f"name contains '{name}' and trashed=false"

        if file_type == "folder":
            query += " and mimeType='application/vnd.google-apps.folder'"
        elif file_type == "spreadsheet":
            query += " and mimeType='application/vnd.google-apps.spreadsheet'"

        results = (
            service.files()
            .list(
                q=query,
                pageSize=50,
                fields="nextPageToken, files(id, name, mimeType, webViewLink, parents)",
            )
            .execute()
        )

        items = results.get("files", [])

        print(f"=== SEARCH FOR '{name}' ===")
        if not items:
            print("No results found")
            return []

        for item in items:
            print(f"Name: {item['name']}")
            print(f"ID: {item['id']}")
            print(f"Type: {item['mimeType']}")
            print(f"Link: {item.get('webViewLink', 'N/A')}")
            print(f"Parents: {item.get('parents', [])}")
            print("-" * 50)

        return items

    except Exception as e:
        print(f"Error in search: {e}")
        return []


def get_drive_info(service):
    """Get general information about the drive."""
    try:
        about = service.about().get(fields="user, storageQuota").execute()
        print("=== DRIVE INFORMATION ===")
        print(f"User: {about.get('user', {}).get('displayName', 'N/A')}")
        print(f"Email: {about.get('user', {}).get('emailAddress', 'N/A')}")

        quota = about.get("storageQuota", {})
        if quota:
            limit = int(quota.get("limit", 0))
            usage = int(quota.get("usage", 0))
            print(f"Storage used: {usage / (1024**3):.2f} GB")
            print(f"Limit: {limit / (1024**3):.2f} GB")
        print()

    except Exception as e:
        print(f"Error getting drive information: {e}")


def main():
    """Main function."""
    print("🔍 Exploring Google Drive...")
    print("=" * 60)

    service = get_drive_service()

    # General information
    get_drive_info(service)

    # Root folder
    root_id = get_root_folder(service)

    if root_id:
        # List folders in root
        folders = list_folders(service, root_id)

        # List some files in root
        files = list_files(service, root_id, max_results=10)

        # Search for existing templates
        print("\n" + "=" * 60)
        print("🔍 Searching for existing templates...")
        search_by_name(service, "template", "spreadsheet")
        search_by_name(service, "quote", "spreadsheet")

        # Save information to JSON file
        drive_info = {
            "root_id": root_id,
            "folders": folders,
            "files": files[:5],  # Only first 5 files
            "timestamp": "2025-07-20",
        }

        with open("drive_structure.json", "w", encoding="utf-8") as f:
            json.dump(drive_info, f, indent=2, ensure_ascii=False)

        print("\n✅ Information saved to 'drive_structure.json'")
        print(f"📁 Root folder ID: {root_id}")


if __name__ == "__main__":
    main()
