#!/usr/bin/env python3
import argparse
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Remote base. Each instance uses a per-client Drive target, so backups are
# uploaded flat under gdrive:dw_backups rather than nested by instance name.
REMOTE_BASE = "gdrive:dw_backups"

# Backup styles in the per-instance backups dir:
#   ts_dir:    legacy nested <YYYYMMDD_HHMMSS>/ trees; 24h+daily+monthly.
#   predeploy: predeploy_<ts>_<hash>.sql.gz (predeploy_backup.sh); 30 days.
#   pre_reset: pre_reset_<db>_<ts>.sql.gz (manage.py reset_public_schema's
#              pre-wipe snapshot, ADR 0048); 7 days.
#   daily:     daily_<YYYYMMDD>.sql.gz (backup_db.sh); keep most recent N,
#              each with its <dump>.migrations.json sidecar.
#   monthly:   monthly_<YYYYMM>.sql.gz (backup_db.sh); keep most recent N,
#              each with its <dump>.migrations.json sidecar.
#   *_sha:     Fable: retired release-commit sidecars; recognised so
#              retention deletes them, never written or kept any more.
#   stale_tmp: a daily/monthly .tmp left by a crash mid-write; the writer
#              renames tmp->final, so a surviving .tmp is garbage.
# Any other entry (logs, ad-hoc files) is left untouched.
TS_DIR_RE = re.compile(r"^\d{8}_\d{6}$")
PREDEPLOY_RE = re.compile(r"^predeploy_(\d{8}_\d{6})_[0-9a-f]+\.sql\.gz$")
PRE_RESET_RE = re.compile(r"^pre_reset_.+_(\d{8}_\d{6})\.sql\.gz$")
DAILY_RE = re.compile(r"^daily_(\d{8})\.sql\.gz$")
DAILY_SNAPSHOT_RE = re.compile(r"^daily_(\d{8})\.sql\.gz\.migrations\.json$")
DAILY_SHA_RE = re.compile(r"^daily_(\d{8})\.sha$")
MONTHLY_RE = re.compile(r"^monthly_(\d{6})\.sql\.gz$")
MONTHLY_SNAPSHOT_RE = re.compile(r"^monthly_(\d{6})\.sql\.gz\.migrations\.json$")
MONTHLY_SHA_RE = re.compile(r"^monthly_(\d{6})\.sha$")
STALE_TMP_RE = re.compile(r"^(?:daily_\d{8}|monthly_\d{6})\.sql\.gz(?:\.migrations\.json)?\.tmp$")

CLASSIFIERS: list[tuple[re.Pattern[str], str]] = [
    (TS_DIR_RE, "ts_dir"),
    (PREDEPLOY_RE, "predeploy"),
    (PRE_RESET_RE, "pre_reset"),
    (DAILY_SNAPSHOT_RE, "daily_snapshot"),
    (DAILY_RE, "daily"),
    (DAILY_SHA_RE, "daily_sha"),
    (MONTHLY_SNAPSHOT_RE, "monthly_snapshot"),
    (MONTHLY_RE, "monthly"),
    (MONTHLY_SHA_RE, "monthly_sha"),
    (STALE_TMP_RE, "stale_tmp"),
]

PREDEPLOY_RETENTION_DAYS = 30
PRE_RESET_RETENTION_DAYS = 7
DAILY_RETENTION_COUNT = 14
MONTHLY_RETENTION_COUNT = 12


def rclone_path() -> str:
    path = shutil.which("rclone")
    if path is None:
        sys.exit("ERROR: rclone not found on PATH")
    return path


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prune timestamped backups and sync to remote")
    parser.add_argument(
        "backup_dir",
        help="Path to the backup directory (e.g., /opt/docketworks/instances/msm/backups)",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Actually remove old backups; omit for dry-run.",
    )
    return parser.parse_args()


def list_backup_dirs(root: Path) -> list[str]:
    try:
        return [entry.name for entry in root.iterdir()]
    except FileNotFoundError:
        sys.exit(f"ERROR: backup root not found: {root}")


def classify(name: str) -> str:
    for pattern, kind in CLASSIFIERS:
        if pattern.match(name):
            return kind
    return "other"


def parse_backup_timestamp(value: str, fmt: str) -> datetime:
    # Backup filenames carry server-local timestamps; compare them in the
    # same local timezone datetime.now().astimezone() reports.
    return datetime.strptime(value, fmt).astimezone()


