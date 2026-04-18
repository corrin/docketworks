# Align Linux User Names with DB User Names (Underscore)

**Goal:** Make per-instance OS user names match the DB role names (both `dw_<client>_<env>`) instead of diverging (`dw-<client>-<env>` vs `dw_<client>_<env>`).

**Architecture:** Centralise OS user naming in a single helper `instance_user()` in `scripts/server/common.sh`. Thread it through every script that constructs or references the user. Update systemd templates to take the user as an explicit `__INSTANCE_USER__` placeholder so the template never encodes the hyphen/underscore convention itself.

**Tech Stack:** bash, systemd unit files, PostgreSQL peer/password auth.

---

## Context

`scripts/server/instance.sh` currently creates per-instance OS users with hyphens (`dw-msm-prod`) while the DB name and DB role use underscores (`dw_msm_prod`). The mismatch has three costs:

1. **Two separate conversions from one identifier.** Every script converts `<client>-<env>` into the OS user (`dw-msm-prod`) and into the DB user (`dw_msm_prod`) independently. Future readers (and the author of the MSM cutover plan) have to remember which form goes where.
2. **Forces `pg_hba.conf` password auth over sockets.** `server-setup.sh:137-139` documents this: peer auth would work if OS user == DB role name, but they don't match, so we fall back to `scram-sha-256`.
3. **Plan noise in `docs/msm-cutover.md`.** Phase 5 (Maestral), Phase 6 (Samba), and Phase 14 (verification) all reference `dw-msm-prod` while the DB is `dw_msm_prod`. The operator has to context-switch between the two.

Flipping the OS convention to underscore gives one source-of-truth form. The MSM cutover hasn't happened yet, so MSM prod gets the new naming from day one. Existing UAT hosts need a one-time rename (see Migration Concern below).

---

## File Structure

**Responsibility map:**

| File | Role |
|---|---|
| `scripts/server/common.sh` | Defines `instance_user()` — single source of truth for the naming |
| `scripts/server/instance.sh` | Calls `instance_user()` in create + destroy paths; header comment documents the convention |
| `scripts/server/dw-run.sh`, `deploy.sh`, `rollback_release.sh`, `migrate_mariadb_to_postgres.sh` | Each calls `instance_user()` instead of constructing the name inline |
| `scripts/server/templates/gunicorn-instance.service.template`, `scheduler-instance.service.template` | Use `__INSTANCE_USER__` placeholder instead of hard-coding `dw-__INSTANCE__` |
| `scripts/server/server-setup.sh` | Comment reworded — user and role now match, but password auth stays because `dw_test` still uses it |
| `docs/msm-cutover.md` | Runtime references to the MSM user updated to `dw_msm_prod` |
| `docs/plans/2026-03-31-scheduler-service-plan.md`, `2026-03-31-scheduler-service-per-instance.md` | Keep scheduler plan docs consistent with the new template placeholder |

**Out of scope:**
- DB name and role already use underscores — no change.
- Files under `docs/plans/completed/` — historical, not touched.
- `.github/workflows/ci.yml`, `.env.precommit`, `.mcp.json.example` — these reference DB names, not OS users.

---

## Migration Concern — existing UAT instances

Any UAT instance already created on the UAT box has an OS user like `dw-msm-uat` (hyphen). After this PR is deployed:

