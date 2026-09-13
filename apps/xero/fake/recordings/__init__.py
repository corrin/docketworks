"""Wire bodies recorded from the real tenant, one per route the fake serves.

Each ``<name>.json`` holds what Xero actually returned, captured at the
transport seam so the SDK's deserialiser never touched it, and cites the run
that produced it. They are the fake's templates for entities the mirror does
not hold, the oracle for the renderer's round-trip test, and what
``test_fake_recordings_current`` re-fetches to alarm on drift (ADR 0050).
"""
