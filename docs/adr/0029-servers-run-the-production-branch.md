# 0029 — Separate integration from production releases

`main` represents integrated work; `production` represents released work.

## Problem

`main` used to represent both integrated work and the production release. A
production fix therefore also shipped every unrelated change merged since the
previous release.

## Decision

Feature PRs target `main`. Testing and UAT servers typically track `main`;
production servers typically track `production`. After UAT verification, a
release PR promotes `main` to `production`.

A hotfix branches from `production`, merges back by PR, deploys, and is
immediately back-merged to `main`.

## Why

Separating integrated work from released work lets production be patched
independently of unreleased changes. Each release is also an explicit,
reviewable promotion.

## Alternatives considered

- **Deploy `main` to production:** simpler, but couples production fixes to all
  integrated work.
- **Release tags:** auditable, but hotfixes still need a branch and "latest
  release" becomes a convention rather than a stable ref.

## Consequences

- Releasing gains one explicit step: the `main` → `production` promotion PR.
- Hotfixes must be back-merged to `main` immediately.
- `production` carries the same branch protections as `main`.
