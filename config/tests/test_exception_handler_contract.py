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

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
APPS = REPO_ROOT / "apps"

MARKER = re.compile(r"#\s*deliberate-swallow:\s*(?P<reason>\S.*)")

# Tests assert on raised exceptions and migrations are frozen historical
# records; neither is production error handling.
EXCLUDED_PARTS = ("/tests/", "/migrations/")


def _persist_aliases(tree: ast.Module) -> frozenset[str]:
    """Names bound to ``apps.core.errors.persist_app_error`` in this module.

    Matching the bare name would accept any ``obj.persist_app_error()`` on any
    unrelated object — a logger, a mock, a scraper helper — as proof the
    contract was met. The binding is what carries the meaning, so it is
    resolved from the import rather than assumed.
    """
    aliases = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module != "apps.core.errors":
            continue
        for alias in node.names:
            if alias.name == "persist_app_error":
                aliases.add(alias.asname or alias.name)
    return frozenset(aliases)


def _is_persist_call(value: ast.expr, aliases: frozenset[str]) -> bool:
    """A direct call to the imported helper — never a method on some object."""
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id in aliases
    )


def _always_handles(body: list[ast.stmt], aliases: frozenset[str]) -> bool:
    """Whether EVERY path through these statements raises or persists.

    Walking for any descendant ``raise`` was the original mistake: it accepted
    ``if retry: raise`` followed by ``return None``, where the return path
    drops the exception silently — the exact failure this gate exists to catch.
    Nested ``def``/``class``/``lambda`` bodies are not entered at all, because a
    ``raise`` inside a function nobody calls proves nothing.
    """
    return any(_statement_handles(statement, aliases) for statement in body)


def _statement_handles(statement: ast.stmt, aliases: frozenset[str]) -> bool:
    """Whether this one statement guarantees the exception is raised or persisted."""
    if isinstance(statement, ast.Raise):
        return True
    if isinstance(statement, ast.Expr | ast.Assign):
        return _is_persist_call(statement.value, aliases)
    if isinstance(statement, ast.If):
        # Only an if/else where BOTH branches handle is conclusive. An if
        # without else falls through, so the caller keeps scanning.
        return bool(statement.orelse) and all(
            _always_handles(branch, aliases) for branch in (statement.body, statement.orelse)
        )
    if isinstance(statement, ast.With | ast.AsyncWith):
        return _always_handles(statement.body, aliases)
    if isinstance(statement, ast.Try):
        # An inner try handles only if its own body does AND every one of its
        # handlers does; otherwise the inner except may swallow.
        return _always_handles(statement.body, aliases) and all(
            _always_handles(inner.body, aliases) for inner in statement.handlers
        )
    return False


def _handler_satisfies_contract(
    node: ast.ExceptHandler, lines: list[str], aliases: frozenset[str]
) -> bool:
    if _always_handles(node.body, aliases):
        return True
    # The marker may sit on the `except` line or the line above it. Python
    # discards comments before the AST exists, so the source text is the only
    # place this can be read from — there is no AST-attached alternative.
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
        tree = ast.parse(source)
        aliases = _persist_aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if not _handler_satisfies_contract(node, lines, aliases):
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


def _check(source: str) -> bool:
    """Run the contract over a single handler in `source`."""
    tree = ast.parse(source)
    aliases = _persist_aliases(tree)
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
    assert len(handlers) == 1, "fixture must contain exactly one handler"
    return _handler_satisfies_contract(handlers[0], source.splitlines(), aliases)


IMPORT = "from apps.core.errors import persist_app_error\n"

SATISFIED = {
    "bare re-raise": "try: pass\nexcept Exception:\n    raise\n",
    "chained re-raise": "try: pass\nexcept Exception as exc:\n    raise ValueError('x') from exc\n",
    "persists without re-raising": IMPORT + "try: pass\nexcept Exception as exc:\n"
    "    persist_app_error(exc, None)\n",
    "persists under an alias": "from apps.core.errors import persist_app_error as persist\n"
    "try: pass\nexcept Exception as exc:\n    persist(exc, None)\n",
    "both branches raise": "try: pass\nexcept Exception:\n"
    "    if retry:\n        raise\n    else:\n        raise RuntimeError('x')\n",
    "justified swallow": "try: pass\nexcept Exception:  # deliberate-swallow: one bad row skipped\n"
    "    pass\n",
}

VIOLATIONS = {
    "bare swallow": "try: pass\nexcept Exception:\n    pass\n",
    # Each of these passed the original ast.walk implementation.
    "conditional raise, other path returns": "try: pass\nexcept Exception:\n"
    "    if retry:\n        raise\n    return None\n",
    "raise inside an uncalled nested function": "try: pass\nexcept Exception:\n"
    "    def helper():\n        raise ValueError('never called')\n    return None\n",
    "persist_app_error method on an unrelated object": "try: pass\nexcept Exception:\n"
    "    logger.persist_app_error()\n    return None\n",
    "persist call not bound to the real import": "try: pass\nexcept Exception as exc:\n"
    "    persist_app_error(exc, None)\n",
    "marker with no reason": "try: pass\nexcept Exception:  # deliberate-swallow:\n    pass\n",
}


@pytest.mark.parametrize("source", SATISFIED.values(), ids=list(SATISFIED))
def test_satisfying_handlers_pass(source: str) -> None:
    assert _check(source)


@pytest.mark.parametrize("source", VIOLATIONS.values(), ids=list(VIOLATIONS))
def test_swallowing_handlers_fail(source: str) -> None:
    assert not _check(source)
