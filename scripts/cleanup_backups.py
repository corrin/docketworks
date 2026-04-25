#!/usr/bin/env python3
import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

REMOTE = "gdrive:dw_backups"

# Two backup styles live in the same per-instance backups dir:
#   ts_dir:    nested <YYYYMMDD_HHMMSS>/ trees produced by some release flows
#              (consumed by rollback_release.sh); retention is 24h+daily+monthly.
#   predeploy: flat predeploy_<ts>_<hash>.sql.gz files produced by
#              predeploy_backup.sh; retention is 30 days.
#   scrubbed:  flat scrubbed_<env>_<ts>.dump files produced by
#              `manage.py backport_data_backup`; retention is 30 days.
# Any other entry (daily_*.sql.gz, monthly_*.sql.gz from backup_db.sh, etc.)
# is left completely untouched — not a deletion candidate, not a keep target.
TS_DIR_RE = re.compile(r"^\d{8}_\d{6}$")
PREDEPLOY_RE = re.compile(r"^predeploy_(\d{8}_\d{6})_[0-9a-f]+\.sql\.gz$")
SCRUBBED_RE = re.compile(r"^scrubbed_[a-z]+_(\d{8}_\d{6})\.dump$")

PREDEPLOY_RETENTION_DAYS = 30
SCRUBBED_RETENTION_DAYS = 30


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Prune timestamped backups and sync to remote"
    )
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


def list_backup_dirs(root):
    try:
        return os.listdir(root)
    except FileNotFoundError:
        sys.exit(f"ERROR: backup root not found: {root}")


def classify(name):
    if TS_DIR_RE.match(name):
        return "ts_dir"
    if PREDEPLOY_RE.match(name):
        return "predeploy"
    if SCRUBBED_RE.match(name):
        return "scrubbed"
    return "other"


def parse_ts_dir_pairs(entries):
    pairs = []
    for name in entries:
        ts = datetime.strptime(name, "%Y%m%d_%H%M%S")
        pairs.append((name, ts))
    return sorted(pairs, key=lambda x: x[1])


def compute_ts_dir_keep(pairs, now):
    """24h + one/day for the past week + oldest per month beyond a week."""
    keep = set()
    if not pairs:
        return keep
    cut24 = now - timedelta(hours=24)
    cut7 = now - timedelta(days=7)

    keep.add(pairs[-1][0])
    keep |= {n for n, ts in pairs if ts > cut24}

    seen_days = set()
    for n, ts in reversed(pairs):
        if cut24 >= ts > cut7:
            d = ts.date()
            if d not in seen_days:
                keep.add(n)
                seen_days.add(d)

    months = {}
    for n, ts in pairs:
        key = (ts.year, ts.month)
        if key not in months or ts < months[key][1]:
            months[key] = (n, ts)
    keep |= {n for n, _ in months.values()}

    return keep


def compute_predeploy_keep(entries, now):
    """Keep predeploy_*.sql.gz files whose timestamp is within the retention window."""
    cutoff = now - timedelta(days=PREDEPLOY_RETENTION_DAYS)
    keep = set()
    for name in entries:
        m = PREDEPLOY_RE.match(name)
        ts = datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
        if ts >= cutoff:
            keep.add(name)
    return keep


def compute_scrubbed_keep(entries, now):
    """Keep scrubbed_*.dump files whose timestamp is within the retention window."""
    cutoff = now - timedelta(days=SCRUBBED_RETENTION_DAYS)
    keep = set()
    for name in entries:
        m = SCRUBBED_RE.match(name)
        ts = datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
        if ts >= cutoff:
            keep.add(name)
    return keep


def remove_entry(root, name):
    path = os.path.join(root, name)
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def delete_and_purge(root, to_delete, dry_run):
    print("To delete locally and purge from remote:", sorted(to_delete))
    for name in to_delete:
        local_path = os.path.join(root, name)
        remote_path = f"{REMOTE}/{name}"
        if dry_run:
            print(f"[DRY] Would remove local: {local_path}")
            print(f"[DRY] Would purge remote: {remote_path}")
        else:
            print(f"Removing local: {local_path}")
            remove_entry(root, name)
            print(f"Purging remote: {remote_path}")
            subprocess.run(["rclone", "purge", remote_path], check=False)


def sync_remote(root, dry_run):
    rem_list = subprocess.check_output(
        ["rclone", "lsf", REMOTE], universal_newlines=True
    ).splitlines()
    rem_names = [entry.rstrip("/") for entry in rem_list]
    local_names = os.listdir(root)
    remote_only = sorted(set(rem_names) - set(local_names))

    if remote_only:
        print("Remote-only entries that would be deleted from Drive:")
        for entry in remote_only:
            print("   ", entry)
    else:
        print("No remote-only entries.")

    if dry_run:
        return

    print(f"Syncing {root} → {REMOTE} --delete-excluded")
    subprocess.run(["rclone", "sync", root, REMOTE, "--delete-excluded"], check=False)


def main():
    args = parse_arguments()
    backup_dir = args.backup_dir
    dry_run = not args.delete

    entries = list_backup_dirs(backup_dir)

    ts_dir_entries = []
    predeploy_entries = []
    scrubbed_entries = []
    other_entries = []
    for name in entries:
        kind = classify(name)
        if kind == "ts_dir":
            ts_dir_entries.append(name)
        elif kind == "predeploy":
            predeploy_entries.append(name)
        elif kind == "scrubbed":
            scrubbed_entries.append(name)
        else:
            other_entries.append(name)

    now = datetime.now()

    ts_dir_pairs = parse_ts_dir_pairs(ts_dir_entries)
    ts_dir_keep = compute_ts_dir_keep(ts_dir_pairs, now)
    predeploy_keep = compute_predeploy_keep(predeploy_entries, now)
    scrubbed_keep = compute_scrubbed_keep(scrubbed_entries, now)

    managed = set(ts_dir_entries) | set(predeploy_entries) | set(scrubbed_entries)
    to_delete = sorted(managed - ts_dir_keep - predeploy_keep - scrubbed_keep)

    print("Keeping (ts_dir):", sorted(ts_dir_keep))
    print("Keeping (predeploy):", sorted(predeploy_keep))
    print("Keeping (scrubbed):", sorted(scrubbed_keep))
    if other_entries:
        print("Leaving untouched (unmanaged pattern):", sorted(other_entries))

    delete_and_purge(backup_dir, to_delete, dry_run)
    sync_remote(backup_dir, dry_run)


if __name__ == "__main__":
    main()
