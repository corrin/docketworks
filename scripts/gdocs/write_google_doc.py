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

Auth is the shared delegated convention (credentials from apps/core/gauth.py,
clients from scripts/gdocs/gauth.py), same as
read_google_doc.py.

Usage (uv run python -m scripts.gdocs.write_google_doc ...):
    write_google_doc import <md_path> <folder_id> <title>
    write_google_doc seed <doc_id>     # baseline an existing doc so it can be managed
    write_google_doc trash <doc_id>    # trash a managed doc (if unedited since our write)
    write_google_doc status            # show manifest vs live state
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from googleapiclient.errors import HttpError  # noqa: E402
from googleapiclient.http import MediaIoBaseUpload  # noqa: E402

from scripts.gdocs.gauth import build_delegated_drive_and_docs  # noqa: E402

if TYPE_CHECKING:
    from googleapiclient._apis.docs.v1.resources import DocsResource
    from googleapiclient._apis.drive.v3.resources import DriveResource
    from googleapiclient._apis.drive.v3.schemas import File


class ManifestEntry(TypedDict):
    """What this tool wrote, where, and the revision it left behind (the
    edit-detection baseline)."""

    title: str
    folder_id: str
    revisionId: str


# Per-instance state (which docs this tool manages + their post-write
# revisionId). Committed, not gitignored: the revisionIds ARE the overwrite
# safety net, and an untracked copy would exist on exactly one machine.
MANIFEST = Path(__file__).parent / "google_doc_manifest.json"


def load() -> dict[str, ManifestEntry]:
    """Read the manifest, validating each entry's shape (missing key = crash)."""
    if not MANIFEST.exists():
        return {}
    raw = json.loads(MANIFEST.read_text())
    if not isinstance(raw, dict):
        raise TypeError(f"{MANIFEST} is not a JSON object")
    return {
        doc_id: ManifestEntry(
            title=rec["title"], folder_id=rec["folder_id"], revisionId=rec["revisionId"]
        )
        for doc_id, rec in raw.items()
    }


def save(manifest: dict[str, ManifestEntry]) -> None:
    """Write the manifest back, stably ordered so diffs stay reviewable."""
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def revid(docs: DocsResource, doc_id: str) -> str:
    """Docs content revisionId — changes only on a real content edit."""
    return docs.documents().get(documentId=doc_id, fields="revisionId").execute()["revisionId"]


def q_literal(value: str) -> str:
    """Escape a value for use inside a Drive query string literal.

    Drive's query grammar takes backslash escapes, so a perfectly ordinary
    title like "Driver's Handbook" would otherwise terminate the literal early
    and make the whole query invalid.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


def find_in_folder(drive: DriveResource, folder_id: str, title: str) -> list[File]:
    """Docs named `title` directly inside `folder_id` (Shared Drives included)."""
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


class OverwriteRefusedError(Exception):
    """The safety net: the doc is unmanaged or has a human edit we must not clobber."""


def check_unedited(docs: DocsResource, doc_id: str, manifest: dict[str, ManifestEntry]) -> None:
    """Raise unless doc_id is managed by this tool and unedited since our write."""
    rec = manifest.get(doc_id)
    if rec is None:
        raise OverwriteRefusedError(f"{doc_id} is not managed by this tool. Refusing.")
    if rec["revisionId"] != revid(docs, doc_id):
        raise OverwriteRefusedError(
            f"{doc_id} ('{rec['title']}') has been edited since this tool wrote "
            f"it (revisionId changed). Refusing to touch a human edit."
        )


def do_import(
    drive: DriveResource, docs: DocsResource, md_path: str, folder_id: str, title: str
) -> str:
    """Replace (or create) the doc `title` in `folder_id` from the Markdown file."""
    manifest = load()
    existing = find_in_folder(drive, folder_id, title)
    if existing:
        doc_id = existing[0]["id"]
        check_unedited(docs, doc_id, manifest)  # refuses if human-edited or unmanaged
        drive.files().update(
            fileId=doc_id, body={"trashed": True}, supportsAllDrives=True
        ).execute()
        del manifest[doc_id]

    media = MediaIoBaseUpload(
        io.BytesIO(Path(md_path).read_bytes()), mimetype="text/markdown", resumable=False
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
        "revisionId": revid(docs, created["id"]),
    }
    save(manifest)
    print(f"created: {created['webViewLink']}")
    return created["id"]


def trash(drive: DriveResource, docs: DocsResource, doc_id: str) -> None:
    """Trash a managed doc, refusing if a human has edited it."""
    manifest = load()
    check_unedited(docs, doc_id, manifest)
    drive.files().update(fileId=doc_id, body={"trashed": True}, supportsAllDrives=True).execute()
    title = manifest.pop(doc_id)["title"]
    save(manifest)
    print(f"trashed '{title}' ({doc_id})")


def seed(drive: DriveResource, docs: DocsResource, doc_id: str) -> None:
    """Baseline an existing doc at its current revision so it may be managed
    (until a human next edits it)."""
    manifest = load()
    f = drive.files().get(fileId=doc_id, fields="id,name,parents", supportsAllDrives=True).execute()
    manifest[f["id"]] = {
        "title": f["name"],
        "folder_id": f["parents"][0],
        "revisionId": revid(docs, f["id"]),
    }
    save(manifest)
    print(f"seeded {f['id']} '{f['name']}'")


def status(docs: DocsResource) -> None:
    """Show each managed doc as unchanged, EDITED, or MISSING/TRASHED."""
    manifest = load()
    print(f"{len(manifest)} docs under management:")
    for doc_id, rec in manifest.items():
        try:
            state = "unchanged" if revid(docs, doc_id) == rec["revisionId"] else "EDITED"
        except HttpError as exc:
            # Only a genuine "it isn't there" is a status. A 403, a quota error
            # or a network failure means we do not know the state, and
            # reporting it as MISSING/TRASHED would be a lie.
            if exc.status_code != 404:
                raise
            state = "MISSING/TRASHED"
        print(f"  {rec['title']:42} {state}")


def main() -> int:
    """Dispatch import/seed/trash/status; exit 3 on a safety-net refusal."""
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    drive, docs = build_delegated_drive_and_docs()
    if cmd == "import":
        try:
            do_import(drive, docs, sys.argv[2], sys.argv[3], sys.argv[4])
        except OverwriteRefusedError as e:
            print(f"SAFETY NET — REFUSED: {e}")
            return 3
    elif cmd == "trash":
        try:
            trash(drive, docs, sys.argv[2])
        except OverwriteRefusedError as e:
            print(f"SAFETY NET — REFUSED: {e}")
            return 3
    elif cmd == "seed":
        seed(drive, docs, sys.argv[2])
    elif cmd == "status":
        status(docs)
    else:
        print(f"unknown command: {cmd!r} (use import/seed/trash/status)")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
