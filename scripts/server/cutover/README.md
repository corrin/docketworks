# TEMPORARY: v1 -> v2 host cutover helpers

**Delete this whole directory once both hosts (Oracle UAT and production)
run v2.** Nothing here is part of the permanent operating surface; the
permanent scripts (`../server-setup.sh`, `../instance.sh`, `../deploy.sh`)
assume a host that is already v2-shaped and refuse legacy state instead of
accommodating it.

A host may run several instances (the UAT box does); the host step runs
once, the instance step once per instance. Instances on a host can be cut
over one at a time — a still-v1 instance keeps running beside a migrated
one because releases are immutable directories and the repo swap keeps
v1's git objects.

## Order of operations

1. **Prerequisites** (before the maintenance window)
   - The v2 repo has the branch each instance's tracked ref points at
     (`production` for prod instances — create it if only `main` exists).
   - Each instance's `/opt/docketworks/config/<instance>.credentials.env`
     satisfies v2's required list — `sudo ../instance.sh validate-config
     <client> <env>` names anything missing (v1 files lack v2-only keys
     such as `BACKUP_GDRIVE_TEAM_DRIVE_ID`); cutover-instance.sh runs the
     same check before it stops anything. If `GCP_CREDENTIALS` points at
     a path that no longer exists, point it at the instance's existing
     copy: `/opt/docketworks/instances/<instance>/gcp-credentials.json`.
   - The data migration has been rehearsed against a copy of this
     instance's database (`docs/cutover-checklist.md`).

2. `sudo ./cutover-host.sh` — once per host. Records firewall/listener
   state, refuses if public listeners other than 22/80/443 would be lost,
   swaps `/opt/docketworks/repo` to the v2 remote (keeping v1 objects for
   rollback), disables the legacy netfilter-persistent firewall, then runs
   `server-setup.sh` to converge UFW, fail2ban and v2 tooling.

3. `sudo ./cutover-instance.sh <client> <env> [--ref <ref>]` — per
   instance. Validates the credentials and company-defaults files against
   v2's contract (aborting before anything stops if the operator must fix
   them), stops v1 services, takes a verified final v1 backup, builds
   the v2 release, reconfigures the instance onto it (new `.env` contract;
   preserved DB password and SECRET_KEY; fresh JWT_SIGNING_KEY, so every
   session re-logs-in; DB fixture loads deferred, since the database is
   still v1 schema), migrates the data into a fresh v2-schema database,
   swaps the databases, loads the credential-derived DB rows, starts
   services and verifies. The v1 database survives as
   `<db>_v1_final_<timestamp>`.

4. `sudo ../verify-instance.sh <client> <env>` — the permanent verifier;
   also runs automatically at the end of cutover-instance.sh.

## Running rules

**Run these scripts with plain output.** Never pipe them through anything
that can close early (`head`, `grep -m`); with `set -o pipefail` a closed
pipe kills the run mid-step, and the firewall steps are not safe to kill.
Capture with `tee` if a copy is wanted.

**The host step runs once, and enforces it:** once ufw is active,
cutover-host.sh refuses — the migration has happened, and its bundled
steps are available directly (`../server-setup.sh` for convergence, plain
git for the repo). server-setup.sh verifies the ruleset is genuinely
wired in (`assert_ufw_effective`) before and after touching ufw; if that
check fails, do not retry ufw commands — none of them repair the state.
Reboot, or delete every ufw chain (`iptables -F && iptables -X`) and
re-run.

## If it goes wrong

`sudo ./rollback-instance.sh <client> <env>` restores the recorded v1
state: unit files, nginx config, `.env`, release link and the database
(renames the v2 database aside and the preserved v1 database back). Host
state (UFW, fail2ban, repo remote) is left in place — it does not prevent
v1 instances from running, and the recorded snapshot under
`/opt/docketworks/cutover-state/` documents how to unwind it by hand if a
full host retreat is ever needed.
