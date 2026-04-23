# 0010 — Single `deploy.sh` with hostname detection; optimistic CD to both machines

One `scripts/deploy.sh` handles PROD, UAT, and SCHEDULER via hostname detection; CD runs it against both UAT machines in parallel with `continue-on-error`, and the systemd startup service re-runs it on boot so a cold machine catches up to `main`.

- **Status:** Accepted
- **Date:** 2025-12-12
- **PR(s):** Commits `72064b4c` (consolidated deploy.sh, 2025-07-24) and `15e569a9` (dual-machine plan, 2025-07-24) — predates GitHub PR workflow

## Context

Deploy logic was split across three scripts — `deploy_app.sh` (user-level, incomplete, missing service restarts), `deploy_release.sh` (root-level orchestrator with backups and service management), `deploy_machine.sh` (UAT-only full deployment) — with overlapping responsibilities, different approaches to environment detection (directory paths vs service presence), and inconsistent service-restart patterns. Separately, the UAT environment had been split across two machines (always-on scheduler, usually-off frontend/backend) and the CD pipeline didn't know how to handle "one machine is offline."

## Decision

One script: `scripts/deploy.sh`, invoked both by the CD pipeline and by a systemd startup service. It runs as the application user, with `sudo` configured via sudoers for the specific `systemctl restart` commands it needs — no user switching, no root-level orchestration. Environment is detected by hostname (`msm` → PROD, `uat-scheduler` → SCHEDULER, `uat`/`uat-frontend` → UAT) rather than by inspecting paths. The script is idempotent so the same code path handles "fresh deploy from CD" and "machine just booted, catch up to `main`." CD runs against both machines with `continue-on-error: true` on the frontend/backend target so a cold second machine doesn't fail the pipeline — the startup service will catch up when the machine comes online.

## Alternatives considered

- **Keep three scripts, fix `deploy_app.sh`:** still three scripts to maintain; still three places to change when a new step is added.
- **Docker images deployed via registry:** solves the "machine catches up on boot" problem differently, but the stack (Django + npm build + systemd services) is not currently containerised and the migration cost is significant.
- **Fail the CD pipeline if any machine is offline:** would force someone to power on the frontend/backend UAT machine before every merge — the whole point of the split was that it can be off.

## Consequences

- **Positive:** one place to edit deployment logic; boot-time catch-up means the UAT frontend machine can be off for weeks and still come up on the latest `main`; CD doesn't fail on a predictable cold-machine state.
- **Negative / costs:** sudoers entries are per-host and must be kept in sync with the service names the script restarts; hostname-based detection means a renamed host silently hits the `ERROR: Unknown hostname` branch.
- **Follow-ups:** adding a new environment requires a sudoers entry, a hostname case in the script, and optionally a new systemd service name; the original dual-machine plan's `deploy_machine.sh` was folded into this single script — that file no longer exists.
