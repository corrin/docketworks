"""Set a captured screenshot into a Google Doc at its {{screenshot:<id>}} marker.

Finds the marker text, uploads the PNG to Drive, inserts it as an inline image
at the marker, and deletes the marker text. If the marker is already gone (image
previously set) it reports and does nothing — re-capturing into an existing image
is a separate replaceImage path (not yet built).

This is the push half of the screenshot pipeline; the capture half is
frontend/scripts/capture-screenshots.ts (run via `npm run manual:screenshots`).

Auth follows the app convention (apps/job/importers/google_sheets.py): key from
the GCP_CREDENTIALS env var, subject from CompanyDefaults.company_email, with a
GCP_DELEGATED_SUBJECT env override for pointing a dev box at a client's Drive
(the dev DB's company_email is a demo placeholder, not a real Workspace user).

Usage:
    GCP_CREDENTIALS=<key.json> python scripts/set_doc_screenshot.py \
        <doc_id> <screenshot_id> <png_path>
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from PIL import Image

from apps.workflow.models import CompanyDefaults

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]

# Fit the image to a typical Google Doc content width.
MAX_WIDTH_PT = 460.0


def build_services():
    """Drive + Docs clients, impersonating the resolved Workspace subject."""
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
    return build("drive", "v3", credentials=creds), build(
        "docs", "v1", credentials=creds
    )


drive, docs = build_services()


def find_marker(doc: dict, marker: str):
    for el in doc.get("body", {}).get("content", []):
        para = el.get("paragraph")
        if not para:
            continue
        for pe in para.get("elements", []):
            tr = pe.get("textRun")
            if not tr:
                continue
            idx = tr.get("content", "").find(marker)
            if idx != -1:
                start = pe["startIndex"] + idx
                return start, start + len(marker)
    return None


def upload_png(png_path: str) -> str:
    with open(png_path, "rb") as fh:
        data = fh.read()
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype="image/png", resumable=False)
    f = (
        drive.files()
        .create(body={"name": "screenshot-tmp.png"}, media_body=media, fields="id")
        .execute()
    )
    fid = f["id"]
    drive.permissions().create(
        fileId=fid, body={"type": "anyone", "role": "reader"}
    ).execute()
    return fid


def main(doc_id: str, screenshot_id: str, png_path: str) -> int:
    marker = "{{screenshot:%s}}" % screenshot_id
    doc = docs.documents().get(documentId=doc_id).execute()
    found = find_marker(doc, marker)
    if not found:
        print(f"marker {marker} not found in doc (already set?). Nothing to do.")
        return 1
    start, end = found

    w, h = Image.open(png_path).size
    disp_w = min(MAX_WIDTH_PT, float(w))
    disp_h = disp_w * h / w

    fid = upload_png(png_path)
    uri = f"https://drive.google.com/uc?export=download&id={fid}"
    try:
        docs.documents().batchUpdate(
            documentId=doc_id,
            body={
                "requests": [
                    {
                        "insertInlineImage": {
                            "location": {"index": start},
                            "uri": uri,
                            "objectSize": {
                                "width": {"magnitude": disp_w, "unit": "PT"},
                                "height": {"magnitude": disp_h, "unit": "PT"},
                            },
                        }
                    },
                    {
                        "deleteContentRange": {
                            "range": {"startIndex": start + 1, "endIndex": end + 1}
                        }
                    },
                ]
            },
        ).execute()
    finally:
        # The upload is world-readable so Docs can fetch it, and Docs keeps its
        # own copy once inserted. Only a permanent delete revokes that public
        # grant — trashing leaves it live.
        drive.files().delete(fileId=fid).execute()

    after = docs.documents().get(documentId=doc_id).execute()
    n_images = len(after.get("inlineObjects", {}))
    marker_gone = find_marker(after, marker) is None
    print(
        f"inserted image ({disp_w:.0f}x{disp_h:.0f} pt); doc now has {n_images} "
        f"inline image(s); marker removed: {marker_gone}"
    )
    return 0 if marker_gone else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
