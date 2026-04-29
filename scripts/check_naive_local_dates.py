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
    python scripts/check_naive_local_dates.py [files...]
    python scripts/check_naive_local_dates.py            # full sweep

Exit code is non-zero on any finding, suitable for pre-commit.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from typing import Iterable

DEFAULT_ROOTS = ["apps", "docketworks", "scripts"]
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


def _is_date_call_on(target: ast.AST, value: ast.AST) -> bool:
    """True if `target` is `<value>.date()`."""
    return (
        isinstance(target, ast.Call)
        and isinstance(target.func, ast.Attribute)
        and target.func.attr == "date"
        and target.func.value is value
    )


def _add_parents(tree: ast.AST) -> None:
    """Annotate every node with a `.parent` reference for upward traversal."""
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child.parent = parent  # type: ignore[attr-defined]


def _enclosing_stmt_range(node: ast.AST) -> tuple[int, int]:
    """Return the (start, end) line range of the simple statement that
    contains ``node``. Black may wrap a long call across several physical
    lines, pushing trailing `# noqa` comments off the call's own line, so
    the noqa check needs to scan every line of the enclosing statement.
    """
    cur = node
    while cur is not None and not isinstance(cur, ast.stmt):
        cur = getattr(cur, "parent", None)
    if cur is None:
        return node.lineno, getattr(node, "end_lineno", node.lineno) or node.lineno
    end = getattr(cur, "end_lineno", cur.lineno) or cur.lineno
    return cur.lineno, end


class NaiveLocalDateVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        # Names assigned `= timezone.now()` (module-level or function-scoped —
        # we conservatively track all assignments without scope tracking, which
        # is fine for this lint: the only false positives would be a name
        # rebound to something non-timezone, which is exotic enough to ignore).
        self.timezone_now_aliases: set[str] = set()
        self.findings: list[tuple[int, int, int, str]] = []

    def visit_Assign(self, node: ast.Assign) -> None:
        if _is_timezone_now_call(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.timezone_now_aliases.add(target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None and _is_timezone_now_call(node.value):
            if isinstance(node.target, ast.Name):
                self.timezone_now_aliases.add(node.target.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # We are looking for `<X>.date()` where <X> is either a call to
        # timezone.now() (inline) or a Name bound to one (aliased).
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
                stmt_start, stmt_end = _enclosing_stmt_range(node)
                self.findings.append((node.lineno, stmt_start, stmt_end, label))
        self.generic_visit(node)


def _scan_noqa(lines: list[str], start: int, end: int) -> str | None:
    """Return the matched-but-empty reason marker (``"bare"``), the reason
    text if present, or ``None`` if no `# noqa: localdate` is in the
    [start, end] line range (inclusive, 1-indexed)."""
    for lineno in range(start, end + 1):
        if not 0 < lineno <= len(lines):
            continue
        match = NOQA_RE.search(lines[lineno - 1])
        if not match:
            continue
        reason = (match.group("reason") or "").strip()
        return reason if reason else "bare"
    return None


def check_file(path: str) -> list[tuple[str, int, str]]:
    with open(path, "r", encoding="utf-8") as fh:
        source = fh.read()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []

    _add_parents(tree)
    lines = source.splitlines()
    visitor = NaiveLocalDateVisitor()
    visitor.visit(tree)

    issues: list[tuple[str, int, str]] = []
    for lineno, stmt_start, stmt_end, label in visitor.findings:
        noqa = _scan_noqa(lines, stmt_start, stmt_end)
        if noqa is not None and noqa != "bare":
            continue
        if noqa == "bare":
            issues.append(
                (
                    path,
                    lineno,
                    "bare `# noqa: localdate` — justification required "
                    "(e.g. `# noqa: localdate UTC needed for foreign API`)",
                )
            )
            continue
        issues.append(
            (
                path,
                lineno,
                f"{label} — use `timezone.localdate()` instead",
            )
        )
    return issues


def _iter_python_files(roots: Iterable[str]) -> Iterable[str]:
    for root in roots:
        if os.path.isfile(root) and root.endswith(".py"):
            yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            if "/migrations" in dirpath or dirpath.endswith("/migrations"):
                continue
            for filename in filenames:
                if filename.endswith(".py"):
                    yield os.path.join(dirpath, filename)


def _is_excluded(path: str) -> bool:
    parts = path.split(os.sep)
    return "migrations" in parts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files",
        nargs="*",
        help=(
            "Specific files to check (e.g. when invoked from pre-commit). "
            "Defaults to a full sweep of apps/, docketworks/, scripts/."
        ),
    )
    args = parser.parse_args()

    targets = args.files or DEFAULT_ROOTS
    candidates = [
        path for path in _iter_python_files(targets) if not _is_excluded(path)
    ]

    all_issues: list[tuple[str, int, str]] = []
    for path in candidates:
        all_issues.extend(check_file(path))

    if not all_issues:
        return 0

    for path, lineno, message in sorted(all_issues):
        print(f"{path}:{lineno}: {message}")
    print(
        f"\n{len(all_issues)} occurrence(s) found. Replace `timezone.now().date()` "
        "with `timezone.localdate()`. If a UTC date is genuinely required, add "
        "`# noqa: localdate <reason>` on the line.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
