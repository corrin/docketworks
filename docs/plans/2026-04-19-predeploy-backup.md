# Pre-deploy DB backup for deploy.sh

## Context

`scripts/server/deploy.sh` currently does: pull central repo → per-instance `git pull` → shared deps → per-instance build + migrate + restart. There is no safety net: a bad migration or unexpected data change after deploy is hard to undo because the only existing backups are the nightly `backup_db.sh` ones (midnight), so a mid-morning deploy that corrupts data loses most of a day.

The goal is a pre-deploy DB snapshot taken right before each instance's `git pull`, named with the commit hash that produced the data (the rollback target). Restoring is then a two-step pair: `git checkout <hash>` in the instance dir + `gunzip < predeploy_*_<hash>.sql.gz | psql <db>`. The backup is default-on with an opt-out flag. The existing midnight cleanup cron is extended to prune predeploy backups older than 30 days.

Decisions already made via clarifying questions:
- Hash = instance HEAD **before** pull (matches the dumped data → rollback target).
- Files live in `$INSTANCE_DIR/backups/` alongside `daily_*.sql.gz`, rclone'd to gdrive automatically.
- Any backup failure aborts the whole deploy (nothing has changed yet, so aborting is safe).
- A dirty working tree on an instance aborts the deploy, unless `--allow-dirty` is passed. Reason: the hash we stamp on the backup would be misleading — `git checkout <hash>` during rollback silently drops the uncommitted changes, so the backup wouldn't actually pair with restorable code. Prod/UAT servers should never have a dirty tree anyway (per user's "never switch branches on the server" rule); dirty = something weird, investigate before proceeding.

## Out of scope

- `cleanup_backups.py` currently validates that every entry in the backups dir matches `^\d{8}_\d{6}$` (nested timestamp dirs), which hard-fails against the `daily_*.sql.gz` / `monthly_*.sql.gz` files `backup_db.sh` already produces. This is a pre-existing bug in the cron setup (the midnight-plus-10 `cleanup_backups.sh` would exit 1 on msm-prod today). Noted but not fixed here — the cleanup refactor below incidentally removes the hard-fail because we must tolerate mixed filenames, but making the existing daily/monthly files actually *reachable* by retention logic is a separate concern.
- `rollback_release.sh` expects a `$TS/{code_*.tgz, db_*.sql.gz}` layout (a different style). Not changed. New predeploys use `git checkout <hash>` + `psql` restore, documented inline.

## Files to modify

1. `scripts/server/deploy.sh` — add `--no-backup` and `--allow-dirty` flags, add pre-pull dirty-tree check and backup step.
2. `scripts/predeploy_backup.sh` — **new**, the actual pg_dump helper. Keeps deploy.sh lean and lets the helper be run by hand for testing.
3. `scripts/predeploy_rollback.sh` — **new**, encapsulates `git checkout <hash>` + `gunzip -c <file> | psql <db>` with service stop/start so rollback is a single command.
4. `scripts/cleanup_backups.py` — extend to recognise `predeploy_*.sql.gz` files and prune those older than 30 days. Keep the existing nested-timestamp-dir logic untouched for entries that match that pattern.
5. `docs/msm-cutover.md` — add a short "Rolling back a deploy" subsection under the backup cron section (Phase 11).

## Design

### 1. `scripts/predeploy_backup.sh` (new)

```bash
#!/bin/bash
set -euo pipefail

# Usage: predeploy_backup.sh <instance>
# Captures instance HEAD + timestamp, pg_dumps into
#   /opt/docketworks/instances/<instance>/backups/predeploy_<ts>_<hash>.sql.gz
# Must run as root (calls sudo -u postgres).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/server/common.sh"

INSTANCE="$1"
INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
ENV_FILE="$INSTANCE_DIR/.env"
BACKUP_DIR="$INSTANCE_DIR/backups"

# Required inputs — fail hard if missing (no fallbacks).
[[ -f "$ENV_FILE" ]] || { echo "ERROR: $ENV_FILE missing" >&2; exit 1; }
[[ -d "$INSTANCE_DIR/.git" ]] || { echo "ERROR: $INSTANCE_DIR is not a git checkout" >&2; exit 1; }

DB_NAME=$(grep -E '^DB_NAME=' "$ENV_FILE" | cut -d= -f2)
[[ -n "$DB_NAME" ]] || { echo "ERROR: DB_NAME not set in $ENV_FILE" >&2; exit 1; }

INST_USER="$(instance_user "$INSTANCE")"
HASH=$(sudo -u "$INST_USER" git -C "$INSTANCE_DIR" rev-parse --short HEAD)
TS=$(date +%Y%m%d_%H%M%S)
OUT="$BACKUP_DIR/predeploy_${TS}_${HASH}.sql.gz"

mkdir -p "$BACKUP_DIR"

# Atomic write: dump to .tmp, rename on success. Partial dumps never look complete.
# pipefail ensures pg_dump failure fails the pipeline even though gzip succeeds on empty input.
sudo -u postgres pg_dump "$DB_NAME" | gzip > "$OUT.tmp"
mv "$OUT.tmp" "$OUT"

echo "Wrote $OUT"
```

