# 0020 — Frontend/Backend separation: data is backend, presentation is frontend

Backend owns data integrity, calculations, persistence, and external integrations. Frontend owns presentation, UI state, and ergonomics. The boundary line is the *kind* of value, not the layer of code.

## Problem

In repos where backend and frontend share a team, the boundary drifts. Backend serializers grow dropdown-choice payloads (`billing_status_options`) shaped for one specific UI. Backend views start returning HTML fragments because a particular page wanted them. Frontend reaches for ad-hoc business logic ("just sum these locally so we don't round-trip") and produces a number that disagrees with the canonical backend total when the user runs a report. The product becomes coherent only if backend and frontend agree on a constantly-moving target, and over time they don't.

## Decision

Two rules:

1. If a value involves the database, business rules, or external systems → **backend**. Frontend reads it as a number/string, never recomputes it.
2. If a value is static UI constants, layout, or ergonomics → **frontend**. Backend never ships dropdown labels, never returns HTML, never shapes responses around what one UI happens to render.

Forbidden: backend serializers for static UI constants; backend views returning HTML or UI-specific structures; frontend making business-logic decisions or recomputing calculated values; frontend bypassing backend validation.

## Why

There is one canonical source for every value the user sees. A UI redesign doesn't touch the API contract — same endpoint, different rendering. A new client (mobile app, BI export, third-party integration) reads exactly what the existing UI reads; no per-client backend dialect. Frontend math drifting from backend math becomes structurally impossible because the frontend doesn't do math on persisted values. Every total in every report comes from one place.

## Alternatives considered

- **Backend-for-Frontend (BFF) layer that shapes data per-UI.** Strongly defendable for organisations with multiple frontends with divergent shapes (web + native + B2B portal). Rejected: docketworks has one frontend; a BFF here is just the backend with extra layers, and it tempts contributors to put business logic in the BFF instead of the canonical backend.
- **Server-rendered pages (Django templates / SSR).** Standard Django. Rejected: ADR 0008 commits to a generated-client SPA shape; SSR-style backend-shapes-the-page is exactly the pattern this rule exists to prevent.

## Consequences

When a UI need conflicts with the boundary, the resolution is to add a derived backend computation, not a frontend shortcut. Costs: more round-trips than a fully-frontend-computed UI; small UI-only adjustments (a dropdown's display text) might still require a backend trip to source the labels. Pays for itself on every report total that reads the same in screenshots, exports, and the database.
