# Prod task: add `django_migrations` snapshot to backup zip

Small, self-contained change to `apps/workflow/management/commands/backport_data_backup.py` so every `backport_data_backup` run writes a third file into the zip: `prod_backup_<ts>.migrations.json`. This is a fast-track of **one** commit from the in-flight `feat/jobevent-audit` branch; the rest of that branch is still going through dev validation. Applying this piece now means the next prod backup already contains what the upcoming dev-side restore flow needs.

**No DB changes. No migrations. No schema touch. Only the Python code that produces the backup zip changes.** Restart of the running Gunicorn is *not* required — the change only takes effect when `manage.py backport_data_backup` is next invoked.

## Log as you go

Keep a log and paste command output under each step. Save it as `logs/prod_patch_migrations_snapshot_<YYYYMMDD_HHMMSS>.log`. Attach it to the PR on merge-back.

---

## Step 0: Set up shell variables

Everything below uses these. Set them once at the top of your session.

```bash
INSTANCE=msm-prod                                 # adjust if your instance name differs
INSTANCE_DIR=/opt/docketworks/instances/$INSTANCE
REPO_DIR=/opt/docketworks/repo                    # shared code checkout
OWNER=$(stat -c '%U' "$INSTANCE_DIR/.git")
```

Sanity:

```bash
echo "instance=$INSTANCE dir=$INSTANCE_DIR repo=$REPO_DIR owner=$OWNER"
ls "$INSTANCE_DIR/.env"
ls "$REPO_DIR/apps/workflow/management/commands/backport_data_backup.py"
```

Both `ls` commands must succeed. If either is missing, stop — paths differ on this host and the rest of this runbook will misfire.

## Step 1: Confirm the code you're about to patch

Record the current state before touching anything.

```bash
sudo -u "$OWNER" git -C "$REPO_DIR" rev-parse HEAD
sudo -u "$OWNER" git -C "$REPO_DIR" status
md5sum "$REPO_DIR/apps/workflow/management/commands/backport_data_backup.py"
```

**Expected:** clean working tree, branch `main`, a commit hash you record in your log. The md5 is your "before" fingerprint — if the patch applies correctly in Step 2, this hash will change; if the patch somehow no-ops, it won't.

If the working tree is **not** clean, stop. Don't patch over someone else's uncommitted change.

## Step 2: Apply the patch

The change is a single unified diff against `apps/workflow/management/commands/backport_data_backup.py`. Save the diff to a file and apply it with `git apply`.