Fail-early checks match the project's defensive philosophy. Atomic `.tmp` + `mv` means a mid-dump failure leaves no file that looks successful.

### 2. `scripts/server/deploy.sh` changes

a. Parse two flags: `--no-backup` (opt-out of the pg_dump step, default: backup enabled) and `--allow-dirty` (proceed even if an instance's working tree has uncommitted changes, default: abort). Flags accepted in any position.

b. Per-instance dirty check + backup inside the existing pull loop (lines 65–71), **before** `git fetch origin`:

```bash
for instance in "${TARGETS[@]}"; do
    inst_dir="$INSTANCES_DIR/$instance"
    inst_user="$(instance_user "$instance")"

    # Clean-tree check: dirty tree makes the backup's commit hash misleading.
    if ! sudo -u "$inst_user" git -C "$inst_dir" diff --quiet --ignore-submodules HEAD -- \
       || [[ -n "$(sudo -u "$inst_user" git -C "$inst_dir" status --porcelain)" ]]; then
        if [[ $ALLOW_DIRTY -eq 1 ]]; then
            log "WARNING: $instance has a dirty working tree (--allow-dirty set, proceeding)"
        else
            log "ERROR: $instance has a dirty working tree. Refusing to deploy."
            log "  Investigate with: sudo -u $inst_user git -C $inst_dir status"
            log "  To override: re-run with --allow-dirty"
            exit 1
        fi
    fi

    if [[ $DO_BACKUP -eq 1 ]]; then
        log "Backing up DB for $instance (pre-deploy)..."
        "$SCRIPT_DIR/../predeploy_backup.sh" "$instance"
    fi
    log "Pulling latest code for $instance..."
    sudo -u "$inst_user" git -C "$inst_dir" fetch origin
    sudo -u "$inst_user" git -C "$inst_dir" pull --ff-only
done
```

`set -euo pipefail` already on line 2 means a backup failure or dirty-tree abort happens before any `git pull`. Nothing has been changed on disk yet → safe.

c. Update the usage string on line 22 to mention `--no-backup` and `--allow-dirty`.

### 3. `scripts/predeploy_rollback.sh` (new)

```bash
#!/bin/bash
set -euo pipefail

# Usage: predeploy_rollback.sh <instance> <hash>
# Example: predeploy_rollback.sh msm-prod b54eddc7
# Looks up the newest predeploy_*_<hash>.sql.gz in the instance's backups dir,
# checks out that commit, restores the DB, bounces gunicorn.
# Must run as root.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/server/common.sh"

[[ $# -eq 2 ]] || { echo "Usage: $0 <instance> <hash>"; exit 1; }

INSTANCE="$1"
HASH="$2"
INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
ENV_FILE="$INSTANCE_DIR/.env"
BACKUP_DIR="$INSTANCE_DIR/backups"
INST_USER="$(instance_user "$INSTANCE")"
SERVICE="gunicorn-$INSTANCE"

[[ -f "$ENV_FILE" ]] || { echo "ERROR: $ENV_FILE missing" >&2; exit 1; }
DB_NAME=$(grep -E '^DB_NAME=' "$ENV_FILE" | cut -d= -f2)
[[ -n "$DB_NAME" ]] || { echo "ERROR: DB_NAME not set in $ENV_FILE" >&2; exit 1; }

# Find newest backup matching this hash. Fail loudly if none or if ambiguous
# across multiple matching files beyond just "take newest".
shopt -s nullglob
MATCHES=("$BACKUP_DIR"/predeploy_*_"$HASH".sql.gz)
(( ${#MATCHES[@]} > 0 )) || { echo "ERROR: no predeploy backup found for hash $HASH in $BACKUP_DIR" >&2; exit 1; }
# Sort by timestamp (filename contains YYYYMMDD_HHMMSS), take newest.
IFS=$'\n' SORTED=($(printf '%s\n' "${MATCHES[@]}" | sort))
unset IFS
BACKUP="${SORTED[-1]}"

echo "=== Rolling $INSTANCE back to $HASH using $BACKUP"
echo "=== This will stop $SERVICE, check out $HASH, and restore the DB."
read -rp "Continue? [y/N] " ans
[[ "$ans" == "y" || "$ans" == "Y" ]] || { echo "Aborted."; exit 1; }

echo "=== Stopping $SERVICE"
systemctl stop "$SERVICE"

echo "=== Checking out $HASH in $INSTANCE_DIR"
sudo -u "$INST_USER" git -C "$INSTANCE_DIR" checkout "$HASH"

echo "=== Restoring DB $DB_NAME from $BACKUP"
gunzip -c "$BACKUP" | sudo -u postgres psql "$DB_NAME"

echo "=== Starting $SERVICE"
systemctl start "$SERVICE"

echo "=== Rollback complete."
echo "=== Note: frontend dist and shared Python/node deps were NOT rebuilt."
echo "=== If the old commit's deps or frontend diverge, run:"
echo "===   sudo $SCRIPT_DIR/server/dw-run.sh $INSTANCE bash -c 'cd frontend && npm run build'"
echo "=== and/or re-run poetry install from $LOCAL_REPO."
```

Notes:
- Interactive confirm prompt because this is destructive (drops and recreates the DB). Keeps parity with `rollback_release.sh` which also stops the service and overwrites data without a confirm — but `rollback_release.sh` requires a specific timestamp arg and is hand-run; a short hash is easier to mis-type, so a confirm is worth the friction.
- Script violates the "stay on main" server rule, but that rule applies to normal operation; rollback is explicitly the exception.
- Follow-up steps (frontend rebuild, `poetry install` against old lockfile) are documented at the end rather than automated. Within the 30-day window deps rarely diverge enough to matter; when they do, the operator needs to make a judgment call (e.g. is `poetry install` against the rolled-back lockfile safe?).

### 4. `scripts/cleanup_backups.py` changes

Current shape: reads `backup_dir`, validates every entry is a nested timestamp dir, applies a keep-set policy, rsyncs to gdrive.

New shape: split entries by pattern, apply per-pattern retention, union the keep-sets, delete the rest.

```python
TS_DIR_RE  = re.compile(r"^\d{8}_\d{6}$")                    # existing nested-ts-dir style
PREDEPLOY_RE = re.compile(r"^predeploy_(\d{8}_\d{6})_[0-9a-f]+\.sql\.gz$")

def classify(name):
    if TS_DIR_RE.match(name):
        return "ts_dir"
    if PREDEPLOY_RE.match(name):
        return "predeploy"
    return "other"    # daily_*.sql.gz, monthly_*.sql.gz, etc. — left alone for now

def compute_predeploy_keep(entries, now):
    """Keep predeploy_*.sql.gz backups from the last 30 days."""
    cutoff = now - timedelta(days=30)
    keep = set()
    for name in entries:
        m = PREDEPLOY_RE.match(name)
        ts = datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
        if ts >= cutoff:
            keep.add(name)
    return keep
```

- `validate_entries` is relaxed: instead of hard-failing on unknown entries, classify them. Only `ts_dir` and `predeploy` participate in cleanup; `other` entries are preserved untouched (so pre-existing `daily_*.sql.gz` / `monthly_*.sql.gz` files don't get deleted).
- `compute_keep_set` keeps its 24h/daily/monthly policy for `ts_dir` entries; `compute_predeploy_keep` applies the 30-day rule to `predeploy` entries.
- `delete_and_purge` only considers entries of a managed class (`ts_dir` or `predeploy`) as deletion candidates. The rclone sync at the end is unchanged (mirrors the whole local dir, including survivors from all classes).

Existing cron from `docs/msm-cutover.md`:
```
0  0 * * * /opt/docketworks/repo/scripts/backup_db.sh msm-prod
10 0 * * * /opt/docketworks/repo/scripts/cleanup_backups.sh msm-prod --delete
```
No cron changes needed — the existing 00:10 run will prune old predeploys as a side-effect of its daily sweep.

### 5. `docs/msm-cutover.md` — Rollback procedure

Add a subsection after Phase 11 showing the one-line path:

```bash
# 1. Find the backup whose hash matches the code you want to restore
ls /opt/docketworks/instances/<instance>/backups/predeploy_*

# 2. Roll back (prompts for confirm, stops gunicorn, checks out <hash>,
#    restores DB, restarts gunicorn)
sudo /opt/docketworks/repo/scripts/predeploy_rollback.sh <instance> <hash>
```

Also document the manual equivalent (for when something is off and the script fails mid-way):

```bash
sudo systemctl stop gunicorn-<instance>
sudo -u dw_<instance> git -C /opt/docketworks/instances/<instance> checkout <hash>
gunzip -c /opt/docketworks/instances/<instance>/backups/predeploy_<ts>_<hash>.sql.gz \
    | sudo -u postgres psql <db_name>
sudo systemctl start gunicorn-<instance>
```

## Verification

Run on UAT (`msm-uat`) since prod cron already references this directory.

1. **Dry-run help**: `sudo /opt/docketworks/repo/scripts/server/deploy.sh --help` (or bad args) should mention `--no-backup` in the usage line.
2. **Happy path**: `sudo /opt/docketworks/repo/scripts/server/deploy.sh msm-uat` — expect a `predeploy_<ts>_<hash>.sql.gz` file in `/opt/docketworks/instances/msm-uat/backups/` whose hash matches `git -C /opt/docketworks/instances/msm-uat rev-parse --short HEAD~1` (the pre-pull HEAD — i.e. the commit that was running before the deploy). File size > 0, `gunzip -t` passes, `zcat | head -5` starts with `-- PostgreSQL database dump`.
3. **Opt-out**: `sudo /opt/docketworks/repo/scripts/server/deploy.sh msm-uat --no-backup` — confirm no new `predeploy_*` file is written.
4. **Failure mode**: temporarily rename the instance's `.env` to simulate a missing DB_NAME, run deploy, confirm script exits non-zero **before** any `git pull` (check `git -C <instance> rev-parse HEAD` is unchanged).
5. **Cleanup logic**: in a scratch dir, seed fake `predeploy_YYYYMMDD_HHMMSS_abc1234.sql.gz` files dated 40 days ago, 20 days ago, and today. Run `cleanup_backups.py <scratch> --delete`. Expect the 40-day-old file removed, the other two kept. Also seed a `daily_20260101.sql.gz` and confirm it survives (left-alone policy).
6. **`--all` abort**: with two instances, break one's `.env` and run `--all`. Expect the script to abort on the broken instance with no pulls on either.
7. **Dirty-tree abort**: in the instance dir, `sudo -u dw_msm_uat touch msm-uat/dirty.txt` (or `echo x >> README.md`). Run deploy — expect non-zero exit, clear error message pointing at `git status`, no backup file written, no `git pull` executed. Then re-run with `--allow-dirty` and confirm the deploy proceeds and the backup is taken.
8. **Rollback script, happy path** (UAT only): note current HEAD as `$H_OLD`, deploy to get a new HEAD, insert a visible row into some table, then run `sudo /opt/docketworks/repo/scripts/predeploy_rollback.sh msm-uat $H_OLD`. Confirm: prompt appears, gunicorn restarts, instance HEAD is `$H_OLD`, the inserted row is gone, site serves the old version.
9. **Rollback script, no-match**: `sudo /opt/docketworks/repo/scripts/predeploy_rollback.sh msm-uat deadbeef` — expect a clean "no predeploy backup found" error and non-zero exit (service not touched).

## Critical file references

- `scripts/server/deploy.sh:2` (`set -euo pipefail`), `:21-23` (usage), `:65-71` (per-instance pull loop — insertion point)
- `scripts/server/common.sh:5-10` (`BASE_DIR`, `INSTANCES_DIR`, `LOCAL_REPO`), `:36-39` (`instance_user` helper — reused in predeploy_backup.sh)
- `scripts/backup_db.sh:24, 35` (pattern for reading `DB_NAME` + `pg_dump | gzip` invocation — reused)
- `scripts/cleanup_backups.py:36-43` (`validate_entries` — relaxed), `:54-82` (`compute_keep_set` — unchanged for ts_dir), `:85-98` (`delete_and_purge` — scoped to managed classes)
- `docs/msm-cutover.md:590-611` (existing backup cron section — new rollback subsection appended)
