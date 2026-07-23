"""Write/replace a Google Doc from Markdown, WITH an overwrite safety net.

Write companion to read_google_doc.py. Imports a Markdown file as a Google Doc
(headings, bold, lists, tables and {{screenshot:id}} markers survive), and will
only ever replace or trash a doc that:
  (a) this tool created or was told to manage (recorded in the manifest), AND
  (b) has NOT been edited since this tool last wrote it
      (current Docs content revisionId == the revisionId recorded after our write).

The signal is the Docs content revisionId (edit history), NOT modifiedTime:
revisionId changes only on a real content edit, so it ignores the async metadata
mtime bump Drive applies after an import. lastModifyingUser is useless here — the
service account writes by impersonating a human, so every change shows that
human's address regardless of who actually made it.

Any doc not in the manifest (human-authored / pre-existing), or any manifest doc
whose revisionId has changed (a human edited it), is REFUSED. To manage an
existing human doc, `seed` it first (baselines its current revision); a later
`import` then replaces it, refusing if a human edited it in between.

Auth follows the app convention (GCP_CREDENTIALS + CompanyDefaults.company_email,
GCP_DELEGATED_SUBJECT override), same as read_google_doc.py.

Usage:
    write_google_doc.py import <md_path> <folder_id> <title>
    write_google_doc.py seed <doc_id>     # baseline an existing doc so it can be managed
    write_google_doc.py trash <doc_id>    # trash a managed doc (if unedited since our write)
    write_google_doc.py status            # show manifest vs live state
"""

import io
import json
import os
import sys
from typing import TypedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from apps.workflow.models import CompanyDefaults

# One manifest entry: what this tool wrote, where, and the revision it left
# behind (the edit-detection baseline).
ManifestEntry = TypedDict(
    "ManifestEntry", {"title": str, "folder_id": str, "revisionId": str}
)

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]
# Per-instance state (which docs this tool manages + their post-write revisionId).
# Gitignored — it is runtime data, not source.
MANIFEST = os.path.join(os.path.dirname(__file__), "google_doc_manifest.json")


def _clients():
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
    return build("drive", "v3", credentials=creds), build(
        "docs", "v1", credentials=creds
    )


drive, docs = _clients()


def load() -> dict[str, ManifestEntry]:
    if os.path.exists(MANIFEST):
        with open(MANIFEST) as fh:
            return json.load(fh)
    return {}


def save(manifest: dict[str, ManifestEntry]) -> None:
    with open(MANIFEST, "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)


def revid(doc_id: str) -> str:
    """Docs content revisionId — changes only on a real content edit."""
    return (
        docs.documents()
        .get(documentId=doc_id, fields="revisionId")
        .execute()["revisionId"]
    )


def q_literal(value: str) -> str:
    """Escape a value for use inside a Drive query string literal.

    Drive's query grammar takes backslash escapes, so a perfectly ordinary
    title like "Driver's Handbook" would otherwise terminate the literal early
    and make the whole query invalid.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


def find_in_folder(folder_id: str, title: str) -> list[dict[str, str]]:
    return (
        drive.files()
        .list(
            q=(
                f"name = '{q_literal(title)}' "
                f"and '{q_literal(folder_id)}' in parents and trashed = false "
                "and mimeType = 'application/vnd.google-apps.document'"
            ),
            fields="files(id)",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        )
        .execute()
        .get("files", [])
    )


class OverwriteRefused(Exception):
    pass


def check_unedited(doc_id: str, manifest: dict[str, ManifestEntry]) -> None:
    """Raise unless doc_id is managed by this tool and unedited since our write."""
    rec = manifest.get(doc_id)
    if rec is None:
        raise OverwriteRefused(f"{doc_id} is not managed by this tool. Refusing.")
    if rec["revisionId"] != revid(doc_id):
        raise OverwriteRefused(
            f"{doc_id} ('{rec['title']}') has been edited since this tool wrote "
            f"it (revisionId changed). Refusing to touch a human edit."
        )


def do_import(md_path: str, folder_id: str, title: str) -> str:
    manifest = load()
    existing = find_in_folder(folder_id, title)
    if existing:
        doc_id = existing[0]["id"]
        check_unedited(doc_id, manifest)  # refuses if human-edited or unmanaged
        drive.files().update(
            fileId=doc_id, body={"trashed": True}, supportsAllDrives=True
        ).execute()
        del manifest[doc_id]

    with open(md_path, "rb") as fh:
        media = MediaIoBaseUpload(
            io.BytesIO(fh.read()), mimetype="text/markdown", resumable=False
        )
    created = (
        drive.files()
        .create(
            body={
                "name": title,
                "mimeType": "application/vnd.google-apps.document",
                "parents": [folder_id],
            },
            media_body=media,
            fields="id,webViewLink",
            supportsAllDrives=True,
        )
        .execute()
    )
    manifest[created["id"]] = {
        "title": title,
        "folder_id": folder_id,
        "revisionId": revid(created["id"]),
    }
    save(manifest)
    print(f"created: {created['webViewLink']}")
    return created["id"]


def trash(doc_id: str) -> None:
    """Trash a managed doc, refusing if a human has edited it."""
    manifest = load()
    check_unedited(doc_id, manifest)
    drive.files().update(
        fileId=doc_id, body={"trashed": True}, supportsAllDrives=True
    ).execute()
    title = manifest.pop(doc_id)["title"]
    save(manifest)
    print(f"trashed '{title}' ({doc_id})")


def seed(doc_id: str) -> None:
    """Baseline an existing doc at its current revision so it may be managed
    (until a human next edits it)."""
    manifest = load()
    f = (
        drive.files()
        .get(fileId=doc_id, fields="id,name,parents", supportsAllDrives=True)
        .execute()
    )
    manifest[f["id"]] = {
        "title": f["name"],
        "folder_id": f["parents"][0],
        "revisionId": revid(f["id"]),
    }
    save(manifest)
    print(f"seeded {f['id']} '{f['name']}'")


def status() -> None:
    manifest = load()
    print(f"{len(manifest)} docs under management:")
    for doc_id, rec in manifest.items():
        try:
            state = "unchanged" if revid(doc_id) == rec["revisionId"] else "EDITED"
        except HttpError as exc:
            # Only a genuine "it isn't there" is a status. A 403, a quota error
            # or a network failure means we do not know the state, and
            # reporting it as MISSING/TRASHED would be a lie.
            if exc.status_code != 404:
                raise
            state = "MISSING/TRASHED"
        print(f"  {rec['title']:42} {state}")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "import":
        try:
            do_import(sys.argv[2], sys.argv[3], sys.argv[4])
        except OverwriteRefused as e:
            print(f"SAFETY NET — REFUSED: {e}")
            return 3
    elif cmd == "trash":
        try:
            trash(sys.argv[2])
        except OverwriteRefused as e:
            print(f"SAFETY NET — REFUSED: {e}")
            return 3
    elif cmd == "seed":
        seed(sys.argv[2])
    elif cmd == "status":
        status()
    else:
        print(f"unknown command: {cmd!r} (use import/seed/trash/status)")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
