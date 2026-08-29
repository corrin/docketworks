"""Retention planning for the per-instance backups directory.

Pins the behaviour that replaced the release-commit ``.sha`` sidecar: a
kept dump keeps its ``.migrations.json`` sidecar, legacy ``.sha`` files are
managed-but-never-kept so one retention run clears them, and unmanaged
names are neither kept nor deleted.
"""

from datetime import datetime

from scripts.cleanup_backups import (
    DAILY_RETENTION_COUNT,
    paired_snapshot_name,
    plan_retention,
)

NOW = datetime(2026, 8, 29, 3, 0).astimezone()


def daily_names(days: int) -> list[str]:
    return [f"daily_202608{day:02d}.sql.gz" for day in range(1, days + 1)]


def test_kept_dumps_keep_their_snapshot_sidecars() -> None:
    dumps = daily_names(16)
    entries = dumps + [paired_snapshot_name(name) for name in dumps]

    keep_sets, to_delete = plan_retention(entries, NOW)

    kept_dumps = sorted(keep_sets["daily"])
    assert len(kept_dumps) == DAILY_RETENTION_COUNT
    assert kept_dumps[0] == "daily_20260803.sql.gz"
    assert keep_sets["daily_snapshot"] == {paired_snapshot_name(n) for n in kept_dumps}
    assert to_delete == [
        "daily_20260801.sql.gz",
        "daily_20260801.sql.gz.migrations.json",
        "daily_20260802.sql.gz",
        "daily_20260802.sql.gz.migrations.json",
    ]


def test_legacy_sha_sidecars_are_deleted_even_for_kept_dumps() -> None:
    entries = ["daily_20260829.sql.gz", "daily_20260829.sha", "monthly_202608.sha"]

    keep_sets, to_delete = plan_retention(entries, NOW)

    assert keep_sets["daily"] == {"daily_20260829.sql.gz"}
    assert to_delete == ["daily_20260829.sha", "monthly_202608.sha"]


def test_orphan_snapshot_without_its_dump_is_deleted() -> None:
    _, to_delete = plan_retention(["daily_20260101.sql.gz.migrations.json"], NOW)

    assert to_delete == ["daily_20260101.sql.gz.migrations.json"]


def test_unmanaged_names_are_neither_kept_nor_deleted() -> None:
    keep_sets, to_delete = plan_retention(["restore.log", "adhoc-notes.txt"], NOW)

    assert keep_sets["other"] == {"restore.log", "adhoc-notes.txt"}
    assert to_delete == []
