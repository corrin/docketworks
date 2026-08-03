# 0021 — Frontend reads and writes the API only through the generated client

All frontend HTTP goes through `/src/api/generated/api.ts`; types come from the OpenAPI schema.

## Rules

- Every API call uses the generated client, with types inferred from the schema (`z.infer<typeof schemas.X>`). A backend rename then surfaces as a TypeScript compile error at the next generation — not as a property that is silently `undefined` until a user reports a blank screen.
- The generated zod schemas also validate at runtime, so a deploy-time version skew fails loudly at the parse step instead of corrupting state.
- After a backend schema change, regenerate: `npm run update-schema && npm run gen:api`.
- Generated files are never hand-edited.
- A missing endpoint is a backend request, never a frontend workaround.

## Do not

- **Raw `fetch`/`axios` or hand-written response types** — hand-maintained types are wrong from the first schema change, and nothing tells you. Reviewers enforce this; the type system cannot see it.