```bash
cat > /tmp/migrations_snapshot.patch <<'PATCH'
diff --git a/apps/workflow/management/commands/backport_data_backup.py b/apps/workflow/management/commands/backport_data_backup.py
--- a/apps/workflow/management/commands/backport_data_backup.py
+++ b/apps/workflow/management/commands/backport_data_backup.py
@@ -9,6 +9,7 @@ from collections import defaultdict

 from django.conf import settings
 from django.core.management.base import BaseCommand
+from django.db import connection
 from faker import Faker

 from apps.accounts.staff_anonymization import create_staff_profile
@@ -167,8 +168,19 @@ class Command(BaseCommand):
             # Step 4: Create schema-only backup using pg_dump
             schema_path = self.create_schema_backup(backup_dir, timestamp, env_name)

+            # Step 4b: Snapshot django_migrations so the restore side can migrate
+            # the target DB to prod's recorded migration state before loaddata.
+            # Without this, any dev-side migration that tightens a constraint
+            # (e.g. adding NOT NULL after a backfill) forces manual rewind hacks
+            # in the restore runbook.
+            migrations_path = self.create_migrations_snapshot(
+                backup_dir, timestamp, env_name
+            )
+
             # Step 5: Create combined zip file in /tmp
-            self.create_combined_zip(output_path, schema_path, timestamp, env_name)
+            self.create_combined_zip(
+                output_path, schema_path, migrations_path, timestamp, env_name
+            )

         except subprocess.CalledProcessError as exc:
             self.stdout.write(self.style.ERROR(f"dumpdata failed: {exc.stderr}"))
@@ -438,8 +450,46 @@ class Command(BaseCommand):
             self.stdout.write(self.style.ERROR(f"Error during schema backup: {e}"))
             raise

-    def create_combined_zip(self, data_path, schema_path, timestamp, env_name):
-        """Create a combined zip file containing both data and schema backups in /tmp"""
+    def create_migrations_snapshot(self, backup_dir, timestamp, env_name):
+        """Dump django_migrations so the restore side can rebuild schema
+        to prod's recorded state before loaddata."""
+        snapshot_filename = f"{env_name}_backup_{timestamp}.migrations.json"
+        snapshot_path = os.path.join(backup_dir, snapshot_filename)
+
+        self.stdout.write(f"Creating migrations snapshot: {snapshot_path}")
+
+        try:
+            with connection.cursor() as cursor:
+                cursor.execute(
+                    "SELECT app, name, applied FROM django_migrations ORDER BY id"
+                )
+                rows = [
+                    {"app": app, "name": name, "applied": applied.isoformat()}
+                    for app, name, applied in cursor.fetchall()
+                ]
+
+            payload = {
+                "dumped_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
+                "rows": rows,
+            }
+            with open(snapshot_path, "w", encoding="utf-8") as f:
+                json.dump(payload, f, indent=2)
+
+            self.stdout.write(
+                self.style.SUCCESS(f"Migrations snapshot written: {len(rows)} rows")
+            )
+            return snapshot_path
+
+        except Exception as exc:
+            persist_app_error(exc)
+            if os.path.exists(snapshot_path):
+                os.remove(snapshot_path)
+            raise
+
+    def create_combined_zip(
+        self, data_path, schema_path, migrations_path, timestamp, env_name
+    ):
+        """Create a combined zip file containing data, schema, and migrations snapshots in /tmp"""
         # Check for failures first
         if not os.path.exists(data_path):
             raise FileNotFoundError(f"Data backup file not found: {data_path}")
@@ -447,6 +497,11 @@ class Command(BaseCommand):
         if not os.path.exists(schema_path):
             raise FileNotFoundError(f"Schema backup file not found: {schema_path}")

+        if not os.path.exists(migrations_path):
+            raise FileNotFoundError(
+                f"Migrations snapshot file not found: {migrations_path}"
+            )
+
         # Create zip file in /tmp
         zip_filename = f"{env_name}_backup_{timestamp}_complete.zip"
         zip_path = os.path.join("/tmp", zip_filename)
@@ -461,6 +516,9 @@ class Command(BaseCommand):
                 # Add schema backup
                 zipf.write(schema_path, os.path.basename(schema_path))

+                # Add migrations snapshot
+                zipf.write(migrations_path, os.path.basename(migrations_path))
+
             self.stdout.write(
                 self.style.SUCCESS(
                     f"Combined backup zip created successfully: {zip_path}"
PATCH

sudo -u "$OWNER" git -C "$REPO_DIR" apply --check /tmp/migrations_snapshot.patch
sudo -u "$OWNER" git -C "$REPO_DIR" apply /tmp/migrations_snapshot.patch
```

**Check:** `git apply --check` exits 0 (clean). `git apply` exits 0 and prints nothing.

**If `--check` fails:** the file has already drifted from what this patch expects (someone else edited it, or this PR already landed via the normal flow). STOP. Do not use `-3` or `--reject`. Report the conflict back and wait for instructions.

Verify the file changed:

```bash
sudo -u "$OWNER" git -C "$REPO_DIR" diff --stat
md5sum "$REPO_DIR/apps/workflow/management/commands/backport_data_backup.py"
```

**Expected:** `git diff --stat` shows one modified file with roughly `~66 insertions, 2 deletions`. The md5 is different from Step 1's fingerprint.

## Step 3: Quick syntax check

The command won't run if the file doesn't parse. Cheap check before we invoke it for real:

```bash
sudo -u "$OWNER" "$INSTANCE_DIR/.venv/bin/python" -m py_compile \
    "$REPO_DIR/apps/workflow/management/commands/backport_data_backup.py"
echo "compile exit: $?"
```

**Expected:** exit `0`, no output. Any `SyntaxError` here means the patch landed wrong — revert (see Rollback) and report.

## Step 4: Run the backup and verify the new format

