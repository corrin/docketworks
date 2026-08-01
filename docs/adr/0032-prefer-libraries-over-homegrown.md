# 0032 — Less code is better: prefer libraries over homegrown implementations

For any capability a well-maintained library provides, we install the library. Writing our own implementation instead is a deliberate, documented exception — never the default.

## Status

Accepted

## Context

The code we own is the code we pay for — forever. Every homegrown utility is a line we test, secure, document, and carry through every future change; a dependency that does the same job is code someone else maintains on our behalf. A homegrown implementation also tends to be a worse version of a library that already exists: it reimplements a subset, misses edge cases, has no docs, and drifts as the person who wrote it moves on. Left unchecked, these accrete into a private standard library that duplicates, badly, things the ecosystem already solved.

The principle is not "add every dependency." A dependency is also a liability — supply-chain surface, transitive weight, an upstream that can break or vanish. The rule is about *ownership*, not byte count: for a real capability, not-owning the code beats owning it; for something trivial, neither write much nor pull a heavyweight dependency to avoid a few lines.

## Decision

Reach for a well-maintained library first. Writing custom code for something a library provides requires an **explicit, deliberate, recorded** justification for rejecting the library — a line in the PR description for ordinary cases, a new ADR for a significant or repeated surface. "We wrote our own" carries the burden of proof; "we added a dependency" is the default.

Legitimate, stated reasons to go custom:

- No library covers the need, or the closest ones are unmaintained / red-flagged (abandoned, insecure, incompatible license).
- The need is small enough that a dependency's cost (supply chain, transitive deps, bundle) outweighs the handful of lines it would save.
- The library would demand more glue and adaptation than it removes.

Absent such a reason, replacing owned code with a library — or deleting owned code a library makes redundant — is always a welcome change, done atomically with every call site migrated in the same PR (ADR 0017).

## Why

Minimising the code we own is the highest-leverage way to keep the system maintainable: unwritten code has no bugs, needs no tests, and never rots. Preferring libraries makes that concrete for the large class of problems the ecosystem has already solved well. Forcing the *justification* to be explicit stops homegrown reimplementation from happening by default — the usual path isn't a decision to reinvent, it's the absence of a decision to check for a library first.

## Consequences

- Reviewers challenge any new homegrown implementation of a solved problem and ask which library was considered and why it was rejected; an unrecorded reinvention is a review finding.
- Deleting a homegrown utility in favour of a library needs no special justification — it is the direction of travel.
- New dependencies are still weighed (maintenance, license, transitive cost); this ADR raises the bar for writing code, it does not lower the bar for adding deps.
- ADR 0031 (replacing the homegrown `debugLog` wrapper with the `debug` library) is the first application of this principle; expect more as owned utilities are retired.
