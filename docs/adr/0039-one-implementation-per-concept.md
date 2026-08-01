# ADR 0039 — One implementation per concept

## Status

Accepted (2026-08-02).

## Context

v1's defining pathology was "remarkably similar" parallel implementations
with no good reason: duplicate calculations that slowly diverged, two job
services, three cost-line grids, three etag modules, five duplicate-detection
subsystems — most written by successive AI sessions that did not find the
existing implementation and wrote a fresh one. Later sessions then wrote
tests and documentation that *enforced* the divergence. The v2 rewrite
exists in large part to kill this pattern, and v2 will also be largely
AI-written, so the root cause persists unless structurally countered.

## Decision

1. **Search before implement.** Before writing any new function, component,
   service, or endpoint, search the codebase for an existing implementation
   of the concept. A near-match gets extended or generalised — never a
   sibling.
2. **One obvious home per concept.** Layout keeps finding code cheaper than
   rewriting it: small feature-scoped modules with predictable names; one
   generated API layer on the frontend so data access cannot fork; the layer
   contract (import-linter) and API-boundary script enforce the homes that
   can be machine-enforced.
3. **Divergence is never load-bearing.** When two implementations of one
   concept are found, one canonical behaviour is chosen (the user arbitrates
   if the difference is user-visible) and the rest are deleted — together
   with any tests or documentation that entrench the divergence. Tests that
   assert both sides of a divergence are evidence of the pathology, not
   protection against it.
4. **Porting rule.** Code is never ported from v1 by copying a single
   implementation without first checking whether it has siblings.

## Consequences

- Slightly slower first-line-of-code; dramatically cheaper maintenance and
  smaller diffs.
- Some duplication is invisible to tooling; reviews (human, agent, and
  `/code-review`) treat "does this already exist?" as a standing question.
- Related: ADR 0032 (prefer libraries — the same principle pointed at the
  ecosystem instead of the codebase).
