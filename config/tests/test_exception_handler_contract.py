"""Every exception handler in apps/ must leave a trace.

CLAUDE.md: "Every handler persists. A `try` needs a reason: reshape the error
or persist it with business context." ADR 0019 says the same. This test makes
that mechanically true instead of review-dependent, because the failure mode
is invisible by construction — a handler that swallows produces no log, no
row, and no symptom until someone notices the number is wrong.

A handler satisfies the contract three ways:

1. It re-raises (bare ``raise``, or ``raise X from exc``).
2. It calls ``persist_app_error``.
3. It carries an inline ``# deliberate-swallow: <reason>`` marker.

Form 3 is not a baseline. It is per-site, written by whoever made the choice,
and reviewed like any other line — the ADR 0043 pattern of recording the
rejected alternative at the seam. Batch loops are the honest case: one
unreadable product page must not abandon a scrape. "I did not think about it"
is not a reason, and a marker without text fails.
"""

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APPS = REPO_ROOT / "apps"

MARKER = re.compile(r"#\s*deliberate-swallow:\s*(?P<reason>\S.*)")

# Tests assert on raised exceptions and migrations are frozen historical
# records; neither is production error handling.
EXCLUDED_PARTS = ("/tests/", "/migrations/")


def _handler_satisfies_contract(node: ast.ExceptHandler, lines: list[str]) -> bool:
    if any(isinstance(inner, ast.Raise) for inner in ast.walk(node)):
        return True
    for inner in ast.walk(node):
        if not isinstance(inner, ast.Call):
            continue
        func = inner.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name == "persist_app_error":
            return True
    # The marker may sit on the `except` line or the line above it.
    for lineno in (node.lineno, node.lineno - 1):
        if 1 <= lineno <= len(lines) and MARKER.search(lines[lineno - 1]):
            return True
    return False


def _violations() -> list[str]:
    found: list[str] = []
    for path in sorted(APPS.rglob("*.py")):
        if any(part in str(path) for part in EXCLUDED_PARTS):
            continue
        source = path.read_text()
        lines = source.splitlines()
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if not _handler_satisfies_contract(node, lines):
                found.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    return found


def test_every_handler_reraises_persists_or_is_justified() -> None:
    violations = _violations()
    assert not violations, (
        "These handlers swallow an exception without re-raising, persisting it, "
        "or carrying a `# deliberate-swallow: <reason>` marker. Each one can "
        "hide a real failure with no symptom:\n  " + "\n  ".join(violations)
    )


def test_the_marker_requires_an_actual_reason() -> None:
    """A bare marker would turn the contract into a rubber stamp."""
    assert MARKER.search("# deliberate-swallow: batch loop, one bad row skipped")
    assert not MARKER.search("# deliberate-swallow:")
    assert not MARKER.search("# deliberate-swallow:   ")
