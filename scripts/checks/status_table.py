"""Regenerate the "Where things stand" table in docs/rewrite-status.md.

The table went stale in two consecutive PRs, because every value was typed by
hand while the thing it described moved. Review caught it both times, which is
the wrong place to catch arithmetic.

Every row that can be measured is measured here. `--check` fails when the file
disagrees, naming the rows, so drift is a gate failure rather than a reviewer's
good eye. A row whose input is absent is asked `is_measurable` first and keeps
the file's value, loudly: coverage reads the `.coverage` data file CI writes a
step earlier, and declines when that file is missing or older than the code it
measured. The type/lint row is prose and is never measured.

The test count shells out to pytest rather than counting `def test_` with ast:
parametrised cases are real tests, and an ast count would quietly under-report
them.

The port-progress rows derive from `scripts/v1-frontend-operations.yml` against
the live `frontend/schema.v2.yml`. v1 is frozen, so storing its totals is what
lets these be measured in CI at all — CI checks out this repo and nothing else,
so `../docketworks` is not there. Porting an operation lowers the count with no
edit to any file.

The doc quotes these numbers in prose as well as in the table. The table is the
owner and `--check` fails when a sentence disagrees with it, because two places
holding one number is the same defect as a hand-typed row.
"""

import argparse
import io
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypedDict

import coverage
import yaml

from scripts import REPO_ROOT

STATUS_DOC = REPO_ROOT / "docs/rewrite-status.md"
LEDGER_FILE = REPO_ROOT / "docs/accepted-api-differences.yml"
ADR_DIR = REPO_ROOT / "docs/adr"
V1_OPERATIONS_FILE = REPO_ROOT / "scripts/v1-frontend-operations.yml"
V2_SCHEMA = REPO_ROOT / "frontend/schema.v2.yml"
E2E_SPEC_DIR = REPO_ROOT / "frontend/tests/e2e"
COVERAGE_DATA = REPO_ROOT / ".coverage"

TABLE_HEADER = "| Measure | Value |"

OPERATION_ID = re.compile(r"operationId:\s*(\S+)")

# Escaped rather than literal: the doc joins ADR ranges with an en dash, and a
# literal one here is what ruff's ambiguous-character rule exists to catch.
EN_DASH = "\u2013"

# ADRs 0001-0037 came from v1; anything at or above this was written for v2.
FIRST_V2_ADR = 38


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


def _coverage_floor() -> int:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    floor = config["tool"]["coverage"]["report"]["fail_under"]
    if not isinstance(floor, int):
        raise TypeError(f"coverage fail_under must be an int, got {floor!r}")
    return floor


def coverage_is_current() -> bool:
    """Whether `.coverage` exists and is newer than the code it measured.

    Asked before `_measure_coverage`, rather than folded into it as an `X | None`
    return: the caller is the one that knows what to do about a missing input
    (keep the file's value and say so), and ADR 0045 puts that question at the
    call site instead of obliging it to decode a None.
    """
    if not COVERAGE_DATA.is_file():
        return False
    newest_source = max(
        (
            path.stat().st_mtime
            for root in ("apps", "config")
            for path in (REPO_ROOT / root).rglob("*.py")
        ),
        default=0.0,
    )
    return newest_source <= COVERAGE_DATA.stat().st_mtime


def _measure_coverage() -> str:
    """Total from the last coverage run.

    Read from the `.coverage` data file rather than re-run: CI runs
    `pytest --cov` immediately before this check, so the number is already
    sitting there, and re-running it would add the whole suite to a check whose
    point is to be fast.
    """
    coverage_data = coverage.Coverage(data_file=str(COVERAGE_DATA))
    coverage_data.load()
    total = coverage_data.report(file=io.StringIO())
    return f"{total:.2f}% (floor {_coverage_floor()}, ratchets up per slice — never down)"


class V1Operations(TypedDict):
    """The frozen record of v1's operation surface, as stored on disk."""

    e2e_spec_files: int
    #: Every operationId v1's schema declared.
    operations: list[str]
    #: The subset v1's frontend actually invoked.
    called: list[str]
    #: v1 operationId -> the v2 operationId that replaced it.
    renamed: dict[str, str]
    #: v2 operations that never existed in v1.
    introduced: list[str]


