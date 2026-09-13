# 0049 — Operational scripts are homed by confidentiality and recurrence

Operational code — repairs, backfills, probes, harnesses — gets its home from
two questions: **is it confidential, and is it expected to run again?** The
answers place it on a ladder, and promotion up the ladder is deliberate, never
a side effect of porting.

| home | criteria | committed to this repo |
|---|---|---|
| client `adhoc/` | anything confidential: named people, client-specific data, one client's secrets | never — this repo is public OSS |
| repo `adhoc/` | written for one client, plausibly useful to others, not yet promoted | yes, once it contains nothing confidential |
| `scripts/` | promoted: cross-client, operator-run, no anticipated schedule | yes |
| management command | cross-client AND anticipated repeated runs AND needs Django context | yes |

## Rules

**Confidential content never enters the repo, even inside a useful mechanism.**
A command whose mechanism is sound but whose payload is client data splits:
the mechanism ships (or already exists — search first), the payload stays in
the client's `adhoc/`. A leave backfill is a client-adhoc CSV over
`create_overtime_entries`'s preview/apply pattern, never a committed batch of
named staff.

**One-shots that must be recorded at all are recorded in the disposition
ledger** (dropped, with the applied outcome), not in the tree.

**Harnesses are named `*_harness.py`, probes `*_probe.py`.**

**Promotion is a move, not a copy.** When a repo-adhoc script generalises, it
moves to `scripts/` (or becomes a command if it meets all three criteria) and
the adhoc copy is deleted in the same change — two homes for one concept is
the duplication pathology ADR 0039 exists to prevent.

## Do not

- **Register a one-shot as a management command** — a command advertises
  "run me again", and an already-applied backfill in `manage.py help` is a
  loaded gun.
- **Give an operator script a pytest-shaped name** — a `test_*.py` under any
  directory is one `testpaths` edit or one IDE test-discovery run away from
  being collected, and these scripts reach live services and mutate data.
- **Port an operator script as a management command because that is where v1
  had it** — it skips the confidentiality and recurrence questions the ladder
  exists to ask, which is how named HR data reaches a public branch.
