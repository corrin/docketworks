"""Measure codebase-quality metrics and write them to docs/code-quality.md.

The file is committed, so every movement shows up in a diff and has to be
explained in review. That is the enforcement: `--check` fails when the file
disagrees with the repo, which means a change that adds suppressions cannot land
without the number going up in front of a reviewer.

Deliberately NOT a shrink-only ratchet, except where noted. Some counts grow for
good reasons — a newly ported app brings legitimate DJ001s with it — and a gate
that blocks those trains people to work around it. Visibility is enforced;
direction is a conversation. The one exception is `passthrough`, which is zero
today and is always removable by inlining, so it is pinned.

Metrics measured here rather than counted by hand, because hand-counted figures
in this repo have been wrong every time they were checked: the status table was
stale in two consecutive PRs, and "0 malformed of 13,931 rows" was a stale
database measurement that re-running corrected to 26,684 rows.
"""

import argparse
import ast
import re
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from scripts import REPO_ROOT

TARGET = REPO_ROOT / "docs" / "code-quality.md"

PYTHON_ROOTS = ("apps", "config", "scripts")
FRONTEND_ROOTS = ("frontend/src", "frontend/tests")

#: Suppression forms, by the language that spells them that way. Counted with a
#: regex rather than the AST because comments are not in the tree at all.
PYTHON_SUPPRESSIONS = {
    "type: ignore": re.compile(r"#\s*type:\s*ignore"),
    "pragma: no cover": re.compile(r"#\s*pragma:\s*no cover"),
    "noqa (no rule code)": re.compile(r"#\s*noqa\s*(?![:\w])"),
}
FRONTEND_SUPPRESSIONS = {
    "@ts-ignore": re.compile(r"@ts-ignore"),
    "@ts-expect-error": re.compile(r"@ts-expect-error"),
    "eslint-disable": re.compile(r"eslint-disable"),
    "oxlint-disable": re.compile(r"oxlint-disable"),
}
NOQA_RULE = re.compile(r"#\s*noqa:\s*([A-Z]+[0-9]+)")


@dataclass
class Section:
    """One table in the report."""

    title: str
    note: str
    rows: list[tuple[str, int]] = field(default_factory=list)


def _python_files() -> Iterator[Path]:
    for root in PYTHON_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            if "migrations" not in path.parts:
                yield path


def _frontend_files() -> Iterator[Path]:
    for root in FRONTEND_ROOTS:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for suffix in ("*.ts", "*.tsx"):
            for path in sorted(base.rglob(suffix)):
                # Generated code is excluded by directory AND by the .gen.ts
                # filename convention: every @ts-ignore in this repo turned out to
                # live in hey-api output or routeTree.gen.ts, rewritten wholesale
                # on each codegen run. Counting them would measure the generator.
                if "node_modules" in path.parts or "generated" in path.parts:
                    continue
                if path.name.endswith((".gen.ts", ".gen.tsx")):
                    continue
                yield path


def measure_suppressions() -> Section:
    """Every way the codebase tells a checker to look away.

    The frontend is included because "zero type: ignore" was true of Python and
    read as a clean bill of health, while @ts-ignore sat uncounted next door.
    Generated client code is excluded: nobody chose those suppressions.
    """
    counts: Counter[str] = Counter()
    for path in _python_files():
        text = path.read_text()
        for label, pattern in PYTHON_SUPPRESSIONS.items():
            counts[label] += len(pattern.findall(text))
        for rule in NOQA_RULE.findall(text):
            counts[f"noqa: {rule}"] += 1
    for path in _frontend_files():
        text = path.read_text()
        for label, pattern in FRONTEND_SUPPRESSIONS.items():
            counts[label] += len(pattern.findall(text))

    # Rule-coded noqa sorted by weight, then the fixed labels, so the biggest
    # thing to work on is the first line you read.
    coded = sorted(
        ((k, v) for k, v in counts.items() if k.startswith("noqa: ")),
        key=lambda kv: (-kv[1], kv[0]),
    )
    fixed = [(k, counts.get(k, 0)) for k in (*PYTHON_SUPPRESSIONS, *FRONTEND_SUPPRESSIONS)]
    return Section(
        title="Suppressions",
        note=(
            "Every place a checker is told to look away. A bare `noqa` carries no "
            "rule code and is forbidden outright (CLAUDE.md); the count is here so "
            "that stays true rather than being assumed."
        ),
        rows=[*fixed, ("TOTAL suppressions", sum(counts.values())), *coded],
    )


