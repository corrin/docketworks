"""Print a Google Doc's text (exported as Markdown) via the service account.

Read companion to explore_google_drive.py — that lists the Drive tree, this
reads a document's content. Same delegated auth (GCP_CREDENTIALS +
CompanyDefaults.company_email, GCP_DELEGATED_SUBJECT override).

Usage:
    GCP_CREDENTIALS=<key.json> python scripts/read_google_doc.py <doc_id>
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

# Drive only: read_doc() exports through the Drive API and never touches a Docs
# API resource. (Narrowing further to drive.readonly would need that scope
# authorised on the domain-wide-delegation client in the Workspace admin
# console, so it is not a safe unilateral change.)
SCOPES = ["https://www.googleapis.com/auth/drive"]


def build_drive():
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
            "CompanyDefaults.company_email in Settings."
        )
    creds = service_account.Credentials.from_service_account_file(
        key_file, scopes=SCOPES
    ).with_subject(subject)
    return build("drive", "v3", credentials=creds)


def read_doc(doc_id: str) -> str:
    data = (
        build_drive().files().export(fileId=doc_id, mimeType="text/markdown").execute()
    )
    return data.decode("utf-8") if isinstance(data, bytes) else str(data)


if __name__ == "__main__":
    print(read_doc(sys.argv[1]))
