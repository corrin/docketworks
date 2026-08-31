"""Set a captured screenshot into a Google Doc at its {{screenshot:<id>}} marker.

Finds the marker text, uploads the PNG to Drive, inserts it as an inline image
at the marker, and deletes the marker text. If the marker is already gone (image
previously set) it reports and does nothing — re-capturing into an existing image
is a separate replaceImage path (not yet built).

This is the push half of the screenshot pipeline; the capture half is
frontend/scripts/capture-screenshots.ts (run via `npm run manual:screenshots`).

Auth is the shared delegated convention (credentials from apps/core/gauth.py).

Usage:
    GCP_CREDENTIALS=<key.json> uv run python -m scripts.gdocs.set_doc_screenshot \\
        <doc_id> <screenshot_id> <png_path>
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from googleapiclient.http import MediaIoBaseUpload  # noqa: E402
from PIL import Image  # noqa: E402

from scripts.gdocs.gauth import build_delegated_drive_and_docs  # noqa: E402

if TYPE_CHECKING:
    from googleapiclient._apis.docs.v1.schemas import Document
    from googleapiclient._apis.drive.v3.resources import DriveResource

# Fit the image to a typical Google Doc content width.
MAX_WIDTH_PT = 460.0


def find_marker(doc: Document, marker: str) -> tuple[int, int] | None:
    """Return the (start, end) indexes of the marker's text run, or None if absent."""
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


def upload_png(drive: DriveResource, png_path: str) -> str:
    """Upload the PNG world-readable (so Docs can fetch it) and return its file id."""
    media = MediaIoBaseUpload(
        io.BytesIO(Path(png_path).read_bytes()), mimetype="image/png", resumable=False
    )
    f = (
        drive.files()
        .create(body={"name": "screenshot-tmp.png"}, media_body=media, fields="id")
        .execute()
    )
    fid = f["id"]
    drive.permissions().create(fileId=fid, body={"type": "anyone", "role": "reader"}).execute()
    return fid


def main(doc_id: str, screenshot_id: str, png_path: str) -> int:
    """Insert the PNG at the doc's marker; 0 = done, 1 = marker absent, 2 = marker survived."""
    drive, docs = build_delegated_drive_and_docs()
    marker = "{{screenshot:" + screenshot_id + "}}"
    doc = docs.documents().get(documentId=doc_id).execute()
    found = find_marker(doc, marker)
    if not found:
        print(f"marker {marker} not found in doc (already set?). Nothing to do.")
        return 1
    start, end = found

    with Image.open(png_path) as image:
        w, h = image.size
    disp_w = min(MAX_WIDTH_PT, float(w))
    disp_h = disp_w * h / w

    fid = upload_png(drive, png_path)
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
