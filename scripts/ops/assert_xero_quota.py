#!/usr/bin/env python
"""Refuse a long run that Xero's remaining day quota cannot carry.

The unattended E2E gate takes about half an hour and spends Xero calls from
its first step (the cleanup that removes the previous run's writes) to its
last. Started with too little quota, it fails partway through, after the
half hour, on whichever call Xero refuses first. One call spent here moves
that refusal to before the run.

The reading is a real call rather than the recorder's freshest header
(``quota_floor_breached``) because a preflight needs the quota NOW: the last
recorded reading may be hours old, or from before another consumer of the
same tenant spent the day.

A token or network failure propagates and stops the run: a preflight that
cannot answer must not be read as "probably fine".

Usage:
    uv run python -m scripts.ops.assert_xero_quota --min 150   # refuse at or below 150
    uv run python -m scripts.ops.assert_xero_quota             # report only
"""

import argparse
import sys

from scripts.bootstrap import setup_django

setup_django()

from apps.xero.quota import read_day_quota  # noqa: E402 -- Django must be configured first


def main() -> int:
    """Print the connected tenant and its quota; with ``--min``, refuse at or below it."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--min",
        type=int,
        help="refuse when the remaining daily calls are at or below this many",
    )
    args = parser.parse_args()

    reading = read_day_quota()
    print(
        f"Xero quota: {reading.organisation_name}, {reading.day_remaining} daily calls"
        f" remaining ({reading.minute_remaining} this minute)."
    )
    if args.min is not None and reading.day_remaining <= args.min:
        print(
            f"Refusing to start: Xero daily quota {reading.day_remaining} is at or below"
            f" the {args.min} this run needs.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
