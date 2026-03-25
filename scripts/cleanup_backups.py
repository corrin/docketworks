#!/usr/bin/env python3
import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

REMOTE = "gdrive:dw_backups"


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


def validate_entries(root, entries):
    if not entries:
        sys.exit(f"ERROR: no backups found in {root}")
    pattern = re.compile(r"^\d{8}_\d{6}$")
    for name in entries:
        path = os.path.join(root, name)
        if not os.path.isdir(path) or not pattern.match(name):
            sys.exit(f"ERROR: unexpected entry in '{root}': {name}")


def parse_timestamps(entries):
    pairs = []
    for name in entries:
        ts = datetime.strptime(name, "%Y%m%d_%H%M%S")
        pairs.append((name, ts))
    return sorted(pairs, key=lambda x: x[1])


def compute_keep_set(pairs, now):
    keep = set()
    cut24 = now - timedelta(hours=24)
    cut7 = now - timedelta(days=7)

    # Always keep newest
    keep.add(pairs[-1][0])

    # Keep last 24h
    keep |= {n for n, ts in pairs if ts > cut24}

    # One per day for past week
    seen_days = set()
    for n, ts in reversed(pairs):
        if cut24 >= ts > cut7:
            d = ts.date()
            if d not in seen_days:
                keep.add(n)
                seen_days.add(d)

    # One oldest per month beyond a week
    months = {}
    for n, ts in pairs:
        key = (ts.year, ts.month)
        if key not in months or ts < months[key][1]:
            months[key] = (n, ts)
    keep |= {n for n, _ in months.values()}

    return keep


def delete_and_purge(root, pairs, keep, dry_run):
    to_delete = [name for name, _ in pairs if name not in keep]
    print("To delete locally and purge from remote:", sorted(to_delete))
    for name in to_delete:
        local_path = os.path.join(root, name)
        remote_path = f"{REMOTE}/{name}"
        if dry_run:
            print(f"[DRY] Would remove local: {local_path}")
            print(f"[DRY] Would purge remote: {remote_path}")
        else:
            print(f"Removing local: {local_path}")
            shutil.rmtree(local_path)
            print(f"Purging remote: {remote_path}")
            subprocess.run(["rclone", "purge", remote_path], check=False)


def sync_remote(root, dry_run):
    # Normalize remote listing and compare to local dirs
    rem_list = subprocess.check_output(
        ["rclone", "lsf", REMOTE], universal_newlines=True
    ).splitlines()
    # strip trailing slashes for directories
    rem_names = [entry.rstrip("/") for entry in rem_list]
    local_names = os.listdir(root)
    remote_only = sorted(set(rem_names) - set(local_names))

    # Display remote-only entries
    if remote_only:
        print("Remote-only entries that would be deleted from Drive:")
        for entry in remote_only:
            print("   ", entry)
    else:
        print("No remote-only entries.")

    # Skip actual sync in dry-run
    if dry_run:
        return

    # Perform real sync
    print(f"Syncing {root} → {REMOTE} --delete-excluded")
    subprocess.run(["rclone", "sync", root, REMOTE, "--delete-excluded"], check=False)


def main():
    args = parse_arguments()
    backup_dir = args.backup_dir
    dry_run = not args.delete

    entries = list_backup_dirs(backup_dir)
    validate_entries(backup_dir, entries)
    pairs = parse_timestamps(entries)

    now = datetime.now()
    keep = compute_keep_set(pairs, now)

    print("Keeping:", sorted(keep))

    delete_and_purge(backup_dir, pairs, keep, dry_run)
    sync_remote(backup_dir, dry_run)


if __name__ == "__main__":
    main()
