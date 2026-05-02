# 0010 — Single `deploy.sh` with hostname detection; optimistic CD to both machines

One `scripts/deploy.sh` handles PROD, UAT, and SCHEDULER via hostname detection. CD runs it against both UAT machines in parallel with `continue-on-error`; the systemd startup service re-runs it on boot so a cold machine catches up to `main`.

## Problem

Deploy logic was split across three scripts (`deploy_app.sh`, `deploy_release.sh`, `deploy_machine.sh`) with overlapping responsibilities, different environment-detection approaches (directory paths vs service presence), and inconsistent service-restart patterns. Separately, the UAT environment is split across two machines (always-on scheduler, usually-off frontend/backend) and the CD pipeline didn't know how to handle "one machine is offline."

## Decision

One script: `scripts/deploy.sh`, invoked both by CD and by a systemd startup service. Runs as the application user, with `sudo` configured via sudoers for the specific `systemctl restart` commands it needs. Environment is detected by hostname (`msm` → PROD, `uat-scheduler` → SCHEDULER, `uat`/`uat-frontend` → UAT). The script is idempotent: same code path handles "fresh deploy from CD" and "machine just booted, catch up to `main`." CD runs it against both UAT hosts with `continue-on-error: true` on the frontend/backend target so a cold machine doesn't fail the pipeline — the startup service catches it up later.

## Why

One file for deployment logic means one place to read, one place to edit. Hostname detection makes "which environment am I?" a property of the host, not a flag passed in by the caller (which gets forgotten). The boot-time idempotent re-run is what lets the UAT frontend/backend machine be off for weeks and still come up on the latest `main`; without it, someone has to remember to redeploy after powering it on.

## Alternatives considered

- **Docker images deployed via registry.** Strongly defendable — solves the "machine catches up on boot" problem differently (pull-on-start), and gives reproducible builds. Rejected for now: the stack (Django + npm build + multiple systemd services) is not currently containerised and the migration cost is significant for a tooling improvement, not a feature.

## Consequences

One place to edit deployment logic; UAT frontend can be off indefinitely and still self-heal. Cost: sudoers entries are per-host and must be kept in sync with the service names the script restarts; a renamed host silently hits the `Unknown hostname` branch.
