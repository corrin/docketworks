#!/usr/bin/env python
"""Regenerate locale/en_NZ/LC_MESSAGES/django.po from the backend's gettext calls.

The .po file is the list of every backend message a user can read (ADR 0069):
it is where the wording is reviewed, so it has to match the code. `--check`
fails when the committed copy is stale instead of rewriting it.

Locations are file-only (`--add-location=file`): line numbers would rewrite the
file on every unrelated edit above a message, and the file is enough to find it.
The POT-Creation-Date header is dropped for the same reason — it changes on
every run and says nothing about the messages. Lines are not wrapped
(`--no-wrap`): gettext 0.21 and 0.23 wrap a long message at different places,
and the committed copy has to match whichever one a machine has.
"""

import argparse
import os
import re

import django
from django.core.management import call_command

from scripts import REPO_ROOT
from scripts.django_settings import pin_settings

TARGET = REPO_ROOT / "locale" / "en_NZ" / "LC_MESSAGES" / "django.po"

CREATION_DATE = re.compile(r'^"POT-Creation-Date: .*\\n"\n', re.MULTILINE)

IGNORE = ["frontend/*", "node_modules/*", ".venv/*", "docs/*", "tests/*", "logs/*"]


def regenerate() -> str:
    """Run makemessages and return the normalised catalogue it wrote."""
    django.setup()
    # makemessages scans and writes relative to the working directory.
    os.chdir(REPO_ROOT)
    call_command(
        "makemessages",
        locale=["en_NZ"],
        add_location="file",
        no_obsolete=True,
        no_wrap=True,
        ignore_patterns=IGNORE,
        verbosity=0,
    )
    return CREATION_DATE.sub("", TARGET.read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed catalogue is stale instead of rewriting it",
    )
    args = parser.parse_args()
    pin_settings()

    committed = TARGET.read_text() if TARGET.exists() else None
    rendered = regenerate()
    if args.check:
        # The check leaves the committed file exactly as it found it.
        if committed is None:
            TARGET.unlink()
        else:
            TARGET.write_text(committed)
        if committed != rendered:
            print(
                f"{TARGET.relative_to(REPO_ROOT)} is stale: a backend message changed "
                "since it was generated. Run:\n"
                "  uv run python -m scripts.checks.messages_catalogue\n"
                "and commit it."
            )
            return 1
        print(f"{TARGET.relative_to(REPO_ROOT)} is current")
        return 0

    TARGET.write_text(rendered)
    print(f"wrote {TARGET.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
