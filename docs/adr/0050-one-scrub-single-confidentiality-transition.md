# 0050 — One scrub: the single confidentiality transition

Data transitions from confidential to non-confidential in exactly one place:
`manage.py backport_data_backup`'s scrub on the production host. Everything
downstream of that scrub — the dump, the database restored from it, anything
derived from either — is non-confidential **by construction**, and code
treats it that way.

## Rules

**Downstream code never re-treats scrubbed data as confidential.** No secrecy
ceremony (restricted-mode files, umask rituals, cleanup-because-sensitive
steps) in the restore pipeline, and no second scrubber over a dev database —
a dev database restored from a scrubbed dump is already scrubbed. Either move
re-implements the one transition (the duplication pathology ADR 0039 exists
to prevent) and stands as a permanent monument of distrust in the scrubber.
If scrubbed output ever needed downstream protection, that is a scrubber
defect, and the fix belongs at the scrubber.

**A demo export is a plain `pg_dump`.** v1's `export_dev_demo_dump` carried
its own lighter scrubber; it was ported and then removed on this ruling
(2026-08-15). The disposition records it as dropped.

**An instance's own operational data is not confidential on its own disk.**
Dev instances are privately owned; their own Xero registration, AI provider
key and portal credentials already live unprotected in their own database and
`.env`. Wrapping copies of them in permissions ceremony changes no real
exposure — the same reasoning that rejected field-level encryption (per-
instance databases make it key-management theatre).

**The scrub must therefore be COMPLETE, and that is where the effort goes.**
The contract only holds if the one transition removes exactly PII — no more,
no less. KAN-341 (field inventory with an explicit scrub/keep ruling per text
field, completeness gate over all apps) and KAN-340 (adjudication of
inherited over-aggressive behaviours) are the enforcement; the scrubber's
tests pin the coverage contracts.

## Rejected alternative

Belt-and-braces protection downstream ("scrub AND chmod AND redact again at
the next boundary") was rejected because layered re-treatment hides scrubber
defects instead of surfacing them: every downstream layer that "handles"
confidential data makes a real leak at the source look survivable, and the
layers drift apart the way all duplicated policy does.
