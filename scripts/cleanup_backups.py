#!/usr/bin/env python3
import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

# Remote base. Each instance uses a per-client Drive target, so backups are
# uploaded flat under gdrive:dw_backups rather than nested by instance name.
REMOTE_BASE = "gdrive:dw_backups"

# Backup styles in the per-instance backups dir:
#   ts_dir:    legacy nested <YYYYMMDD_HHMMSS>/ trees; 24h+daily+monthly.
#   predeploy: predeploy_<ts>_<hash>.sql.gz (predeploy_backup.sh); 30 days.
#   daily:     daily_<YYYYMMDD>.sql.gz (backup_db.sh); keep most recent N.
#   monthly:   monthly_<YYYYMM>.sql.gz (backup_db.sh); keep most recent N.
# Any other entry (logs, ad-hoc files) is left untouched.
TS_DIR_RE = re.compile(r"^\d{8}_\d{6}$")
PREDEPLOY_RE = re.compile(r"^predeploy_(\d{8}_\d{6})_[0-9a-f]+\.sql\.gz$")
DAILY_RE = re.compile(r"^daily_(\d{8})\.sql\.gz$")
DAILY_SHA_RE = re.compile(r"^daily_(\d{8})\.sha$")
MONTHLY_RE = re.compile(r"^monthly_(\d{6})\.sql\.gz$")
MONTHLY_SHA_RE = re.compile(r"^monthly_(\d{6})\.sha$")

PREDEPLOY_RETENTION_DAYS = 30
DAILY_RETENTION_COUNT = 14
MONTHLY_RETENTION_COUNT = 12


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
    if DAILY_RE.match(name):
        return "daily"
    if DAILY_SHA_RE.match(name):
        return "daily_sha"
    if MONTHLY_RE.match(name):
        return "monthly"
    if MONTHLY_SHA_RE.match(name):
        return "monthly_sha"
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


def paired_sha_name(name: str) -> str:
    return name.replace(".sql.gz", ".sha")


def compute_recent_keep(entries, pattern, fmt, count):
    """Keep the `count` most recent entries matching `pattern` (timestamp via `fmt`)."""
    pairs = []
    for name in entries:
        m = pattern.match(name)
        if not m:
            continue
        ts = datetime.strptime(m.group(1), fmt)
        pairs.append((name, ts))
    pairs.sort(key=lambda x: x[1])
    return {n for n, _ in pairs[-count:]} if count else set()


def remove_entry(root, name):
    path = os.path.join(root, name)
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def remote_delete_commands(root, names):
    commands = []
    for name in names:
        local_path = os.path.join(root, name)
        remote_delete_command = "purge" if os.path.isdir(local_path) else "deletefile"
        commands.append((name, remote_delete_command))
    return commands


def purge_remote_entries(commands, dry_run, remote):
    print("To purge from remote:", [name for name, _ in commands])
    for name, remote_delete_command in commands:
        remote_path = f"{remote}/{name}"
        if dry_run:
            print(f"[DRY] Would {remote_delete_command} remote: {remote_path}")
        else:
            print(f"Deleting remote with rclone {remote_delete_command}: {remote_path}")
            subprocess.run(["rclone", remote_delete_command, remote_path], check=True)


def delete_local_entries(root, to_delete, dry_run):
    print("To delete locally:", sorted(to_delete))
    for name in to_delete:
        local_path = os.path.join(root, name)
        if dry_run:
            print(f"[DRY] Would remove local: {local_path}")
        else:
            print(f"Removing local: {local_path}")
            remove_entry(root, name)


def copy_remote(root, dry_run, remote):
    if not dry_run:
        subprocess.run(["rclone", "mkdir", remote], check=True)
    try:
        rem_list = subprocess.check_output(
            ["rclone", "lsf", remote], universal_newlines=True
        ).splitlines()
    except subprocess.CalledProcessError:
        if dry_run:
            print(f"Remote is not readable during dry-run: {remote}")
            rem_list = []
        else:
            raise
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

    print(f"Copying {root} → {remote}")
    subprocess.run(["rclone", "copy", root, remote], check=True)


def main():
    args = parse_arguments()
    backup_dir = args.backup_dir
    dry_run = not args.delete

    backup_dir_abs = os.path.abspath(backup_dir)
    if os.path.basename(backup_dir_abs) != "backups":
        sys.exit(f"ERROR: expected backup_dir to end with '/backups': {backup_dir}")
    remote = REMOTE_BASE

    entries = list_backup_dirs(backup_dir)

    ts_dir_entries = []
    predeploy_entries = []
    daily_entries = []
    daily_sha_entries = []
    monthly_entries = []
    monthly_sha_entries = []
    other_entries = []
    for name in entries:
        kind = classify(name)
        if kind == "ts_dir":
            ts_dir_entries.append(name)
        elif kind == "predeploy":
            predeploy_entries.append(name)
        elif kind == "daily":
            daily_entries.append(name)
        elif kind == "daily_sha":
            daily_sha_entries.append(name)
        elif kind == "monthly":
            monthly_entries.append(name)
        elif kind == "monthly_sha":
            monthly_sha_entries.append(name)
        else:
            other_entries.append(name)

    now = datetime.now()

    ts_dir_pairs = parse_ts_dir_pairs(ts_dir_entries)
    ts_dir_keep = compute_ts_dir_keep(ts_dir_pairs, now)
    predeploy_keep = compute_predeploy_keep(predeploy_entries, now)
    daily_keep = compute_recent_keep(
        daily_entries, DAILY_RE, "%Y%m%d", DAILY_RETENTION_COUNT
    )
    monthly_keep = compute_recent_keep(
        monthly_entries, MONTHLY_RE, "%Y%m", MONTHLY_RETENTION_COUNT
    )
    daily_sha_keep = {paired_sha_name(name) for name in daily_keep}
    monthly_sha_keep = {paired_sha_name(name) for name in monthly_keep}

    managed = (
        set(ts_dir_entries)
        | set(predeploy_entries)
        | set(daily_entries)
        | set(daily_sha_entries)
        | set(monthly_entries)
        | set(monthly_sha_entries)
    )
    keep = (
        ts_dir_keep
        | predeploy_keep
        | daily_keep
        | daily_sha_keep
        | monthly_keep
        | monthly_sha_keep
    )
    to_delete = sorted(managed - keep)

    print("Keeping (ts_dir):", sorted(ts_dir_keep))
    print("Keeping (predeploy):", sorted(predeploy_keep))
    print("Keeping (daily):", sorted(daily_keep))
    print("Keeping (daily sha):", sorted(daily_sha_keep))
    print("Keeping (monthly):", sorted(monthly_keep))
    print("Keeping (monthly sha):", sorted(monthly_sha_keep))
    if other_entries:
        print("Leaving untouched (unmanaged pattern):", sorted(other_entries))

    remote_delete_plan = remote_delete_commands(backup_dir, to_delete)

    copy_remote(backup_dir, dry_run, remote)
    purge_remote_entries(remote_delete_plan, dry_run, remote)
    delete_local_entries(backup_dir, to_delete, dry_run)


if __name__ == "__main__":
    main()
