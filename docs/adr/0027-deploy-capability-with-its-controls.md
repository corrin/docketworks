# 0027 — A Capability Deploys With The Means To Operate It

A change that introduces governable state ships — in the same deployable increment — the surface that lets operators see and change that state.

## Problem

Labour subtypes (names, rates, active flags) shipped to production seeded only by
migration, with the management UI scoped into a separate, later, un-started ticket.
Production carried configurable data nobody could configure: routine rate changes needed a
migration, operational knobs were invisible, and the gap surfaced as bug reports scattered
across several tickets for what was one unfinished capability. The tracker had split one
deployable unit into fragments, and the fragments shipped independently.

## Decision

Scope work by the **deployable capability**, not by ticket boundaries. When a change
introduces state an operator is expected to read, set, or retire — rates, catalogues,
toggles, anything tunable per install — the surface to manage that state ships in the same
increment. Do not deploy a capability whose configuration, management, or retirement is
deferred to a later ticket. A ticket split that strands the means of control is an artifact
of planning, not a licence to ship half a feature.

Reporting and analysis built *on top of* a capability are a separate unit and may ship
later; the means to *operate* the capability are not.

## Why

A deployed capability is judged by whether it can be used and governed in production, not
by whether one ticket's acceptance criteria were met. Software that introduces tunable
state without the means to tune it is broken on arrival: it forces migrations for routine
config, hides operational knobs, and disperses the confusion across tickets that each look
small. This is the feature-surface analogue of
[ADR 0017](0017-zero-backwards-compatibility.md): as a rename changes every call site in
one PR, a capability ships every part needed to run it in one increment. The discipline
that *catches* a violation is the test plan ([ADR 0026](0026-plan-the-tests-before-approval.md)):
a user-facing capability owes an end-to-end test, and an E2E that exercises operating the
capability fails when the controls are absent — surfacing the gap at plan time instead of
in production.

## Alternatives considered

- **Trust the tracker's breakdown** — ship each ticket as it completes, management UI
  later. Right when tickets are genuinely independent; wrong when the split severs a
  capability from its controls, because the increments aren't independently operable and
  "shipped" then overstates what's usable.
- **Feature-flag the capability until its management surface lands** — keep the
  half-feature dark in prod. Legitimate for staged rollout, but here it adds flag machinery
  and a dark-launch window to paper over a planning split that should simply not have
  shipped yet.

## Consequences

Some tickets grow: a capability plus its management surface is one PR, not two. Estimation
happens at the capability level — "add labour subtypes" is sized to include managing them.
In exchange every deploy is operable, config stops requiring migrations, and bug reports
attach to one coherent unit instead of scattering across fragments. Reporting/analysis
remains a separate, later unit by design.
