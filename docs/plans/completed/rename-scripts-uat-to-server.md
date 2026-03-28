# Rename scripts/uat/ to scripts/server/

## Context

The `scripts/uat/` directory contains scripts for setting up servers and managing client instances on those servers. This applies equally to UAT, staging, and production — the "uat" prefix is a historical artifact from when UAT was the first server set up. Renaming clarifies that these are general server/instance management scripts.

## Rename Map

### Directory
- `scripts/uat/` → `scripts/server/`

### Files (drop the uat- prefix)
- `uat-base-setup.sh` → `server-setup.sh`
- `uat-instance.sh` → `instance.sh`
- `uat-deploy.sh` → `deploy.sh`
- `uat-common.sh` → `common.sh`
- `dw-run.sh` → unchanged (no uat prefix)
- `certbot-dreamhost-auth.sh` → unchanged
- `certbot-dreamhost-cleanup.sh` → unchanged
- `README.md` → unchanged
- `templates/` → unchanged

### Internal cross-references (source statements)
- `instance.sh:17` — `source "$SCRIPT_DIR/uat-common.sh"` → `common.sh`
- `deploy.sh:14` — `source "$SCRIPT_DIR/uat-common.sh"` → `common.sh`
- `dw-run.sh:13` — `source "$SCRIPT_DIR/uat-common.sh"` → `common.sh`
- `server-setup.sh:183-184` — references `certbot-dreamhost-*.sh` (no change needed)

### Documentation updates
- `scripts/server/README.md` — update all `scripts/uat/` paths and `uat-*.sh` filenames
- `docs/uat_setup.md` — rename to `docs/server_setup.md`, update all paths. Also fix stale script names (uat-create-instance.sh → instance.sh create, etc.)
- `docs/updating.md:41,44` — update `scripts/uat/uat-deploy.sh` → `scripts/server/deploy.sh`
- `docs/production-cutover-plan.md:20,25,40,44,50` — update all `scripts/uat/` paths
- `docs/plans/copilot-pr96-triage.md:36,72` — update path references

### CI/CD
- `.github/workflows/deploy-uat.yml` — update any script path references (currently references `/opt/docketworks/repo` not the script paths directly, but should verify)

## Steps

1. `git mv scripts/uat scripts/server`
2. Rename the 4 uat-prefixed scripts within `scripts/server/`
3. Update `source` lines in instance.sh, deploy.sh, dw-run.sh
4. Update all doc references
5. Rename `docs/uat_setup.md` → `docs/server_setup.md`
6. Verify with `grep -r "scripts/uat\|uat-base-setup\|uat-instance\|uat-deploy\|uat-common" .` — should return zero hits (excluding git history)

## What does NOT change
- The `/opt/docketworks/` path on actual servers — that's the install location, not related to "uat"
- `VALID_ENVS="dev uat staging prod"` in common.sh — "uat" is a legitimate environment name
- The GitHub workflow filename `deploy-uat.yml` — that's specifically about deploying to UAT (could be renamed separately but out of scope)

## Verification
- `grep -rn "scripts/uat\|uat-base-setup\|uat-instance\|uat-deploy\|uat-common" --include="*.sh" --include="*.md" --include="*.yml" .` should return nothing
- `bash -n scripts/server/*.sh` — syntax check all scripts
- Read through updated docs to confirm paths are coherent