```bash
cd "$INSTANCE_DIR"
sudo -u "$OWNER" .venv/bin/python manage.py backport_data_backup 2>&1 | tee -a /tmp/backport_run.log
```

**Expected in the output (the new lines are what prove the patch is live):**

```
...
Schema backup completed successfully to ...prod_backup_<TS>.schema.sql
Creating migrations snapshot: ...prod_backup_<TS>.migrations.json
Migrations snapshot written: NNN rows
Creating combined zip file: /tmp/prod_backup_<TS>_complete.zip
Combined backup zip created successfully: /tmp/prod_backup_<TS>_complete.zip
Zip file size: X.XX MB
```

The two lines starting `Creating migrations snapshot:` and `Migrations snapshot written: NNN rows` are the signal that the patched code ran. If you don't see them, the old code ran — check that the `.venv` is picking up the file you edited (it should, because you edited in place).

**Record in your log:** `NNN` (the row count) and the final zip filename.

## Step 5: Verify the zip contains three files

```bash
ZIP=$(ls -t /tmp/prod_backup_*_complete.zip | head -1)
echo "Verifying: $ZIP"
unzip -l "$ZIP"
```

**Expected — three lines, all with today's timestamp:**

```
prod_backup_<TS>.json.gz
prod_backup_<TS>.schema.sql
prod_backup_<TS>.migrations.json
```

Peek at the migrations snapshot to confirm the shape:

```bash
unzip -p "$ZIP" "prod_backup_*.migrations.json" | jq '.rows | length'
unzip -p "$ZIP" "prod_backup_*.migrations.json" | jq '.rows[0]'
unzip -p "$ZIP" "prod_backup_*.migrations.json" | jq '.dumped_at'
```

**Expected:**
- `.rows | length` — a three-digit number (several hundred migrations).
- `.rows[0]` — `{app, name, applied}` with `applied` as an ISO-8601 string.
- `.dumped_at` — today's date, ISO-8601.

Record all three in your log.

## Step 6: Deliver the zip

Use the existing delivery route (typically rclone to shared storage). Example:

```bash
rclone copy "$ZIP" gdrive:dw_backups/
```

**Check:** remote listing shows the file with the expected size. Ping Corrin with the filename so the dev-side restore can use it.

## Step 7: Leave the patch in place

Do **not** revert the patch. The in-flight `feat/jobevent-audit` PR includes this same change, so when that PR eventually merges and the normal deploy runs, `git pull` on `$REPO_DIR` will reconcile — the file will already match what's coming in (the "ours" and "theirs" are byte-identical), and the pull will fast-forward cleanly.

If you need to audit exactly what's different from `main`:

```bash
sudo -u "$OWNER" git -C "$REPO_DIR" diff
sudo -u "$OWNER" git -C "$REPO_DIR" status
```

Expected on that diff: exactly the patch from Step 2, nothing else. Expected on that status: `backport_data_backup.py` modified, nothing else tracked or added.

Attach your log file to the `feat/jobevent-audit` PR so Corrin knows the patch was applied on prod at what time, and that the first new-format zip is delivered.

---

## Rollback

If Step 3 or Step 4 fails in a way you can't resolve:

```bash
sudo -u "$OWNER" git -C "$REPO_DIR" checkout -- \
    apps/workflow/management/commands/backport_data_backup.py
md5sum "$REPO_DIR/apps/workflow/management/commands/backport_data_backup.py"
```

The md5 should now match the Step 1 fingerprint. The command is back to its pre-patch state. Delete any partial artifacts:

```bash
rm -f /tmp/prod_backup_*_complete.zip
rm -f "$INSTANCE_DIR/restore/"*.migrations.json   # only if it was created mid-failure
```

Report what failed — diff output, tracebacks, whatever `backport_data_backup` printed — and wait for a fix rather than re-attempting.

---

## What you have NOT done

For clarity: this task only changes the Python code that builds the backup zip. It does **not**:

- Run any DB migration.
- Restart Gunicorn.
- Touch any other instance.
- Merge anything to `main`.

The larger `feat/jobevent-audit` PR (which includes this same patch plus the `JobEvent` backfill/NOT-NULL migrations 0078/0079) is a separate, later deployment and will have its own runbook.
