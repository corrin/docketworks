# 0021 — Frontend reads and writes the API only through the generated client

All frontend HTTP traffic goes through `/src/api/generated/api.ts`. Types come from the OpenAPI schema via `z.infer<typeof schemas.X>`. No raw `fetch`/`axios`, no manual response typing, no hand-edited generated files.

## Problem

Frontend code that hand-writes API calls drifts from the backend schema the moment the schema changes. A backend field rename ships and the frontend keeps "working" — calling a property that's now `undefined`, with no compile error and no runtime warning, until a user reports the screen is blank. Manually typed responses fall out of date silently; raw `fetch` parses JSON into whatever shape the dev guessed at the time of writing.

## Decision

Every API call goes through the generated client at `/src/api/generated/api.ts`. Types are inferred from the schema (`z.infer<typeof schemas.X>` or generated TypeScript types). After a backend schema change, regenerate via `npm run update-schema && npm run gen:api`. Generated files are never hand-edited. Raw `fetch` and `axios` are not used. A missing endpoint is a backend request — never a frontend workaround.

## Why

A backend rename becomes a TypeScript compilation error in the frontend the next time `gen:api` runs — not a silent runtime breakage discovered weeks later. The schema is the single source of truth and there's exactly one path through which frontend code reaches the API. Generated zod schemas double as runtime validation, so even a deploy-time backend version skew fails loudly at the parse step rather than corrupting state.

## Alternatives considered

- **Hand-written API client with hand-written types.** Standard for Vue/React projects with rare schema changes. Rejected: docketworks ships schema changes weekly; hand-maintenance lags every change, so the types are wrong by definition.
- **TanStack Query / SWR with `openapi-typescript`-generated types.** Strong contemporary default. Rejected for now: the current zod-based generated client already gives types plus runtime validation; a query layer adds caching but no type capability. Revisit if caching becomes a real bottleneck.
- **GraphQL with a generated client.** Defendable for query-shape flexibility. Rejected: the backend is REST-shaped per ADR 0006; converting is a much larger decision than a client-library choice.

## Consequences

Schema changes are a structural front-end break — small, well-defined edits per backend rename. Old frontend code does not compile against new schemas without explicit migration. The frontend rules in `frontend/CLAUDE.md` (no raw `fetch`, no manual typing, regenerate after schema changes) are mechanical applications of this ADR. Cost: reviewers must enforce "no raw `fetch`" — the rule is invisible to the type system itself.
