# v1 port baseline

v2's bootstrap commit (`ec2c30f`, 2026-08-01 19:10 +1200) was written against v1
(`../docketworks`) at **`2594e93f`** — "Merge pull request #505" (KAN-321 null-only text
migration), the tip of v1 `main` that morning. This hash was reconstructed from v1's `main`
reflog and both repos' commit timestamps; it was not recorded at the time, which is why this
file now exists.

## Ports read the live tree, not a pinned hash

Each port phase reads whatever `../docketworks` has checked out at that moment, so v1 work
landing mid-rewrite is picked up by later phases and silently missing from earlier ones.
**When starting a port phase, note v1's current HEAD here** so the drift stays auditable.

| v2 phase | v1 state read |
|----------|---------------|
| Bootstrap → Phase 1 (2026-08-01 evening) | `2594e93f` |
| Phase 2 models (2026-08-01 22:34) | post-PR #511 working tree (KAN-323 Job checklist fields included) |
| Phase 3a company (2026-08-02 15:00) | KAN-325 branch working tree (PR #516 merge fixes included, pre-merge) |

Before each future port phase, update v1's local `main` (`git -C ../docketworks pull` on
`main`) so the port reads current v1, and add a row above.

## v1 changes after `2594e93f` — port status

Audited 2026-08-03 (v1 origin/main through `4410d88`):

| v1 change | Status in v2 |
|-----------|--------------|
| PR #511/#513 — KAN-323 Finish Job workspace | Job checklist model fields ported (Phase 2). **Pending: Finish tab frontend + job API** — pick up in the job UI phase. |
| PR #514 — skip Xero phone sync for merged companies (`reprocess_xero.py`) | **Pending: port with the Xero sync phase** — v2 `apps/xero` has models only. |
| PR #516 — KAN-325 company merge is Xero-first | Merge service/command fixes ported (Phase 3a, verified). ADR 0034 carried into `docs/adr/`. **Pending: duplicate-identities report `.vue` tweak** — pick up in the CRM frontend phase. |
| `4410d88` — CI mypy incremental cache | Not applicable; v2 CI is separate and mypy is zero-baseline. |

## ADR numbering across the fork

ADR numbering is continuous with v1, but v1 kept minting ADRs after the fork (0034 landed in
v1 on 2026-08-02). When v1 writes a new ADR, carry it into v2 under the **same number** and
shift v2's reserved block if it collides — v1's number wins because it is already referenced
in v1 commits and tickets.