def parse_ts_dir_pairs(entries: list[str]) -> list[tuple[str, datetime]]:
    pairs = [(name, parse_backup_timestamp(name, "%Y%m%d_%H%M%S")) for name in entries]
    return sorted(pairs, key=lambda x: x[1])


def compute_ts_dir_keep(pairs: list[tuple[str, datetime]], now: datetime) -> set[str]:
    """24h + one/day for the past week + oldest per month beyond a week."""
    keep: set[str] = set()
    if not pairs:
        return keep
    cut24 = now - timedelta(hours=24)
    cut7 = now - timedelta(days=7)

    keep.add(pairs[-1][0])
    keep |= {n for n, ts in pairs if ts > cut24}

    seen_days: set[date] = set()
    for n, ts in reversed(pairs):
        if cut24 >= ts > cut7:
            d = ts.date()
            if d not in seen_days:
                keep.add(n)
                seen_days.add(d)

    months: dict[tuple[int, int], tuple[str, datetime]] = {}
    for n, ts in pairs:
        key = (ts.year, ts.month)
        if key not in months or ts < months[key][1]:
            months[key] = (n, ts)
    keep |= {n for n, _ in months.values()}

    return keep


def compute_window_keep(
    entries: list[str], pattern: re.Pattern[str], retention_days: int, now: datetime
) -> set[str]:
    """Keep entries whose <YYYYMMDD_HHMMSS> group is within the retention window."""
    cutoff = now - timedelta(days=retention_days)
    keep: set[str] = set()
    for name in entries:
        m = pattern.match(name)
        if m is None:
            raise ValueError(f"entry does not match {pattern.pattern}: {name}")
        ts = parse_backup_timestamp(m.group(1), "%Y%m%d_%H%M%S")
        if ts >= cutoff:
            keep.add(name)
    return keep


def paired_snapshot_name(name: str) -> str:
    return f"{name}.migrations.json"


def compute_recent_keep(
    entries: list[str], pattern: re.Pattern[str], fmt: str, count: int
) -> set[str]:
    """Keep the `count` most recent entries matching `pattern` (timestamp via `fmt`)."""
    pairs: list[tuple[str, datetime]] = []
    for name in entries:
        m = pattern.match(name)
        if not m:
            continue
        ts = parse_backup_timestamp(m.group(1), fmt)
        pairs.append((name, ts))
    pairs.sort(key=lambda x: x[1])
    return {n for n, _ in pairs[-count:]} if count else set()


def remove_entry(root: Path, name: str) -> None:
    path = root / name
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def remote_delete_commands(root: Path, names: list[str]) -> list[tuple[str, str]]:
    commands: list[tuple[str, str]] = []
    for name in names:
        remote_delete_command = "purge" if (root / name).is_dir() else "deletefile"
        commands.append((name, remote_delete_command))
    return commands


def purge_remote_entries(commands: list[tuple[str, str]], dry_run: bool, remote: str) -> None:
    print("To purge from remote:", [name for name, _ in commands])
    rclone = rclone_path()
    for name, remote_delete_command in commands:
        remote_path = f"{remote}/{name}"
        if dry_run:
            print(f"[DRY] Would {remote_delete_command} remote: {remote_path}")
        else:
            print(f"Deleting remote with rclone {remote_delete_command}: {remote_path}")
            subprocess.run(  # noqa: S603 -- fixed argv; executable resolved via shutil.which, no user input
                [rclone, remote_delete_command, remote_path], check=True
            )


def delete_local_entries(root: Path, to_delete: list[str], dry_run: bool) -> None:
    print("To delete locally:", sorted(to_delete))
    for name in to_delete:
        local_path = root / name
        if dry_run:
            print(f"[DRY] Would remove local: {local_path}")
        else:
            print(f"Removing local: {local_path}")
            remove_entry(root, name)


