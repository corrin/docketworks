# 0021 — Frontend reads and writes the API only through the generated client

All frontend HTTP goes through the generated client under `frontend/src/api/generated/`, re-exported by `@/api`; types come from the OpenAPI schema.

## Rules

- Every API call uses the generated client, and every request and response type is imported from `@/api` rather than declared by hand. A backend rename then surfaces as a TypeScript compile error at the next generation — not as a property that is silently `undefined` until a user reports a blank screen.
- The generated zod schemas in `zod.gen.ts` also validate at runtime, so a deploy-time version skew fails loudly at the parse step instead of corrupting state.
- After a backend schema change, export the wire contract with `uv run python -m scripts.checks.export_openapi` and then regenerate the client with `npm run gen:api`. Both run as commit hooks from the root `.pre-commit-config.yaml` (there is no husky), so a stale client fails the commit tier rather than reaching CI. The `frontend-boundary` hook (`frontend/scripts/check-api-boundary.mjs`) fails an `axios` import or an import of generated internals outside `src/api`; a raw `fetch` is caught only in review.
- Generated files are never hand-edited.
- A missing endpoint is a backend request, never a frontend workaround.
- GPT: The quoting-chat embed uses ChatKit's typed SDK for its own conversation protocol and transient thread state (ADR 0041). Its transport lives in `frontend/src/api/chatkit.ts` and shares application session recovery; its configuration remains generated API + TanStack Query. Django enforces office access, job scope and CSRF at the SDK endpoint. This exception covers ChatKit traffic only.

## Do not

- **Raw `fetch`/`axios` or hand-written response types** — hand-maintained types are wrong from the first schema change, and nothing tells you.
- **Duplicate ChatKit's thread cache, message components or SSE protocol in application code** — the SDK owns its protocol; the exception above covers its traffic, not a reimplementation of it.
