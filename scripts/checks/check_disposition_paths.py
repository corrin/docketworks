# Opus: !/usr/bin/env python3
"""Assert every path `docs/v1-disposition.md` calls ported actually exists.

That file is the record the v1 repository's deletion is meant to survive — its
own header promises "every 'ported' path below was verified to exist there",
and once v1 is gone a wrong entry is unfalsifiable: there is nothing left to
check it against. Verification that only happened once, by hand, is the thing
this repo has already learned not to trust (ADR 0050), so it runs on every
commit instead.

A `| ported |` row names its v2 path in the third column. Two rows name a
command or a function inside a module rather than a file; those are skipped and
printed by name, because the row is still a true statement about the port.

Usage:
    uv run python -m scripts.checks.check_disposition_paths

Exit code is non-zero on any missing path, suitable for pre-commit.
"""
# Opus: docstring rationale unratified (ADR 0051).

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from scripts import REPO_ROOT

DISPOSITION = REPO_ROOT / "docs" / "v1-disposition.md"

#: Opus: A ported row: `| <v1 thing> | ported | `<v2 path>`...`. Only the first
#: backticked token after the disposition column is the path.
_PORTED_ROW = re.compile(r"\|\s*ported\s*\|\s*`([^`]+)`")


@dataclass(frozen=True)
class DispositionAudit:
    """What the record claims, split by whether the tree bears it out."""

    present: list[str]
    missing: list[str]
    not_paths: list[str]


# Opus: docstring rationale unratified (ADR 0051).
def _is_a_path(candidate: str, root: Path) -> bool:
    """Whether a candidate that is NOT on disk is nevertheless claiming to be a file.

    Existence is the primary signal — anything present is a path, whatever it
    looks like, which is why this is asked only of the absent. Judging by
    filename shape instead skipped a dozen real entries (`.nvmrc`,
    `.gitattributes`, directories, a `.json.template`) and reported a smaller
    check as a passing one.

    Two shapes are legitimately not files: a command, which has whitespace; and
    a reference to something INSIDE a module, like
    ``apps/xero/seeding._employees_phase``, recognised by its module existing.
    """
    if " " in candidate:
        return False
    module, _, _attribute = candidate.rpartition(".")
    return not (module and (root / f"{module}.py").exists())


# Opus: docstring rationale unratified (ADR 0051).
def _escapes_the_repo(candidate: str) -> bool:
    """Whether the row names something outside the tree it claims to describe.

    ``root / "/etc/passwd"`` is ``/etc/passwd`` — pathlib lets an absolute
    operand discard the left-hand side entirely — so an absolute row passed
    this audit whenever the file happened to exist on the machine running it.
    ``..`` walks out the same way. Either would let the record claim a port
    that is not in this repository, which is the one thing it exists to deny.
    """
    path = PurePosixPath(candidate)
    return path.is_absolute() or ".." in path.parts


def audit(markdown: str, root: Path) -> DispositionAudit:
    """Classify every `| ported |` row's path against the tree at ``root``."""
    present: list[str] = []
    missing: list[str] = []
    not_paths: list[str] = []
    for candidate in _PORTED_ROW.findall(markdown):
        if _escapes_the_repo(candidate):
            missing.append(candidate)
        elif (root / candidate).exists():
            present.append(candidate)
        elif _is_a_path(candidate, root):
            missing.append(candidate)
        else:
            not_paths.append(candidate)
    return DispositionAudit(present=present, missing=missing, not_paths=not_paths)


def main() -> int:
    """Report any ported path the working tree does not have."""
    if not DISPOSITION.exists():
        print(f"{DISPOSITION} is missing; the port record cannot be checked.")
        return 1

    result = audit(DISPOSITION.read_text(encoding="utf-8"), REPO_ROOT)

    if result.missing:
        print(
            f"{len(result.missing)} path(s) marked ported in {DISPOSITION.name} do not exist. "
            "Either the port moved and the record needs updating, or the entry was never "
            "true — and after v1 is deleted there is no way to tell which:"
        )
        for path in result.missing:
            print(f"  - {path}")
        return 1

    # Opus: Named, not merely counted: a check that silently skips rows reads as
    # full coverage while proving less than it appears to.
    print(
        f"v1-disposition: {len(result.present)} ported paths present, "
        f"{len(result.not_paths)} rows not paths."
    )
    for candidate in result.not_paths:
        print(f"  not checked (not a file): {candidate}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
