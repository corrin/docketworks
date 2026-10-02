# 0043 — Comments explain decisions and constraints

Write for an engineer fluent in the stack who needs to understand Docketworks.
Comments and documentation carry business meaning, decisions, constraints and dependencies
that experience or the surrounding code would not supply.

## Rules

- Explain what the reader needs to maintain the behaviour: a business invariant, a dependency
  outside the local code, a deliberate tradeoff, an unusual framework interaction or the
  intended recovery from a failure. Contract summaries remain useful when they define the
  caller's obligations or the meaning of a result.
- Discuss an alternative only when a competent engineer might reasonably consider it and the
  comparison explains the choice. For example, `apps/core/errors.py` keeps the persistence
  marker on the original exception because the HTTP boundary uses its type to choose a status.
  A comment does not need a rejected alternative to justify its existence.
- Check factual claims against the relevant writers, callers, tests, data or authoritative
  decision. Name the evidence where the claim would otherwise be hard to verify. Distinguish
  observed behaviour from an untested hypothesis, and flag a disagreement between the code
  and its documented contract for resolution.
- State project requirements directly. Explain why Docketworks needs a strict contract or a
  particular recovery path when that choice depends on its business or operating model.
  Existing code and old data are evidence to investigate, not sufficient reasons to preserve
  a design (ADR 0015).
- Preserve useful reasoning when removing lectures, straw-man comparisons or accounts of
  previous arguments with coding tools. Historical incidents and measurements belong beside
  the code when they explain a current constraint; otherwise retain the mechanism and its
  authoritative reference.
- Delete generic programming advice, narration of visible code and repeated instructions
  that add no information. Replacing them with a positive imperative does not add value.
  Comment-count reduction is not a goal; retain the knowledge a future maintainer needs.
- Apply the same standard to docstrings and documentation. Test docstrings state the business
  risk or guarantee (ADR 0025). Operational instructions retain concrete prerequisites,
  commands and recovery procedures.
- AI-originated rationale carries its model-family attribution until ratified (ADR 0051).
  Attribution records provenance; a policy change needs its own authority.
