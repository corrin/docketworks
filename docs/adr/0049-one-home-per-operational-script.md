# 0049 — One home per operational script

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
the client's `adhoc/`. The live counterexample is v1's
`create_leave_entries.py`: an append-only leave backfill whose entire content
was a hardcoded batch of named staff sick/bereavement/unpaid leave. v2
dropped it — the batch was already applied in production, and a future leave
backfill is a client-adhoc CSV over `create_overtime_entries`'s
preview/apply pattern.

**A one-shot does not become a management command.** Registering a command
advertises "run me again"; an already-applied backfill registered as a
command is a loaded gun in `manage.py help`. One-shots that must be recorded
at all are recorded in the disposition ledger (dropped, with the applied
outcome), not in the tree.

**Operator scripts never take pytest-shaped names.** A `test_*.py` under any
directory is one `testpaths` edit or one IDE test-discovery run away from
being collected, and these scripts reach live services and mutate data.
Harnesses are named `*_harness.py`, probes `*_probe.py`
(`ai_chat_harness.py` records the original rationale).

**Promotion is a move, not a copy.** When a repo-adhoc script generalises, it
moves to `scripts/` (or becomes a command if it meets all three criteria) and
the adhoc copy is deleted in the same change — two homes for one concept is
the duplication pathology ADR 0039 exists to prevent.

## Rejected alternatives

- *Port every v1 operator script as a management command* (what the 2026-08
  ops port initially did): rejected because it erases the
  confidentiality and recurrence questions the ladder exists to ask — it is
  how named HR data reached a public branch.
- *A private repo for client scripts instead of client `adhoc/`*: rejected
  for now; per-instance `adhoc/` needs no extra infrastructure and keeps
  client data on the client's own host.