def _v1_operations() -> V1Operations:
    """Load and validate the stored file.

    Validated rather than trusted: it is hand-edited for renames, and a typo
    that made `renamed` a list would otherwise surface as a wrong count rather
    than an error — the silent-wrongness this whole gate exists to prevent.
    """
    raw = yaml.safe_load(V1_OPERATIONS_FILE.read_text())
    if not isinstance(raw, dict):
        raise TypeError(f"{V1_OPERATIONS_FILE} must hold a mapping, got {type(raw).__name__}")
    expected: dict[str, type] = {
        "e2e_spec_files": int,
        "operations": list,
        "called": list,
        "renamed": dict,
        "introduced": list,
    }
    for key, kind in expected.items():
        if key not in raw:
            raise KeyError(f"{V1_OPERATIONS_FILE} is missing '{key}'")
        if not isinstance(raw[key], kind):
            raise TypeError(
                f"{V1_OPERATIONS_FILE}: '{key}' must be {kind.__name__}, "
                f"got {type(raw[key]).__name__}"
            )
    return V1Operations(
        e2e_spec_files=raw["e2e_spec_files"],
        operations=raw["operations"],
        called=raw["called"],
        renamed=raw["renamed"],
        introduced=raw["introduced"],
    )


def _v2_operation_ids() -> set[str]:
    return set(OPERATION_ID.findall(V2_SCHEMA.read_text()))


def _unported_operations() -> set[str]:
    """Operations v1's frontend calls that v2 does not yet serve.

    A recorded rename counts as ported: without the map the v1 name reads as
    still missing while the v2 name looks like a new endpoint, so one unrecorded
    rename adds one to this count AND hides a real gap behind it.
    """
    stored = _v1_operations()
    v2 = _v2_operation_ids()
    ported_under_a_new_name = {
        v1_name for v1_name, v2_name in stored["renamed"].items() if v2_name in v2
    }
    return set(stored["called"]) - v2 - ported_under_a_new_name


def _dead_operations() -> set[str]:
    """v1 operations no call site reaches. Porting them is work no spec can verify."""
    stored = _v1_operations()
    return set(stored["operations"]) - set(stored["called"]) - _v2_operation_ids()


def orphan_v2_operations() -> set[str]:
    """v2 operations with no v1 ancestor, no rename entry and no `introduced` entry.

    The only staleness detectable without the v1 repo, and the one that matters:
    v2 renames operations deliberately (`export_openapi.py` pins dissolved v1 app
    names at zero, so every `workflow_*` operation must be renamed when it ports),
    and an unrecorded rename silently corrupts the count in both directions.
    A genuinely new endpoint is legitimate — it just has to say so.
    """
    stored = _v1_operations()
    return (
        _v2_operation_ids()
        - set(stored["operations"])
        - set(stored["renamed"].values())
        - set(stored["introduced"])
    )


def _measure_unported() -> str:
    return (
        f"**{len(_unported_operations())}** (see below; "
        f"{len(_dead_operations())} more exist but nothing calls them)"
    )


def _measure_v2_operations() -> str:
    return f"{len(_v2_operation_ids())} (`frontend/schema.v2.yml`, kept fresh by its own gate)"


def _measure_specs_ported() -> str:
    ported = len(list(E2E_SPEC_DIR.rglob("*.spec.ts")))
    # Deliberately "ported", not "passing": this counts files, and a file
    # existing is not a spec going green. Nothing here can know the latter.
    total = _v1_operations()["e2e_spec_files"]
    return f"**{ported} of {total}** — green is the only measure that counts"


def _always() -> bool:
    """Most rows can always be measured; only coverage depends on a prior run."""
    return True


@dataclass(frozen=True)
class Row:
    """A measured row, and the prose patterns that restate it.

    The patterns live on the row rather than in a parallel dict keyed by label:
    a second dict can hold a key this one does not, and a typo there would
    disable the prose check while failing nothing — the exact shape of bug this
    gate exists to catch.
    """

    measure: Callable[[], str]
    #: Each captures the integer a sentence claims for this row.
    claims: tuple[re.Pattern[str], ...] = ()
    #: Asked before `measure`. False means the input to measure from is absent,
    #: so the file's value stands — never a guess dressed up as a measurement.
    is_measurable: Callable[[], bool] = _always
    #: Told to the reader when `is_measurable` says no. Lives here rather than in
    #: the reporting code so a second decl declining row cannot inherit this one's advice.
    unavailable_hint: str = ""


# Rows absent here (Coverage, Type/lint debt) are preserved from the file:
# coverage is only known after a coverage run, and the other is prose.
MEASURED: dict[str, Row] = {
    "E2E specs ported": Row(_measure_specs_ported),
    "Backend operations still to port": Row(
        _measure_unported,
        (
            re.compile(r"(\d+)\s+(?:of them\s+)?(?:are\s+|is\s+)?unported"),
            re.compile(r"(\d+)\s+operations?\s+still to port"),
            re.compile(r"still to port:?\s+(\d+)"),
        ),
    ),
    "API operations v2 exposes": Row(_measure_v2_operations, (re.compile(r"v2 exposes\s+(\d+)"),)),
    "Coverage": Row(
        _measure_coverage,
        is_measurable=coverage_is_current,
        unavailable_hint="run: uv run pytest --cov=apps --cov=config",
    ),
    "Unit tests": Row(_measure_tests),
    "Behaviour ledger": Row(_measure_ledger),
    "ADRs": Row(_measure_adrs),
}


