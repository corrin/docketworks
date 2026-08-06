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
from collections import defaultdict
from enum import Enum
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

    Only MODULE-LEVEL imports count, and any later rebinding of the name
    disqualifies it everywhere in the file. Collecting imports from anywhere
    let one function's nested import bless the name for every handler in the
    module, and let a local ``def persist_app_error(*a): pass`` satisfy the
    gate while calling nothing. Being conservative here costs an import moved
    to the top of a file; being permissive costs the gate.
    """
    aliases = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "apps.core.errors"
        for alias in node.names
        if alias.name == "persist_app_error"
    }
    return frozenset(aliases - _rebound_names(tree, aliases))


def _rebound_names(tree: ast.Module, names: set[str]) -> set[str]:
    """Names from `names` that anything in the file binds to something else."""
    rebound = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if node.name in names:
                rebound.add(node.name)
        elif isinstance(node, ast.Assign):
            rebound |= {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name) and target.id in names
            }
        elif isinstance(node, ast.ImportFrom) and node not in tree.body:
            rebound |= {alias.asname or alias.name for alias in node.names} & names
    return rebound


def _is_persist_call(value: ast.expr, aliases: frozenset[str]) -> bool:
    """A direct call to the imported helper — never a method on some object."""
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id in aliases
    )


class Outcome(Enum):
    """What a statement (or block) does to the exception being handled."""

    HANDLED = "handled"  # raises or persists: this path is accounted for
    ESCAPES = "escapes"  # leaves the handler without doing either
    CONTINUES = "continues"  # neither yet; execution reaches the next statement


def _always_handles(body: list[ast.stmt], aliases: frozenset[str]) -> bool:
    """Whether EVERY path through these statements raises or persists."""
    return _block_outcome(body, aliases) is Outcome.HANDLED


def _block_outcome(body: list[ast.stmt], aliases: frozenset[str]) -> Outcome:
    """Fold the statements in order, stopping at the first conclusive one.

    A boolean "does any statement handle it" was not enough, and failed the
    same way the original ``ast.walk`` did — one level up. It accepted::

        except Exception as exc:
            if retry:
                return None        # <- this path drops the exception
            persist_app_error(exc, ...)

    because a later statement handled it. An early exit has to END the path,
    which needs three outcomes rather than two: reaching a ``return`` before a
    handling statement is a swallow no matter what follows it.
    """
    for statement in body:
        outcome = _statement_outcome(statement, aliases)
        if outcome is not Outcome.CONTINUES:
            return outcome
    # Ran off the end: the exception was neither re-raised nor persisted.
    return Outcome.CONTINUES


def _statement_outcome(statement: ast.stmt, aliases: frozenset[str]) -> Outcome:  # noqa: PLR0911 -- one branch per statement kind
    """What this one statement does. Nested def/class/lambda are never entered.

    A ``raise`` inside a function nobody calls proves nothing, so those bodies
    are not examined at all.
    """
    if isinstance(statement, ast.Raise):
        return Outcome.HANDLED
    if isinstance(statement, ast.Expr | ast.Assign):
        return Outcome.HANDLED if _is_persist_call(statement.value, aliases) else Outcome.CONTINUES
    if isinstance(statement, ast.Return | ast.Break | ast.Continue):
        return Outcome.ESCAPES
    if isinstance(statement, ast.If):
        return _branch_outcome(statement.body, statement.orelse, aliases)
    if isinstance(statement, ast.With | ast.AsyncWith):
        return _block_outcome(statement.body, aliases)
    if isinstance(statement, ast.For | ast.AsyncFor | ast.While):
        # The body may run zero times, so it can never prove HANDLED — but a
        # `return` inside it still escapes.
        inner = _block_outcome(statement.body, aliases)
        return Outcome.ESCAPES if inner is Outcome.ESCAPES else Outcome.CONTINUES
    if isinstance(statement, ast.Try):
        return _try_outcome(statement, aliases)
    return Outcome.CONTINUES


def _branch_outcome(
    body: list[ast.stmt], orelse: list[ast.stmt], aliases: frozenset[str]
) -> Outcome:
    """Combine two arms.

    An `if` with no `else` whose body escapes reports ESCAPES even though the
    untaken path continues: the question is whether ANY path leaves without
    handling, and one that does is a swallow regardless of how often it runs.
    """
    taken = _block_outcome(body, aliases)
    if not orelse:
        return Outcome.ESCAPES if taken is Outcome.ESCAPES else Outcome.CONTINUES
    other = _block_outcome(orelse, aliases)
    if taken is Outcome.HANDLED and other is Outcome.HANDLED:
        return Outcome.HANDLED
    if Outcome.ESCAPES in (taken, other):
        return Outcome.ESCAPES
    return Outcome.CONTINUES


def _try_outcome(statement: ast.Try, aliases: frozenset[str]) -> Outcome:
    """An inner try/finally, where `finally` has the last word.

    `finally: return` discards an exception propagating out of the try — even
    the bare `raise` in the block above it — so it escapes regardless of what
    the body did.
    """
    if statement.finalbody and _block_outcome(statement.finalbody, aliases) is Outcome.ESCAPES:
        return Outcome.ESCAPES
    arms = [statement.body, *(handler.body for handler in statement.handlers)]
    outcomes = [_block_outcome(arm, aliases) for arm in arms]
    if all(outcome is Outcome.HANDLED for outcome in outcomes):
        return Outcome.HANDLED
    if Outcome.ESCAPES in outcomes:
        return Outcome.ESCAPES
    return Outcome.CONTINUES


def _has_marker(node: ast.ExceptHandler, lines: list[str]) -> bool:
    """Whether a marker sits on the `except` line or in the comments above it.

    Python discards comments before the AST exists, so source text is the only
    place this can be read from — there is no AST-attached alternative.

    The whole contiguous comment block counts, not just the line immediately
    above. A reason worth writing rarely fits on one line, and requiring the
    marker to be last would put the conclusion before its argument.
    """
    if MARKER.search(lines[node.lineno - 1]):
        return True
    for lineno in range(node.lineno - 1, 0, -1):
        line = lines[lineno - 1].strip()
        if not line.startswith("#"):
            return False
        if MARKER.search(line):
            return True
    return False


def _handler_satisfies_contract(
    node: ast.ExceptHandler, lines: list[str], aliases: frozenset[str]
) -> bool:
    return _always_handles(node.body, aliases) or _has_marker(node, lines)


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


def _reasons_by_text(root: Path, base: Path) -> dict[str, list[str]]:
    """Every marker reason under `root`, mapped to the sites carrying it.

    `base` is what site labels are reported relative to, and is passed rather
    than assumed: hard-coding REPO_ROOT made this raise for any tree outside
    the repo, so the rule could only ever be run against the real one.
    Whitespace is collapsed so that re-indenting a copied marker does not
    launder it into a distinct reason.
    """
    sites: dict[str, list[str]] = defaultdict(list)
    for path in sorted(root.rglob("*.py")):
        if any(part in str(path) for part in EXCLUDED_PARTS):
            continue
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            match = MARKER.search(line)
            if match:
                reason = " ".join(match.group("reason").split())
                sites[reason].append(f"{path.relative_to(base)}:{number}")
    return sites


def test_each_marker_reason_is_written_for_its_own_handler() -> None:
    """A reason reused verbatim is evidence nobody read the second site.

    The marker's whole value is that someone looked at THIS handler and decided
    the swallow was right. A sentence that applies word-for-word to six
    different handlers cannot be that, and reviewing prose cannot catch it —
    each site looks considered on its own. Duplication is the mechanical
    signature, so it is what the gate checks.

    Two handlers that genuinely share a reason are a hint they should share a
    helper; if they truly must differ, say what differs.
    """
    reused = {
        reason: sites
        for reason, sites in _reasons_by_text(APPS, REPO_ROOT).items()
        if len(sites) > 1
    }
    assert not reused, (
        "These marker reasons are reused verbatim, so they describe no "
        "site in particular. Give each the fact that justifies THAT handler:\n"
        + "\n".join(
            f"  {len(sites)}x {reason!r}\n" + "\n".join(f"      {site}" for site in sites)
            for reason, sites in sorted(reused.items(), key=lambda item: -len(item[1]))
        )
    )


def test_the_uniqueness_rule_catches_a_reason_used_twice(tmp_path: Path) -> None:
    (tmp_path / "one.py").write_text("# deliberate-swallow: the portal omits it\n")
    (tmp_path / "two.py").write_text("# deliberate-swallow: the portal omits it\n")
    reused = {r: s for r, s in _reasons_by_text(tmp_path, tmp_path).items() if len(s) > 1}
    assert len(reused) == 1
    assert len(next(iter(reused.values()))) == 2


def test_whitespace_alone_does_not_make_a_reason_distinct(tmp_path: Path) -> None:
    """Otherwise re-indenting a copied marker would launder it past the rule."""
    (tmp_path / "one.py").write_text("# deliberate-swallow: the portal omits it\n")
    (tmp_path / "two.py").write_text("#   deliberate-swallow:  the   portal omits it\n")
    assert any(len(sites) > 1 for sites in _reasons_by_text(tmp_path, tmp_path).values())


def test_distinct_reasons_pass(tmp_path: Path) -> None:
    (tmp_path / "one.py").write_text("# deliberate-swallow: the portal omits it on plain rows\n")
    (tmp_path / "two.py").write_text("# deliberate-swallow: a spacer row carries neither cell\n")
    assert all(len(sites) == 1 for sites in _reasons_by_text(tmp_path, tmp_path).values())


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
    # Found by the second review round: handling LATER does not rescue a path
    # that already left, and a name is only the helper if nothing rebinds it.
    "early return before a later persist": IMPORT + "try: pass\nexcept Exception as exc:\n"
    "    if retry:\n        return None\n    persist_app_error(exc, None)\n",
    "finally-return suppressing the raise above it": "try: pass\nexcept Exception:\n"
    "    try:\n        raise\n    finally:\n        return None\n",
    "break inside a loop before persisting": IMPORT + "try: pass\nexcept Exception as exc:\n"
    "    for _ in items:\n        break\n",
    "local def shadowing the imported helper": IMPORT + "def outer():\n"
    "    def persist_app_error(*a): pass\n    try: pass\n"
    "    except Exception as exc:\n        persist_app_error(exc, None)\n",
    "nested import blessing another function": "def other():\n"
    "    from apps.core.errors import persist_app_error\n"
    "def g():\n    try: pass\n    except Exception as exc:\n"
    "        persist_app_error(exc, None)\n",
}


@pytest.mark.parametrize("source", SATISFIED.values(), ids=list(SATISFIED))
def test_satisfying_handlers_pass(source: str) -> None:
    assert _check(source)


@pytest.mark.parametrize("source", VIOLATIONS.values(), ids=list(VIOLATIONS))
def test_swallowing_handlers_fail(source: str) -> None:
    assert not _check(source)
