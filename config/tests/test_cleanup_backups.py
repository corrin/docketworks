"""Retention planning for the per-instance backups directory.

Pins that retention keeps exactly the most recent dumps, that a crashed
writer's ``.tmp`` leftovers are deleted, and that unmanaged names are neither
kept nor deleted.
"""

from datetime import datetime

from scripts.cleanup_backups import DAILY_RETENTION_COUNT, plan_retention

NOW = datetime(2026, 8, 29, 3, 0).astimezone()


def daily_names(days: int) -> list[str]:
    return [f"daily_202608{day:02d}.sql.gz" for day in range(1, days + 1)]


def test_dailies_beyond_the_retention_count_are_deleted() -> None:
    keep_sets, to_delete = plan_retention(daily_names(16), NOW)

    kept_dumps = sorted(keep_sets["daily"])
    assert len(kept_dumps) == DAILY_RETENTION_COUNT
    assert kept_dumps[0] == "daily_20260803.sql.gz"
    assert to_delete == ["daily_20260801.sql.gz", "daily_20260802.sql.gz"]


def test_monthlies_within_the_retention_count_are_kept() -> None:
    dumps = [f"monthly_2026{month:02d}.sql.gz" for month in range(1, 9)]

    keep_sets, to_delete = plan_retention(dumps, NOW)

    assert keep_sets["monthly"] == set(dumps)
    assert to_delete == []


def test_stale_tmp_leftovers_are_deleted() -> None:
    entries = ["daily_20260829.sql.gz", "daily_20260828.sql.gz.tmp", "monthly_202608.sql.gz.tmp"]

    _, to_delete = plan_retention(entries, NOW)

    assert to_delete == ["daily_20260828.sql.gz.tmp", "monthly_202608.sql.gz.tmp"]


def test_unmanaged_names_are_neither_kept_nor_deleted() -> None:
    keep_sets, to_delete = plan_retention(["restore.log", "adhoc-notes.txt"], NOW)

    assert keep_sets["other"] == {"restore.log", "adhoc-notes.txt"}
    assert to_delete == []
