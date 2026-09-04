"""Report where this database is thinner than production.

A screen's volume-sensitive behaviour — clipping at the fold, paging, query
count per row, response size — is invisible against a handful of rows. So a
suite run against a thin corpus can be green and prove nothing about the
screen production actually renders. This names the tables where that is true
right now, against the counts committed in ``docs/prod-data-shape.yml``.

It reports rather than fails. Thirteen tables were short of production the day
it was written, so failing would have baselined the number instead of showing
it moving — and a suite that refuses to run is a suite people stop running.
Making a single surface representative is the work; the ADR 0054 rule is that
the spec asserting a volume-sensitive property checks its own table here.
"""

import argparse
import sys
from pathlib import Path

import django
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SHAPE_FILE = REPO_ROOT / "docs" / "prod-data-shape.yml"

# Opus: Below this, a table is too small for its own count to say anything: a lookup
# table with five rows in production is not "thin" in the local copy.
MEANINGFUL_ROWS = 50
# Opus: Half of production is the line between "the same order of magnitude" and a
# corpus that cannot exercise what production does.
THIN_FRACTION = 0.5


def _local_counts() -> dict[str, int]:
    """Count every project model in the database this process is pointed at."""
    from django.apps import apps

    counts: dict[str, int] = {}
    for model in apps.get_models():
        if not model._meta.app_config.name.startswith("apps."):
            continue
        counts[f"{model._meta.app_label}.{model.__name__}"] = model._default_manager.count()
    return counts


def main() -> int:
    """Print the tables this database holds too few rows of to be representative."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quiet-when-representative",
        action="store_true",
        help="Print nothing when no table is thin, for use as a run preamble.",
    )
    args = parser.parse_args()

    if not SHAPE_FILE.exists():
        raise SystemExit(f"No committed production shape at {SHAPE_FILE}")

    shape = yaml.safe_load(SHAPE_FILE.read_text())
    production: dict[str, int] = shape["counts"]

    sys.path.insert(0, str(REPO_ROOT))
    import os

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
    local = _local_counts()

    thin = [
        (produced / max(local.get(label, 0), 1), label, local.get(label, 0), produced)
        for label, produced in production.items()
        if produced >= MEANINGFUL_ROWS and local.get(label, 0) < produced * THIN_FRACTION
    ]
    thin.sort(reverse=True)

    if not thin:
        if not args.quiet_when_representative:
            print(f"[shape] every table is within half of {shape['instance']}.")
        return 0

    print(
        f"[shape] {len(thin)} table(s) hold too little to exercise what "
        f"{shape['instance']} renders (captured {shape['captured_at']}):"
    )
    for ratio, label, here, produced in thin:
        print(
            f"[shape]   {label:<42} {here:>7} here vs {produced:>7} in production  ({ratio:.0f}x)"
        )
    print("[shape] A spec asserting a volume-sensitive property on one of these owns")
    print("[shape] seeding it to production volume first (ADR 0054).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