def copy_remote(root: Path, dry_run: bool, remote: str) -> None:
    rclone = rclone_path()
    if not dry_run:
        subprocess.run([rclone, "mkdir", remote], check=True)  # noqa: S603 -- fixed argv; executable resolved via shutil.which, no user input
    try:
        rem_list = subprocess.check_output(  # noqa: S603 -- fixed argv; executable resolved via shutil.which, no user input
            [rclone, "lsf", remote], universal_newlines=True
        ).splitlines()
    except subprocess.CalledProcessError:
        if dry_run:
            print(f"Remote is not readable during dry-run: {remote}")
            rem_list = []
        else:
            raise
    rem_names = [entry.rstrip("/") for entry in rem_list]
    local_names = [entry.name for entry in root.iterdir()]
    remote_only = sorted(set(rem_names) - set(local_names))

    if remote_only:
        print("Remote-only entries that would be deleted from Drive:")
        for entry in remote_only:
            print("   ", entry)
    else:
        print("No remote-only entries.")

    if dry_run:
        return

    print(f"Copying {root} → {remote}")
    subprocess.run([rclone, "copy", str(root), remote], check=True)  # noqa: S603 -- fixed argv; executable resolved via shutil.which, no user input


def bucket_entries(entries: list[str]) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {kind: [] for _, kind in CLASSIFIERS}
    buckets["other"] = []
    for name in entries:
        buckets[classify(name)].append(name)
    return buckets


def plan_retention(entries: list[str], now: datetime) -> tuple[dict[str, set[str]], list[str]]:
    """Decide what stays and what goes; pure so retention is testable.

    Returns per-kind keep sets and the sorted deletion list. A kept dump
    keeps its ``.migrations.json`` sidecar; legacy ``.sha`` sidecars are
    never kept; unmanaged names appear in neither.
    """
    buckets = bucket_entries(entries)

    ts_dir_pairs = parse_ts_dir_pairs(buckets["ts_dir"])
    daily_keep = compute_recent_keep(buckets["daily"], DAILY_RE, "%Y%m%d", DAILY_RETENTION_COUNT)
    monthly_keep = compute_recent_keep(
        buckets["monthly"], MONTHLY_RE, "%Y%m", MONTHLY_RETENTION_COUNT
    )
    keep_sets = {
        "ts_dir": compute_ts_dir_keep(ts_dir_pairs, now),
        "predeploy": compute_window_keep(
            buckets["predeploy"], PREDEPLOY_RE, PREDEPLOY_RETENTION_DAYS, now
        ),
        "pre_reset": compute_window_keep(
            buckets["pre_reset"], PRE_RESET_RE, PRE_RESET_RETENTION_DAYS, now
        ),
        "daily": daily_keep,
        "daily_snapshot": {paired_snapshot_name(name) for name in daily_keep},
        "monthly": monthly_keep,
        "monthly_snapshot": {paired_snapshot_name(name) for name in monthly_keep},
        "other": set(),
    }

    managed = {name for kind, names in buckets.items() if kind != "other" for name in names}
    keep: set[str] = set()
    for kept in keep_sets.values():
        keep |= kept
    to_delete = sorted(managed - keep)
    keep_sets["other"] = set(buckets["other"])
    return keep_sets, to_delete


def main() -> None:
    args = parse_arguments()
    dry_run = not args.delete

    backup_dir = Path(args.backup_dir).absolute()
    if backup_dir.name != "backups":
        sys.exit(f"ERROR: expected backup_dir to end with '/backups': {args.backup_dir}")
    remote = REMOTE_BASE

    now = datetime.now().astimezone()
    keep_sets, to_delete = plan_retention(list_backup_dirs(backup_dir), now)

    print("Keeping (ts_dir):", sorted(keep_sets["ts_dir"]))
    print("Keeping (predeploy):", sorted(keep_sets["predeploy"]))
    print("Keeping (pre_reset):", sorted(keep_sets["pre_reset"]))
    print("Keeping (daily):", sorted(keep_sets["daily"]))
    print("Keeping (daily snapshots):", sorted(keep_sets["daily_snapshot"]))
    print("Keeping (monthly):", sorted(keep_sets["monthly"]))
    print("Keeping (monthly snapshots):", sorted(keep_sets["monthly_snapshot"]))
    if keep_sets["other"]:
        print("Leaving untouched (unmanaged pattern):", sorted(keep_sets["other"]))

    remote_delete_plan = remote_delete_commands(backup_dir, to_delete)

    copy_remote(backup_dir, dry_run, remote)
    purge_remote_entries(remote_delete_plan, dry_run, remote)
    delete_local_entries(backup_dir, to_delete, dry_run)


if __name__ == "__main__":
    main()