def _body_without_docstring(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        return body[1:]
    return body


def _shim_kind(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Classify a function whose whole body is one single-statement try.

    What the handler CATCHES is what separates a legitimate one from a defect,
    and that judgement is not mechanical — so this counts shapes and leaves the
    reading to a human. An absence exception (DoesNotExist, NoSuchElementException)
    answered with None/False is the answer the predicate exists to give. A
    malformed-input exception (InvalidOperation, ValueError) answered with a
    default is the ADR 0015 smell: it reports "absent" and "corrupt" identically,
    which is exactly how a garbage rate multiplier came back as 1.00.
    """
    body = _body_without_docstring(node)
    if len(body) != 1 or not isinstance(body[0], ast.Try):
        return None
    block = body[0]
    if len(block.body) != 1 or block.finalbody or block.orelse or not block.handlers:
        return None

    kinds = set()
    for handler in block.handlers:
        if len(handler.body) != 1:
            return None
        stmt = handler.body[0]
        if isinstance(stmt, ast.Raise):
            kinds.add("passthrough" if stmt.exc is None else "rethrow")
        elif isinstance(stmt, ast.Return) and isinstance(
            stmt.value, ast.Constant | ast.Name | ast.Call | type(None)
        ):
            kinds.add("fallback")
        else:
            return None
    return kinds.pop() if len(kinds) == 1 else None


def _returns_optional(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True only when None is a member of the OUTERMOST union, beside a real type.

    A bare `-> None` is a procedure. `tuple[Company | None, ...]` returns a tuple
    and `Status[None] | Data` is the error envelope; neither ever returns None.
    Substring matching counted those and gave 130; treating a bare `-> None` as
    optional gave 275. Both were wrong.
    """
    annotation = node.returns
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        annotation = ast.parse(annotation.value, mode="eval").body
    if isinstance(annotation, ast.Subscript) and ast.unparse(annotation.value).endswith("Optional"):
        return True

    members: list[ast.expr] = []

    def flatten(expr: ast.expr) -> None:
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
            flatten(expr.left)
            flatten(expr.right)
        else:
            members.append(expr)

    flatten(annotation)
    has_none = any(isinstance(m, ast.Constant) and m.value is None for m in members)
    return has_none and len(members) > 1


def measure_code_shape() -> tuple[Section, Section]:
    """Shim shapes and optional returns, from one walk over every function."""
    shims: Counter[str] = Counter()
    optional_returns = 0
    functions = 0
    for path in _python_files():
        is_test = "tests" in path.parts or path.name.startswith("test_")
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            kind = _shim_kind(node)
            if kind is not None:
                shims[kind] += 1
            if is_test:
                continue
            functions += 1
            if _returns_optional(node):
                optional_returns += 1

    shape = Section(
        title="try/except shapes",
        note=(
            "Functions whose entire body is one single-statement `try`. "
            "`passthrough` re-raises and so the try is dead — it is pinned at zero, "
            "because inlining always removes it. `rethrow` reshapes an error at a "
            "boundary and is usually right. `fallback` returns a default and needs "
            "reading: legitimate when it catches *absence*, a defect when it catches "
            "*malformed input* and thereby reports the two identically."
        ),
        rows=[(k, shims.get(k, 0)) for k in ("passthrough", "rethrow", "fallback")],
    )
    returns = Section(
        title="Optional returns",
        note=(
            "Functions returning `X | None`, which moves a decision onto every "
            "caller — and there are always more callers than functions (ADR 0045). "
            "Existing sites are a post-cutover sweep, not a blocker."
        ),
        rows=[
            ("functions returning `X | None`", optional_returns),
            ("non-test functions", functions),
        ],
    )
    return shape, returns


def render(sections: list[Section]) -> str:
    lines = [
        "# Code quality metrics",
        "",
        "Generated by `uv run python -m scripts.checks.code_quality`.",
        "**Do not edit by hand** — the numbers are measured, and `--check` fails when",
        "this file disagrees with the repo.",
        "",
        "These are not all meant to be zero. They are here so that a change which",
        "moves one has to show that movement in its diff, rather than a reviewer",
        "having to notice. Only `passthrough` is pinned at zero.",
        "",
    ]
    for section in sections:
        lines += [f"## {section.title}", "", section.note, "", "| metric | count |", "|---|---:|"]
        # A metric name containing `|` (as `X | None` does) would otherwise be
        # read as a column separator and split the row.
        lines += [f"| {name.replace('|', '\\|')} | {count} |" for name, count in section.rows]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero when the committed file is out of date, writing nothing",
    )
    args = parser.parse_args()

    shape, returns = measure_code_shape()
    sections = [measure_suppressions(), shape, returns]
    report = render(sections)

    pinned = dict(shape.rows).get("passthrough", 0)
    if pinned:
        print(
            f"{pinned} passthrough try/except found; each is dead code that inlining "
            "removes. This one is pinned at zero.",
            file=sys.stderr,
        )
        return 1

    current = TARGET.read_text() if TARGET.exists() else ""
    if report == current:
        print(f"code quality metrics are current ({sum(len(s.rows) for s in sections)} measures)")
        return 0

    if args.check:
        print(
            f"{TARGET.relative_to(REPO_ROOT)} is out of date.\n"
            "Regenerate with: uv run python -m scripts.checks.code_quality",
            file=sys.stderr,
        )
        return 1

    TARGET.write_text(report)
    print(f"wrote {TARGET.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
