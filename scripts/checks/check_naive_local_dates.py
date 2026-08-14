#!/usr/bin/env python3
"""Forbid `timezone.now().date()` (and its aliased equivalents).

Django's `timezone.now()` returns a UTC-aware datetime. Calling `.date()` on
it gives the *UTC* calendar date, which is wrong for any "what day is it for
the user" question whenever the project's local timezone is offset from UTC
(this codebase runs `Pacific/Auckland`, UTC+12/+13). Use
`timezone.localdate()` instead.

Detects:
  * Inline:   `timezone.now().date()`
  * Aliased:  `now = timezone.now() ... now.date()`

A line may opt out with `# noqa: localdate <reason>`. The justification
after the rule name is mandatory — bare `# noqa: localdate` is rejected to
match the project-wide rule that linter suppressions must carry a *why*.

Migrations are excluded — they are frozen historical snapshots.

Usage:
    uv run python -m scripts.checks.check_naive_local_dates [files...]
    uv run python -m scripts.checks.check_naive_local_dates    # full sweep

Exit code is non-zero on any finding, suitable for pre-commit.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from scripts import REPO_ROOT

DEFAULT_ROOTS = ["apps", "config", "scripts"]
NOQA_RE = re.compile(
    r"#\s*noqa:\s*localdate(?:\s*$|\s+(?P<reason>.+)$)",
    re.IGNORECASE,
)


def _is_timezone_now_call(node: ast.AST) -> bool:
    """True if `node` is a `timezone.now()` call expression."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "now"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "timezone"
    )


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    """Map every node to its parent for upward traversal.

    A side dict rather than v1's `child.parent = parent` attribute stuffing:
    ast nodes carry no such attribute in their type, so the assignment form
    cannot be expressed to mypy without casts on every read.
    """
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _enclosing_stmt_range(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> tuple[int, int]:
    """Return the (start, end) line range of the statement containing ``node``.

    A formatter may wrap a long call across several physical lines, pushing a
    trailing suppression comment off the call's own line, so the noqa scan
    covers every line of the enclosing statement.
    """
    cur: ast.AST | None = node
    while cur is not None and not isinstance(cur, ast.stmt):
        cur = parents.get(cur)
    node_lineno = getattr(node, "lineno", 1)
    if cur is None:
        return node_lineno, getattr(node, "end_lineno", node_lineno) or node_lineno
    end = cur.end_lineno or cur.lineno
    return cur.lineno, end


class NaiveLocalDateVisitor(ast.NodeVisitor):
    """Collect `.date()` calls on inline or aliased `timezone.now()` values."""

    def __init__(self) -> None:
        # Names assigned `= timezone.now()` — tracked without scope analysis,
        # which is fine for this lint: the only false positives would be a name
        # rebound to something non-timezone, which is exotic enough to ignore.
        self.timezone_now_aliases: set[str] = set()
        self.findings: list[tuple[int, ast.AST, str]] = []

    def visit_Assign(self, node: ast.Assign) -> None:
        """Record names bound to `timezone.now()`."""
        if _is_timezone_now_call(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.timezone_now_aliases.add(target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Record annotated names bound to `timezone.now()`."""
        if (
            node.value is not None
            and _is_timezone_now_call(node.value)
            and isinstance(node.target, ast.Name)
        ):
            self.timezone_now_aliases.add(node.target.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Flag `<X>.date()` where <X> is `timezone.now()` inline or aliased."""
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "date"
            and not node.args
            and not node.keywords
        ):
            value = node.func.value
            label: str | None = None
            if _is_timezone_now_call(value):
                label = "timezone.now().date()"
            elif isinstance(value, ast.Name) and value.id in self.timezone_now_aliases:
                label = f"{value.id}.date()  (aliased timezone.now())"
            if label is not None:
                self.findings.append((node.lineno, node, label))
        self.generic_visit(node)


def _scan_noqa(lines: list[str], start: int, end: int) -> str | None:
    """Return "bare" for an unjustified marker, the reason text, or None.

    Scans the [start, end] line range (inclusive, 1-indexed) for a
    `# noqa: localdate` marker.
    """
    for lineno in range(start, end + 1):
        if not 0 < lineno <= len(lines):
            continue
        match = NOQA_RE.search(lines[lineno - 1])
        if not match:
            continue
        reason = (match.group("reason") or "").strip()
        return reason if reason else "bare"
    return None


def check_file(path: Path) -> list[tuple[str, int, str]]:
    """Return (path, line, message) findings for one Python file."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        # A file that does not parse is ruff's problem, not this gate's.
        return []

    parents = _parent_map(tree)
    lines = source.splitlines()
    visitor = NaiveLocalDateVisitor()
    visitor.visit(tree)

    issues: list[tuple[str, int, str]] = []
    for lineno, node, label in visitor.findings:
        stmt_start, stmt_end = _enclosing_stmt_range(node, parents)
        noqa = _scan_noqa(lines, stmt_start, stmt_end)
        if noqa is not None and noqa != "bare":
            continue
        if noqa == "bare":
            issues.append(
                (
                    str(path),
                    lineno,
                    (
                        "bare `# noqa: localdate` — justification required "
                        "(e.g. `# noqa: localdate UTC needed for foreign API`)"
                    ),
                )
            )
            continue
        issues.append((str(path), lineno, f"{label} — use `timezone.localdate()` instead"))
    return issues


def _iter_python_files(roots: Iterable[str]) -> Iterable[Path]:
    """Yield .py files under each root, excluding migrations."""
    for root in roots:
        root_path = Path(root)
        if not root_path.is_absolute():
            root_path = REPO_ROOT / root_path
        if root_path.is_file() and root_path.suffix == ".py":
            yield root_path
            continue
        for path in sorted(root_path.rglob("*.py")):
            if "migrations" in path.parts:
                continue
            yield path


def main() -> int:
    """Run the check over the given files or the default full sweep."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files",
        nargs="*",
        help=(
            "Specific files to check (e.g. when invoked from pre-commit). "
            "Defaults to a full sweep of apps/, config/, scripts/."
        ),
    )
    args = parser.parse_args()

    targets: list[str] = args.files or DEFAULT_ROOTS

    all_issues: list[tuple[str, int, str]] = []
    for path in _iter_python_files(targets):
        all_issues.extend(check_file(path))

    if not all_issues:
        return 0

    for issue_path, lineno, message in sorted(all_issues):
        print(f"{issue_path}:{lineno}: {message}")
    print(
        f"\n{len(all_issues)} occurrence(s) found. Replace `timezone.now().date()` "
        "with `timezone.localdate()`. If a UTC date is genuinely required, add "
        "`# noqa: localdate <reason>` on the line.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
