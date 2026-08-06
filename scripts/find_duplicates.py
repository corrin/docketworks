#!/usr/bin/env python
"""Fail when one concept has two definitions (ADR 0039, and CLAUDE.md's prime rule).

Two checks, both of them things a linter cannot see, because they are about
the shape of the TREE rather than the contents of a file:

SIBLING MODULES — a module whose name is another's plus a marker like `rest`
or `legacy`, sitting in the same directory. This catches v1's actual
pathology, and it was verified against v1 rather than assumed: run over v1 it
reports four pairs — `job_rest_service`/`job_service`, and `urls_rest`/`urls`
in each of job, process and purchasing. Over v2, nothing.

COLLIDING SYMBOLS — the same public module-level symbol defined in two
modules under apps/. Note what this does NOT do: measured against v1 it finds
six collisions and none of them are the parallel job services or the three
etag modules, because those siblings used DIFFERENT names. Same-name
collision is a narrower defect than duplication, and it is worth catching on
its own terms — it found `PhoneCompanyOwner` declared with `company_id: str`
in one module and `company_id: UUID` in another.

Deliberately ABSENT: a within-file scan for duplicate methods, class
attributes and dict keys. v1's `scripts/find_duplicates.py` did that and this
script was originally a port of it, but ruff already runs on every commit
with `F` and `PIE` selected and covers the same ground strictly better —
F811 for redefined methods AND module-level functions/classes, PIE794 for
class attributes, F601 for dict keys anywhere including class bodies and
module scope. The hand-written version missed all three of those wider cases
and additionally flagged `@typing.overload` as a duplicate. Reimplementing an
enabled library rule is the exact pathology this gate exists to prevent
(ADR 0032, ADR 0039).

A same-basename check (three `etag.py` files) was tried and rejected: Django
mandates per-app `models.py`, `admin.py`, `apps.py`, so it cannot separate
duplication from framework layout without an exemption list.

Exemptions are structural, never a hand-maintained list of names — a name
list would grow every time someone wanted their duplicate blessed, which is
how the gate would stop meaning anything:

- Django management commands must all define `Command`.
- An `api.py` handler beside its `services/` implementation of the same name
  is the layering this codebase mandates. v2 has 13 such pairs, which is
  every name it defines in more than one module — so this exemption is
  currently carrying the whole check, and widening it would silently disable
  the check entirely.

Usage: uv run python scripts/find_duplicates.py
Exit 0 = no duplicate definitions.
"""

import ast
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APPS = REPO / "apps"

# Markers that turn one module name into a sibling of another. Kept short and
# concrete: every entry is a suffix v1 actually grew (`urls_rest`, then
# `job_rest_service`) or the obvious next one. A broad list would start
# matching legitimate names like `test_helpers`.
SIBLING_MARKERS = frozenset({"rest", "new", "old", "legacy", "v2", "impl", "copy"})


def _app_of(path: Path) -> str:
    return path.relative_to(APPS).parts[0]


def _is_handler_service_pair(paths: set[Path]) -> bool:
    """One `api.py` handler and one `services/` implementation in the same app."""
    if len(paths) != 2:
        return False
    handlers = {path for path in paths if path.name == "api.py"}
    services = {path for path in paths if "services" in path.parts}
    if len(handlers) != 1 or len(services) != 1:
        return False
    handler, service = next(iter(handlers)), next(iter(services))
    # `<app>/services/api.py` satisfies BOTH roles, which would make the
    # same-app test compare that path to itself and exempt whatever it was
    # paired with, in any app. The exemption is about two DIFFERENT files.
    if handler == service:
        return False
    return _app_of(handler) == _app_of(service)


def _scan_sibling_modules() -> list[str]:
    """Modules whose name is another module's name plus a sibling marker.

    Grouped by DIRECTORY, not by bare stem. Stems are nowhere near unique —
    v2 alone has 15 `apps.py`, 9 `schemas.py` and 9 `api.py` — so a single
    {stem: path} map silently keeps one arbitrary survivor per name and drops
    the rest, which both hides real pairs and invents cross-app ones. v1's
    four `urls_rest.py` files were all reported as one for exactly this reason.
    A sibling is a module sitting BESIDE the thing it duplicates.
    """
    by_directory: dict[Path, dict[str, Path]] = defaultdict(dict)
    for path in sorted(APPS.rglob("*.py")):
        if "migrations" in path.parts or path.name == "__init__.py":
            continue
        by_directory[path.parent][path.stem] = path

    issues = []
    for siblings in by_directory.values():
        for stem, path in sorted(siblings.items()):
            tokens = stem.split("_")
            for index, token in enumerate(tokens):
                if token not in SIBLING_MARKERS:
                    continue
                base = "_".join(tokens[:index] + tokens[index + 1 :])
                if base and base in siblings:
                    issues.append(
                        f"{path.relative_to(REPO)} is a sibling of "
                        f"{siblings[base].relative_to(REPO)} — v1 rotted exactly this way "
                        "(job_rest_service.py beside job_service.py). Extend the original."
                    )
    return issues


def _scan_across_modules() -> list[str]:
    """Public module-level symbols defined in more than one module."""
    definitions: dict[str, set[Path]] = defaultdict(set)
    for path in sorted(APPS.rglob("*.py")):
        parts = path.parts
        # Tests legitimately repeat helper names per app; migrations are
        # generated. Duplicates WITHIN either are ruff's job (F811), not this
        # check's, which is only about the same name in two places.
        if "migrations" in parts or "tests" in parts or path.name == "conftest.py":
            continue
        if "commands" in parts and "management" in parts:
            continue  # every Django command class is named Command
        for node in ast.parse(path.read_text(), filename=str(path)).body:
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            if node.name.startswith("_"):
                continue
            definitions[node.name].add(path)

    issues = []
    for name, paths in sorted(definitions.items()):
        if len(paths) < 2 or _is_handler_service_pair(paths):
            continue
        where = ", ".join(sorted(str(p.relative_to(REPO)) for p in paths))
        issues.append(
            f"{name!r} is defined in {len(paths)} modules: {where} "
            "— one concept, one implementation (ADR 0039): extend one and import it"
        )
    return issues


def main() -> int:
    issues = _scan_sibling_modules() + _scan_across_modules()
    if not issues:
        print("no duplicate definitions found")
        return 0
    print(f"found {len(issues)} duplicate definitions:\n")
    for issue in issues:
        print(f"  {issue}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
