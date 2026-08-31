"""Print a Google Doc's text (exported as Markdown) via the service account.

Read companion to explore_google_drive.py — that lists the Drive tree, this
reads a document's content. Same delegated auth (credentials from
apps/core/gauth.py via scripts/gdocs/gauth.py).

Usage:
    GCP_CREDENTIALS=<key.json> uv run python -m scripts.gdocs.read_google_doc <doc_id>
"""

import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from scripts.gdocs.gauth import build_delegated_drive  # noqa: E402


def read_doc(doc_id: str) -> str:
    """Export the doc as Markdown through the Drive API (no Docs resource needed)."""
    data = build_delegated_drive().files().export(fileId=doc_id, mimeType="text/markdown").execute()
    if isinstance(data, bytes):
        return data.decode("utf-8")
    return str(data)


if __name__ == "__main__":
    print(read_doc(sys.argv[1]))
