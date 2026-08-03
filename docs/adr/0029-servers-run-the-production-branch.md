# 0029 — Separate integration from production releases

`main` is integrated work; `production` is released work.

## Rules

- Feature PRs target `main`. Testing and UAT servers typically track `main`; production servers typically track `production`.
- A release is a promotion PR from `main` to `production` after UAT verification — production can be patched without shipping every change merged since the last release.
- A hotfix branches from `production`, merges back by PR, deploys, and is immediately back-merged to `main`.
- `production` carries the same branch protections as `main`.