- `instance.sh create` re-run for that instance would NOT skip user creation (the `id "$INSTANCE_USER"` check looks for `dw_msm_uat`, which doesn't exist) and would create a second user.
- The systemd unit rendered from the new template would set `User=dw_msm_uat`, but the instance directory and `.env` are owned by `dw-msm-uat`. Gunicorn would fail to read `.env`.

**Recommendation:** one-time manual rename on each UAT host *before* pulling this branch into the UAT checkout. There are few UAT instances; the alternative (add auto-rename logic to `instance.sh`) is transient code we'd just delete later.

Per-instance rename procedure (operator runs):
```bash
sudo systemctl stop gunicorn-msm-uat scheduler-msm-uat
sudo usermod -l dw_msm_uat dw-msm-uat
sudo groupmod -n dw_msm_uat dw-msm-uat
# usermod keeps the UID, so file ownership follows automatically
sudo systemctl daemon-reload
sudo systemctl start gunicorn-msm-uat scheduler-msm-uat
```

This rename procedure should be captured in a short section at the top of `docs/plans/2026-03-31-scheduler-service-plan.md` or a dedicated ops note — I'll include the snippet inside the PR description rather than in a new doc file.

---

## Tasks

### Task 1: Add `instance_user()` helper to `common.sh`

**Files:**
- Modify: `scripts/server/common.sh`

- [ ] **Step 1.** Open `scripts/server/common.sh` and append after `validate_env()` (end of file):

```bash
# Returns the OS user name for an instance: "msm-prod" → "dw_msm_prod".
# Matches the DB role name (see templates/env-instance.template DB_USER)
# so Postgres peer auth via socket is possible.
instance_user() {
    local instance="$1"
    echo "dw_${instance//-/_}"
}
```

- [ ] **Step 2.** Sanity-check the helper:

```bash
bash -c 'source scripts/server/common.sh && instance_user msm-prod'
# Expected: dw_msm_prod
bash -c 'source scripts/server/common.sh && instance_user acme-uat'
# Expected: dw_acme_uat
```

- [ ] **Step 3.** Commit.

```bash
git add scripts/server/common.sh
git commit -m "refactor(server): add instance_user helper for OS user naming"
```

---

### Task 2: Use `instance_user()` in `instance.sh` (create + destroy) and update header comment

**Files:**
- Modify: `scripts/server/instance.sh:12-14` (header), `:152`, `:197-198`, `:457`

- [ ] **Step 1.** Replace the header block. Old:

```bash
# Naming convention: dw_<client>_<env>
#   Instance name: <client>-<env>  (e.g., msm-uat)
#   Database:      dw_<client>_<env> (e.g., dw_msm_uat)
#   OS user:       dw-<client>-<env> (e.g., dw-msm-uat)
#   URL:           <client>-<env>.docketworks.site
```

New:

```bash
# Naming convention:
#   Instance name: <client>-<env>     (e.g., msm-uat)     — directory, systemd unit suffix
#   Database:      dw_<client>_<env>  (e.g., dw_msm_uat)
#   OS user:       dw_<client>_<env>  (e.g., dw_msm_uat)  — same string as the DB role
#   URL:           <client>-<env>.docketworks.site
```

- [ ] **Step 2.** Line 152 — replace:

```bash
    local INSTANCE_USER="dw-$INSTANCE"
```

with:

```bash
    local INSTANCE_USER="$(instance_user "$INSTANCE")"
```

- [ ] **Step 3.** Lines 197-198 — update the dw-acme/dw-msm comment:

```bash
    # Instance dir is 750 with group www-data so nginx can traverse to
    # mediafiles, frontend/dist, and gunicorn.sock.
    # .env and logs stay owner-only (dw_<client>_<env>:dw_<client>_<env>, 600/700).
    # Instance users have NO supplementary groups, so dw_acme_uat cannot
    # traverse dw_msm_uat's dir (not owner, not in www-data).
```

- [ ] **Step 4.** Line 457 (destroy path) — same replacement as Step 2:

```bash
    local INSTANCE_USER="$(instance_user "$INSTANCE")"
```

- [ ] **Step 5.** Verify no other `dw-$INSTANCE` remains in the file:

```bash
grep -n "dw-\$INSTANCE\|dw-\${" scripts/server/instance.sh
# Expected: no hits
```

- [ ] **Step 6.** Commit.

```bash
git add scripts/server/instance.sh
git commit -m "refactor(server): align OS user with DB role in instance.sh"
```

---

### Task 3: Switch remaining scripts to `instance_user()`

**Files:**
- Modify: `scripts/server/dw-run.sh:24`
- Modify: `scripts/server/deploy.sh:67, 97`
- Modify: `scripts/rollback_release.sh:16`
- Modify: `scripts/migrate_mariadb_to_postgres.sh:55`

- [ ] **Step 1.** `scripts/server/dw-run.sh:24` — replace:

```bash
INSTANCE_USER="dw-$INSTANCE"
```

with:

```bash
INSTANCE_USER="$(instance_user "$INSTANCE")"
```

(`common.sh` is already sourced at line 13.)

- [ ] **Step 2.** `scripts/server/deploy.sh:67` and `:97` — replace:

```bash
    instance_user="dw-$instance"
```

with:

```bash
    instance_user="$(instance_user "$instance")"
```

Check whether `deploy.sh` sources `common.sh`. If not, add at the top (after `set -euo pipefail`):

```bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/common.sh"
```

**Name collision note:** `instance_user` is both the local variable and the helper function. That's fine in bash (functions and variables have separate namespaces), but to keep it readable also rename the local variable where convenient:

```bash
    local instance_user_name
    instance_user_name="$(instance_user "$instance")"
```

Then update the two following usages in each block.

- [ ] **Step 3.** `scripts/rollback_release.sh:16` — replace:

```bash
INSTANCE_USER="dw-$INSTANCE"
```

with:

```bash
INSTANCE_USER="$(instance_user "$INSTANCE")"
```

Check for `source ... common.sh` at the top. If absent, add:

```bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/server/common.sh"
```

- [ ] **Step 4.** `scripts/migrate_mariadb_to_postgres.sh:55` — same pattern as Step 3 (including the `common.sh` source if missing — it lives one level up from `server/`, so the path is `$SCRIPT_DIR/server/common.sh`).

- [ ] **Step 5.** Grep verification:

```bash
grep -rn "dw-\$INSTANCE\|dw-\$instance\|dw-\${" scripts/
# Expected: no hits
```

- [ ] **Step 6.** Commit.

```bash
git add scripts/server/dw-run.sh scripts/server/deploy.sh \
        scripts/rollback_release.sh scripts/migrate_mariadb_to_postgres.sh
git commit -m "refactor: switch remaining scripts to instance_user helper"
```

---

### Task 4: Parameterise `User=` in gunicorn and scheduler service templates

**Files:**
- Modify: `scripts/server/templates/gunicorn-instance.service.template:6`
- Modify: `scripts/server/templates/scheduler-instance.service.template:6`
- Modify: `scripts/server/instance.sh` (the two `sed` blocks rendering these templates, around lines 400-414)

- [ ] **Step 1.** Replace `User=dw-__INSTANCE__` with `User=__INSTANCE_USER__` in both templates.

- [ ] **Step 2.** In `instance.sh`, update the gunicorn sed block (around line 400):

```bash
    sed \
        -e "s|__INSTANCE__|$INSTANCE|g" \
        -e "s|__INSTANCE_USER__|$INSTANCE_USER|g" \
        "$TEMPLATE_DIR/gunicorn-instance.service.template" \
        > "/etc/systemd/system/gunicorn-$INSTANCE.service"
```

- [ ] **Step 3.** Same addition to the scheduler sed block (around line 410).

- [ ] **Step 4.** Hand-render a template to confirm:

```bash
INSTANCE=msm-prod
INSTANCE_USER="$(bash -c 'source scripts/server/common.sh && instance_user msm-prod')"
sed \
    -e "s|__INSTANCE__|$INSTANCE|g" \
    -e "s|__INSTANCE_USER__|$INSTANCE_USER|g" \
    scripts/server/templates/gunicorn-instance.service.template | grep User=
# Expected: User=dw_msm_prod
```

- [ ] **Step 5.** Commit.

```bash
git add scripts/server/templates/gunicorn-instance.service.template \
        scripts/server/templates/scheduler-instance.service.template \
        scripts/server/instance.sh
git commit -m "refactor(server): parameterise User= in systemd service templates"
```

---

### Task 5: Update the `pg_hba` comment in `server-setup.sh`

**Files:**
- Modify: `scripts/server/server-setup.sh:137-139`

- [ ] **Step 1.** Replace:

```bash
# Allow password auth over sockets for app users (keep peer for postgres).
# Without this, instance users can't connect via socket because their OS
# username (dw-msm-uat) doesn't match the DB role (dw_msm_uat).
```

with:

```bash
# Allow password auth over sockets for app users (keep peer for postgres).
# Per-instance OS users share the same name as their DB role (dw_<client>_<env>),
# so peer auth would also work for them — but the shared dw_test pytest user
# has no matching Linux user and requires password auth. Keep the setting
# uniform.
```

- [ ] **Step 2.** Commit.

```bash
git add scripts/server/server-setup.sh
git commit -m "docs(server-setup): refresh pg_hba comment to reflect unified naming"
```

---

### Task 6: Update `docs/msm-cutover.md`

**Files:**
- Modify: `docs/msm-cutover.md` (~20 occurrences of `dw-msm-prod`)

- [ ] **Step 1.** Mechanical replacement:

```bash
sed -i 's/dw-msm-prod/dw_msm_prod/g' docs/msm-cutover.md
```

- [ ] **Step 2.** Spot-check the replacement landed in every phase:

```bash
grep -n "dw_msm_prod\|dw-msm-prod" docs/msm-cutover.md
# Expected: all hits are dw_msm_prod; no dw-msm-prod remains
```

Cross-reference the occurrences against this list to make sure the sed caught them all:
- Line 279 (Phase 4.3 — creates user)
- Lines 316-324 (Phase 5 header + config paths)
- Lines 329-371 (Phase 5.0-5.3 Maestral commands)
- Line 392 (Phase 5.4 systemd `User=`)
- Line 413 (Phase 5.4 verify)
- Lines 441-445 (Phase 6.1 Samba `force user`)
- Lines 713-715 (Phase 14.2 psql verify)
- Lines 782, 790, 796 (Phase 14.6 Maestral verify)
- Lines 916-922 (Troubleshooting)

- [ ] **Step 3.** Line 320 currently says `not /home/dw-msm-prod`. After sed it becomes `not /home/dw_msm_prod`. That's still meaningful (the path useradd *would* default to), so no further edit needed.

- [ ] **Step 4.** Commit.

```bash
git add docs/msm-cutover.md
git commit -m "docs(msm-cutover): align Linux user references with new underscore naming"
```

---

### Task 7: Update scheduler plan docs

**Files:**
- Modify: `docs/plans/2026-03-31-scheduler-service-plan.md:26`
- Modify: `docs/plans/2026-03-31-scheduler-service-per-instance.md:24`

- [ ] **Step 1.** In both files, change `User=dw-__INSTANCE__` to `User=__INSTANCE_USER__` so the snippet matches the template after Task 4.

- [ ] **Step 2.** Commit.

```bash
git add docs/plans/2026-03-31-scheduler-service-plan.md \
        docs/plans/2026-03-31-scheduler-service-per-instance.md
git commit -m "docs(plans): align scheduler plan snippets with new User= placeholder"
```

---

## Verification (end-to-end)

- [ ] `grep -rn "dw-\$INSTANCE\|dw-\$instance\|dw-__INSTANCE__\|dw-msm-prod" scripts/ docs/msm-cutover.md docs/plans/2026-03-31-*.md` returns no hits.
- [ ] `grep -n "instance_user()" scripts/server/common.sh` shows the helper definition.
- [ ] `bash -c 'source scripts/server/common.sh && instance_user msm-prod'` prints `dw_msm_prod`.
- [ ] Hand-render the gunicorn template for `msm-prod` (Task 4, Step 4) — must print `User=dw_msm_prod`.
- [ ] On a scratch box / UAT spare slot: run `sudo /opt/docketworks/repo/scripts/server/instance.sh create <fresh-client> prod --fqdn <fresh-fqdn>`, then:
  - `id dw_<fresh-client>_prod` succeeds
  - `systemctl cat gunicorn-<fresh-client>-prod | grep '^User='` shows `User=dw_<fresh-client>_prod`
  - `sudo -u postgres psql -c '\du'` shows role `dw_<fresh-client>_prod`
  - `sudo -u dw_<fresh-client>_prod psql dw_<fresh-client>_prod -c 'SELECT 1;'` returns 1

## PR structure

- Branch: `refactor/linux-user-underscore-naming` off `main`.
- Seven commits, one per task.
- Link Trello card URL in PR body (per `feedback_trello_github_linkage.md`).
- Flag the existing-UAT rename step in the PR description so the next deploy to UAT isn't a surprise.
