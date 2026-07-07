# 0029 — Servers run the production branch

Servers only ever deploy `production`; `main` is the integration branch, and releasing is an explicit merge from `main` into `production`.

## Problem

Merging to `main` and deploying to servers were the same event: `deploy.sh` resolved `origin/main`, so anything merged was immediately what the next deploy shipped. A production bug could not be patched without also shipping every unrelated change that had landed on `main` since the last deploy, and long-running structural work (renames, migration squashes) sat between a diagnosed prod bug and its fix.

## Decision

Servers only ever run the `production` branch. All feature PRs target `main` as before. A release is a promotion PR merging `main` → `production`, followed by deploy to UAT, verification, then deploy to prod. A hotfix is a branch cut from `production`, merged into `production` by PR, deployed, and back-merged to `main` immediately so no fix exists only on `production`. Nothing is ever pushed directly to `production`, and no server is ever pointed at any other ref except transiently via `deploy.sh --ref` for candidate verification on UAT.

## Why

Separating "integrated" from "released" makes the deployable state an explicit, deliberate ref instead of a side effect of merge timing. Prod can be patched from exactly what prod runs, regardless of what is in flight on `main`; `main` can absorb large structural work without freezing releases. The promotion merge is also the natural audit point: the diff of the promotion PR is precisely what the fleet is about to receive. Keeping every server (prod, UAT, demo) on the same branch preserves UAT/prod parity — UAT verifies the very ref prod will get, not an approximation.

## Alternatives considered

- **Deploy `main` everywhere (status quo):** simplest possible model and fine while the project was one instance with continuous deploys. Wrong once multiple paying instances need patching independently of integration velocity.
- **Release tags instead of a branch:** deploy pinned tags (`prod-YYYY-MM-DD-<sha>`). Auditable, but hotfixes need a branch anyway, "latest release" becomes a convention rather than a ref, and every tool that today asks "what should servers run?" needs tag-resolution logic. A branch is the same thing with a stable name.
- **Per-instance release pinning:** each instance records its own ref. Maximum flexibility, but it institutionalises fleet drift; the shared-release directory design (one SHA, many instances) deliberately pushes the other way.

## Consequences

- Releasing gains one explicit step: the `main` → `production` promotion PR. Deploys themselves are unchanged (`deploy.sh` now resolves `origin/production` by default).
- Hotfixes must be back-merged to `main` in the same working session; a fix that exists only on `production` is a regression waiting to be re-released.
- `production` carries the same branch protections as `main`.
- Anything that assumes servers track `main` (docs, boot-time catch-up units, operator habit) must say `production` instead.
