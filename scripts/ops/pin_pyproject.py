"""Move the direct dependency pins in pyproject.toml through a sweep (ADR 0033).

Three modes, each over the `dependencies` list and the `dev` group only:

- `show`  prints `name version` for every direct dependency (the sweep's before/after snapshot);
- `relax` turns every `==X` into `>=X` so `uv lock --upgrade` may move it;
- `pin`   turns every spec into `==<the version uv.lock resolved>`.

Only the version spec of a matching line changes. Comments and every other line are untouched, so
a deferral block stays beside the pin it explains and the human, not this script, decides whether
a moved pin stays moved. A spec carrying anything but one `==` or `>=` bound (a `<` cap, a `!=`)
stops the run: ADR 0033 says such a bound needs a dated deferral, and that is a decision for a
person. `scripts/ops/sweep_dependencies.sh` runs relax, `uv lock --upgrade`, pin.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
LOCK = ROOT / "uv.lock"

SECTION_START = re.compile(r"^(dependencies = \[|dev = \[)$")
SPEC = re.compile(
    r'^(?P<indent>\s*)"(?P<name>[A-Za-z0-9_.-]+)(?P<extras>\[[^\]]*\])?(?P<spec>[^"]*)",\s*$'
)
BOUND = re.compile(r"^(?P<op>==|>=)(?P<version>[A-Za-z0-9.+!-]+)$")


def normalised(name: str) -> str:
    """The lock file spells names lowercase with hyphens; pyproject may not."""
    return name.lower().replace("_", "-")


def locked_versions() -> dict[str, str]:
    """Every package in uv.lock, by normalised name."""
    with LOCK.open("rb") as handle:
        lock = tomllib.load(handle)
    packages: list[dict[str, str]] = lock["package"]
    return {normalised(package["name"]): package["version"] for package in packages}


def direct_specs(lines: list[str]) -> list[tuple[int, re.Match[str]]]:
    """Line index and parsed spec for each direct dependency line."""
    found: list[tuple[int, re.Match[str]]] = []
    in_section = False
    for index, line in enumerate(lines):
        if SECTION_START.match(line):
            in_section = True
        elif in_section and line.strip() == "]":
            in_section = False
        elif in_section:
            match = SPEC.match(line)
            if match is not None:
                found.append((index, match))
    return found


def bound_of(match: re.Match[str]) -> tuple[str, str]:
    """The single `==`/`>=` bound a direct spec carries; anything else is a person's decision."""
    bound = BOUND.match(match["spec"])
    if bound is None:
        raise SystemExit(
            f'{match["name"]}: spec "{match["spec"]}" is not a single == or >= bound; '
            "ADR 0033 wants a dated deferral for any other bound, so pin it by hand"
        )
    return bound["op"], bound["version"]


def rewrite(mode: str) -> list[str]:
    """Apply `relax` or `pin`; return one `name: old -> new` line per changed spec."""
    locked = locked_versions() if mode == "pin" else {}
    lines = PYPROJECT.read_text().split("\n")
    changed: list[str] = []
    for index, match in direct_specs(lines):
        op, version = bound_of(match)
        if mode == "relax":
            new_op, new_version = ">=", version
        else:
            new_op, new_version = "==", locked[normalised(match["name"])]
        line = f'{match["indent"]}"{match["name"]}{match["extras"] or ""}{new_op}{new_version}",'
        if line != lines[index]:
            changed.append(f"{match['name']}: {op}{version} -> {new_op}{new_version}")
            lines[index] = line
    PYPROJECT.write_text("\n".join(lines))
    return changed


def show() -> list[str]:
    """`name version` for every direct dependency, in file order."""
    lines = PYPROJECT.read_text().split("\n")
    return [f"{match['name']} {bound_of(match)[1]}" for _, match in direct_specs(lines)]


def main(argv: list[str]) -> int:
    """Dispatch one mode; usage error otherwise."""
    if len(argv) != 2 or argv[1] not in {"show", "relax", "pin"}:
        print("usage: pin_pyproject.py show|relax|pin", file=sys.stderr)
        return 2
    output = show() if argv[1] == "show" else rewrite(argv[1])
    for line in output:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
