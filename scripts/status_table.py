"""Regenerate the "Where things stand" table in docs/rewrite-status.md.

The table went stale in two consecutive PRs — claiming 176 contract gaps while
the gaps file held 152, and 1245 tests while the suite collected 1273 — because
every value was typed by hand while the thing it described moved. Review caught
it both times, which is the wrong place to catch arithmetic.

Every row that can be measured is measured here. `--check` fails when the file
disagrees, naming the rows, so drift is a gate failure rather than a reviewer's
good eye. Rows that cannot be derived from the repo (coverage needs a coverage
run; the type/lint row is prose) are preserved verbatim from the file.

Measurements reuse schema_parity_diff rather than reimplementing the parity walk
— one implementation per concept (ADR 0039). That is also why the test count
shells out to pytest instead of counting `def test_` with ast: parametrised
cases are real tests, and an ast count would quietly under-report them.
"""

import argparse
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.schema_parity_diff import (  # noqa: E402  (needs REPO_ROOT on sys.path)
    _contract_gaps,
    _ledgered_operations,
    _operations,
    _v1_spec,
    _v2_spec,
)

STATUS_DOC = REPO_ROOT / "docs/rewrite-status.md"
LEDGER_FILE = REPO_ROOT / "docs/accepted-api-differences.yml"
ADR_DIR = REPO_ROOT / "docs/adr"

TABLE_HEADER = "| Measure | Value |"

# Escaped rather than literal: the doc joins ADR ranges with an en dash, and a
# literal one here is what ruff's ambiguous-character rule exists to catch.
EN_DASH = "\u2013"

# ADRs 0001-0037 came from v1; anything at or above this was written for v2.
FIRST_V2_ADR = 38


def _measure_operations() -> str:
    """`N of M` ported, counted the way the parity gate counts them."""
    v1 = _operations(_v1_spec())
    v2 = _operations(_v2_spec())
    ledgered = _ledgered_operations()
    matched = {op for op in v1 if op in v2}
    unported = {op for op in v1 if op not in v2 and op not in ledgered}
    return (
        f"**{len(matched)} of {len(matched) + len(unported)}** "
        "(parity diff, drift 0, ratcheting baseline)"
    )


def _measure_tests() -> str:
    """Collected test count, including parametrised cases."""
    # No -q here: pyproject's addopts already supplies one, and a second turns
    # the summary line into a per-file breakdown with no total to read.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pytest collection failed:\n{result.stdout}\n{result.stderr}")
    match = re.search(r"(\d+) tests? collected", result.stdout)
    if match is None:
        raise RuntimeError(f"no collection count in pytest output:\n{result.stdout}")
    return f"{match.group(1)} (all passing)"


def _measure_contract_gaps() -> str:
    """Live gap count by kind, so the headline cannot disagree with the body."""
    gaps = _contract_gaps(_v1_spec(), _v2_spec())
    by_kind: dict[str, int] = {}
    for gap in gaps:
        by_kind[gap.split(" ", 1)[0]] = by_kind.get(gap.split(" ", 1)[0], 0) + 1
    zeroed = sorted(k for k in ("uuid", "nullable", "required") if not by_kind.get(k))
    remaining = ", ".join(f"`{k}` {n}" for k, n in sorted(by_kind.items()))
    detail = f"{remaining}" if remaining else "all categories at zero"
    if zeroed:
        detail = f"{', '.join(f'`{k}`' for k in zeroed)} at zero; {detail}"
    return (
        f"**{len(gaps)}**, ratcheting to zero "
        f"(`scripts/schema-contract-gaps.txt`, ADR 0044). {detail}"
    )


def _measure_ledger() -> str:
    entries = yaml.safe_load(LEDGER_FILE.read_text())
    return f"{len(entries)} recorded deviations"


def _measure_adrs() -> str:
    numbered = [p for p in ADR_DIR.glob("*.md") if re.match(r"^\d{4}-", p.name)]
    written_here = sorted(int(p.name[:4]) for p in numbered if int(p.name[:4]) >= FIRST_V2_ADR)
    carried = len(numbered) - len(written_here)
    spans: list[str] = []
    for number in written_here:
        if spans and int(spans[-1].split(EN_DASH)[-1]) == number - 1:
            spans[-1] = f"{spans[-1].split(EN_DASH)[0]}{EN_DASH}{number:04d}"
        else:
            spans.append(f"{number:04d}")
    return f"{len(numbered)} (v1's {carried} carried forward + {', '.join(spans)} written here)"


# Rows absent here (Coverage, Type/lint debt) are preserved from the file:
# coverage is only known after a coverage run, and the other is prose.
MEASURED: dict[str, Callable[[], str]] = {
    "API operations ported": _measure_operations,
    "Tests": _measure_tests,
    "Contract gaps vs v1": _measure_contract_gaps,
    "Parity ledger": _measure_ledger,
    "ADRs": _measure_adrs,
}


def _table_bounds(lines: list[str]) -> tuple[int, int]:
    """Line range of the table body, exclusive of header and separator."""
    try:
        header = lines.index(TABLE_HEADER)
    except ValueError as exc:
        raise RuntimeError(f"{STATUS_DOC} has no {TABLE_HEADER!r} row") from exc
    start = header + 2  # skip the |---|---| separator
    end = start
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    return start, end


def _row_label(line: str) -> str:
    return line.split("|")[1].strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero when the table disagrees with the repo, changing nothing",
    )
    args = parser.parse_args()

    lines = STATUS_DOC.read_text().splitlines()
    start, end = _table_bounds(lines)
    stale: list[str] = []
    rewritten = list(lines)

    for index in range(start, end):
        label = _row_label(lines[index])
        measure = MEASURED.get(label)
        if measure is None:
            continue
        value = measure()
        row = f"| {label} | {value} |"
        if row != lines[index]:
            stale.append(f"  {label}\n    file: {lines[index]}\n    repo: {row}")
            rewritten[index] = row

    missing = sorted(set(MEASURED) - {_row_label(lines[i]) for i in range(start, end)})
    if missing:
        print(f"rows missing from the table: {', '.join(missing)}", file=sys.stderr)
        return 1

    if not stale:
        print(f"status table matches the repo ({len(MEASURED)} measured rows)")
        return 0

    if args.check:
        print("status table is stale:\n" + "\n".join(stale), file=sys.stderr)
        print("\nregenerate with: uv run python scripts/status_table.py", file=sys.stderr)
        return 1

    STATUS_DOC.write_text("\n".join(rewritten) + "\n")
    print(f"updated {len(stale)} row(s):\n" + "\n".join(stale))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
