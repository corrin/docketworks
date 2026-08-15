#!/usr/bin/env python
"""Harness for the spreadsheet quote import service — BLOCKED, see below.

Quote import is not ported yet: v1's apps/job/services/import_quote_service.py
(preview_quote_import / import_quote_from_file) has no v2 counterpart, so this
harness refuses to run rather than pretending to test anything. The argument
surface is kept so the eventual port drops straight in.

Usage (once unblocked):
    uv run python scripts/ops/quote_import_harness.py --file "Quote.xlsx"
    uv run python scripts/ops/quote_import_harness.py --file "Quote.xlsx" --job-id <uuid>
    uv run python scripts/ops/quote_import_harness.py --file "Quote.xlsx" --preview-only
"""

import argparse
import os
import sys
from pathlib import Path

# scripts/ops/ is two levels below the repo root; see
# scripts/ops/setup_dev_logins.py for why this is inserted explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()


def parse_args() -> argparse.Namespace:
    """The v1 harness's argument surface, preserved for the eventual port."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file",
        type=str,
        required=True,
        help="Path to the Excel file",
    )
    parser.add_argument(
        "--job-id",
        type=str,
        help="Job ID to import quote for (default: find or create test job)",
    )
    parser.add_argument(
        "--preview-only",
        action="store_true",
        help="Only preview import, do not actually import",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip spreadsheet validation during import",
    )
    return parser.parse_args()


def main() -> None:
    parse_args()
    raise SystemExit(
        "blocked-by: quote-import — the spreadsheet quote import service "
        "(v1: apps/job/services/import_quote_service.py, preview_quote_import "
        "and import_quote_from_file over CostSet revisions) is not ported to "
        "v2 yet. Port that service first, then wire this harness to it."
    )


if __name__ == "__main__":
    main()