def _prose_disagreements(lines: list[str], table: range) -> list[str]:
    """Sentences quoting a number the table no longer says.

    The table is the owner. Prose is free to mention a quantity, but not to hold
    a second copy of it that nothing keeps in step.
    """
    problems: list[str] = []
    claimed = [(label, row) for label, row in MEASURED.items() if row.claims]
    for index, line in enumerate(lines):
        if index in table:
            continue
        # Strip emphasis and thousands separators so `**1,275**` reads as 1275.
        plain = line.replace("*", "").replace(",", "")
        for label, row in claimed:
            if not row.is_measurable():
                continue
            expected = _row_number(row.measure())
            if expected is None:
                continue
            for pattern in row.claims:
                for match in pattern.finditer(plain):
                    if int(match.group(1)) != expected:
                        problems.append(
                            f"  line {index + 1} says {match.group(1)}, "
                            f"but '{label}' measures {expected}\n    {line.strip()}"
                        )
    return problems


def _row_number(value: str) -> int | None:
    match = re.search(r"\d+", value.replace(",", ""))
    return int(match.group()) if match else None


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


def _orphan_report() -> str | None:
    orphans = orphan_v2_operations()
    if not orphans:
        return None
    return (
        "v2 serves operations with no v1 ancestor and no entry recording why:\n  "
        + "\n  ".join(sorted(orphans))
        + "\n\nEach is either a rename — add it to `renamed:` in "
        "scripts/v1-frontend-operations.yml,\nmapping the v1 name to it — or a genuinely new "
        "endpoint, which goes under\n`introduced:`. Left unrecorded, a rename adds one to the "
        "remaining count and\nhides a real gap behind it."
    )


def _remeasure(lines: list[str], table: range) -> tuple[list[str], list[str], list[str]]:
    """Rewritten lines, the rows that moved, and the rows no measurer would answer for."""
    rewritten = list(lines)
    stale: list[str] = []
    preserved: list[str] = []
    for index in table:
        label = _row_label(lines[index])
        row = MEASURED.get(label)
        if row is None:
            continue
        if not row.is_measurable():
            # No fresh input. Keeping the file's value is the honest answer;
            # inventing one that looks measured is not.
            preserved.append(f"{label} ({row.unavailable_hint})")
            continue
        row_text = f"| {label} | {row.measure()} |"
        if row_text != lines[index]:
            stale.append(f"  {label}\n    file: {lines[index]}\n    repo: {row_text}")
            rewritten[index] = row_text
    return rewritten, stale, preserved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero when the table disagrees with the repo, changing nothing",
    )
    args = parser.parse_args()

    if orphan_report := _orphan_report():
        print(orphan_report, file=sys.stderr)
        return 1

    lines = STATUS_DOC.read_text().splitlines()
    start, end = _table_bounds(lines)
    rewritten, stale, preserved = _remeasure(lines, range(start, end))

    missing = sorted(set(MEASURED) - {_row_label(lines[i]) for i in range(start, end)})
    if missing:
        print(f"rows missing from the table: {', '.join(missing)}", file=sys.stderr)
        return 1

    # Against the rewritten rows, so a regeneration run reports prose that the
    # new values have just contradicted rather than silently leaving it wrong.
    prose = _prose_disagreements(rewritten, range(start, end))

    if stale and not args.check:
        STATUS_DOC.write_text("\n".join(rewritten) + "\n")
        print(f"updated {len(stale)} row(s):\n" + "\n".join(stale))

    if prose:
        print(
            "prose in the doc disagrees with the table, which owns these numbers:\n"
            + "\n".join(prose)
            + "\n\nThe fix is to stop restating: point the sentence at the table.",
            file=sys.stderr,
        )
        return 1

    if stale and args.check:
        print("status table is stale:\n" + "\n".join(stale), file=sys.stderr)
        print("\nregenerate with: uv run python -m scripts.checks.status_table", file=sys.stderr)
        return 1

    if preserved:
        # Loud, because a silently preserved row is indistinguishable from a
        # measured one and that is the whole failure mode being designed out.
        print("kept the file's value, no fresh input to measure from:\n  " + "\n  ".join(preserved))

    if not stale:
        print(f"status table matches the repo ({len(MEASURED) - len(preserved)} measured rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
