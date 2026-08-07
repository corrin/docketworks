# Frontend testing plan — field integrity as the app grows

Status (2026-08-07): **binding for the React SPA, partly done.** Written 2026-08-04 while
the frontend was the auth-only scaffold.

- **Landmine 2 is FIXED.** `scripts/checks/export_openapi.py` exists, `frontend/schema.v2.yml`
  is committed and is the codegen input, and CI fails on a stale client. `frontend/schema.yml`
  (v1's frozen baseline) and `schema_parity_diff.py` are **deleted** — read `../docketworks`
  when you need v1's contract. Ignore the parts below that describe doing this.
- **The rest of Phase A is not done**: `src/lib/forms/`, the field manifests, the vitest dom
  project, the boundary-script extensions.
- **This does not replace E2E.** The original framing shrank E2E to "a smoke layer"; that is
  no longer the policy. Done means the E2E spec passes (CLAUDE.md), and these component tests
  are what make each spec cheap to satisfy, not a substitute for one.

## The problem this solves

Fields kept being added to the v1 frontend without regression tests. Canonical instance:
unticking "price TBC" on a purchase order clobbered unrelated fields. Root cause was payload
construction, not missing E2E coverage — v1's PO editor
(`../docketworks/frontend/src/pages/purchasing/po/[id].vue`, `saveLines()`) rebuilt a full
12-field payload for any changed line (`item_code: line.item_code || ''` …), and the backend
coerced `''` → NULL. A one-checkbox PATCH was effectively a whole-line PUT. No test covered
it (`grep -ri tbc frontend/tests/` in v1: zero hits), and the 25-minute E2E suite never
economically could at per-field granularity.

The v2 backend half is already fixed: `_line_write_data()` applies only fields present in
`model_fields_set` (`apps/purchasing/api.py`), with a regression test
(`apps/purchasing/tests/test_allocations_api.py`,
`test_a_patched_line_still_receipts_after_a_price_tbc_toggle`) and parity-ledger entries.
This plan is the frontend half: make "every writable field keeps working" a **mechanical
guarantee**, enforced by the compiler and CI, not by reviewer discipline.

## The enforcement chain

```text
backend adds a field to an update-request schema
→ CI "OpenAPI export is current" fails until frontend/schema.v2.yml is regenerated
→ regen changes types.gen.ts → existing "generated client is current" CI step fails until committed
→ the new key makes the form's field manifest non-exhaustive → tsc fails (in-editor, pre-CI)
→ adding it to the manifest makes the round-trip test's edit map non-exhaustive → tsc fails
→ the new round-trip test asserts the PATCH body deep-equals exactly { field: value }
→ buildPatch — the only legal payload producer (the brand exists only at compile time;
  runtime safety follows from components using buildPatch/buildLinesPatch, enforced above)
```

Every link is a hard failure. TypeScript types are erased at runtime, so exhaustiveness is
enforced at the type level (mapped types over `keyof UpdateRequest`); a small runtime
meta-test cross-checks each manifest against the generated zod schema's `.shape` keys to
catch a manifest declared against the wrong type.

## Layer 1 — the single write path: `src/lib/forms/`

One implementation per concept (ADR 0039): every PATCH body in the app is produced by
`buildPatch` / `buildLinesPatch`. Components never hand-roll payload object literals.

### `src/lib/forms/patch.ts`

Diff-based, not touched-based: compares the original snapshot against edited values, so
typing a value and reverting it emits nothing, and the form-state approach (plain
`useState`, react-hook-form, TanStack Form) stays orthogonal — adopting a form library
later does not touch this contract.

```ts
declare const PATCH_BRAND: unique symbol
/** Only buildPatch/buildLinesPatch can produce this. Never cast to it. */
export type Patch<T> = { [K in keyof T]?: T[K] } & { readonly [PATCH_BRAND]: true }

export interface FieldSpec {
  kind: 'text' | 'number' | 'checkbox' | 'date' | 'select' | 'reference'
  /** ADR 0040: an emptied input ('') is sent as null (clear); unchanged is omitted. */
  nullable?: true
}

export function buildPatch<T extends object>(
  original: T,
  edited: T,
  fields: { readonly [K in keyof T]?: FieldSpec },
): Patch<T>
```

Contract (this is ADR 0040 applied to the client):

| user action | wire |
|---|---|
| left a field untouched (or reverted it) | key **omitted** — backend's `model_fields_set` gate leaves it alone |
| emptied a nullable field | `null` — the one way a client clears a value |
| changed a value | the value |
| — | `undefined` never appears in a body (and `trimStringsDeep` in `src/api/client.ts` strips it as a second line of defence) |

### `src/lib/forms/lines.ts`

`buildLinesPatch(original, edited, fields)` for id-keyed line arrays (PO lines, cost
lines). Semantics:

- edited line **without** an id → full create object (all manifested keys with defined values)
- edited line whose id exists in original → `{ id, ...buildPatch(origLine, line, fields) }`,
  **dropped entirely when the diff is empty** — untouched lines never appear in the payload
- original ids absent from edited → `lines_to_delete`

The motivating payload becomes exactly `{ lines: [{ id, price_tbc: false }] }`.

**Precondition to verify before first use:** the purchasing service must treat lines absent
from the `lines` array as untouched. `lines_to_delete` existing as a separate field implies
it; confirm in `apps/purchasing/services/purchase_order_service.py` before Phase B.

### Enforcement

1. **Type system (primary):** PATCH mutations re-exported from `src/api/index.ts` are
   wrapped so the body parameter is `Patch<PatchedXUpdateRequest>`, not a raw partial. A
   hand-rolled object literal lacks the brand → compile error.
2. **`frontend/scripts/check-api-boundary.mjs` (backstop):** add rules — the tokens
   `as Patch<` / `satisfies Patch<` and any import of `PATCH_BRAND` may appear only in
   `src/lib/forms/`; every `.parse(` / `.safeParse(` call in `src/` must be on a
   *response* schema — flag any call whose receiver resolves to (or aliases) a generated
   request schema, not just the literal token `Request.parse(`, since feature code can
   alias a schema before calling it (see landmine 1 below). Same file walk; the receiver
   check needs the import map, which the script already builds.

## Layer 2 — exact-coverage field manifests

### `src/lib/forms/manifest.ts`

```ts
export interface FormManifest<
  TRequest extends object,
  F extends { [K in keyof TRequest]?: FieldSpec } = { [K in keyof TRequest]?: FieldSpec },
> {
  fields: F
  excluded: { readonly [K in Exclude<keyof TRequest, keyof F>]?: string } // key → written reason
}

/** Every key of TRequest must appear in exactly one of fields/excluded.
 *  A regenerated client that adds a key makes this a compile error naming it. */
export function defineFormFields<TRequest extends object>() {
  return <F extends { [K in keyof TRequest]?: FieldSpec }>(
    fields: F & { [K in Exclude<keyof F, keyof TRequest>]: never },
    excluded: { [K in Exclude<keyof TRequest, keyof F>]: string } & {
      [K in Extract<keyof F, string>]?: never
    },
  ): FormManifest<TRequest, F> => ({ fields, excluded })  // F survives, so `edit` below
                                                           // maps over exactly the manifested keys
}
```

Exclusions carry a reason string a reviewer can check, e.g.
`status: 'changed via workflow buttons, not the edit form; E2E smoke covers it'`,
`lines: 'diffed via buildLinesPatch with poLineFields'`. Adding a key to `excluded` just to
silence the gate, without a reason that survives review, is the forbidden move.

Example (the first real consumer, Phase B):

```ts
// src/features/purchasing/po-edit/fields.ts
export const poLineFields = defineFormFields<PurchaseOrderLineUpdateRequest>()(
  {
    job_id: { kind: 'reference', nullable: true },
    description: { kind: 'text' },
    quantity: { kind: 'number' },
    unit_cost: { kind: 'number', nullable: true },
    price_tbc: { kind: 'checkbox' },
    item_code: { kind: 'text' },
    metal_type: { kind: 'text' },
    alloy: { kind: 'text' },
    specifics: { kind: 'text' },
    location: { kind: 'text' },
    dimensions: { kind: 'text' },
  },
  { id: 'identity key for the diff, not editable' },
)
```

### The runtime cross-check

The type-level gate has one blind spot: a manifest declared against a wrong or stale type
parameter. Close it with one runtime comparison per form. The boundary allows zod imports
only inside `src/api/`, so `src/api/index.ts` exports curated **key lists**, not schemas:

```ts
// src/api/index.ts (addition)
export const updateRequestKeys = {
  purchaseOrder: Object.keys(zPatchedPurchaseOrderUpdateRequest.shape),
  purchaseOrderLine: Object.keys(zPurchaseOrderLineUpdateRequest.shape),
} as const
```

```ts
// src/lib/forms/registry.ts — one entry per editable form, added with each feature slice
export const formRegistry = [
  { name: 'po-edit-line', schemaKeys: updateRequestKeys.purchaseOrderLine, manifest: poLineFields },
] as const

// src/lib/forms/__tests__/field-coverage.test.ts (node project, no DOM)
it.each(formRegistry)('$name manifest exactly covers its schema', (e) => {
  const manifestKeys = [...Object.keys(e.manifest.fields), ...Object.keys(e.manifest.excluded)].sort()
  expect(manifestKeys).toEqual([...e.schemaKeys].sort())
})
```

## Layer 3 — manifest-driven round-trip component tests

### Infra

Dev deps: `jsdom`, `@testing-library/react`, `@testing-library/user-event`,
`@testing-library/jest-dom`, `msw` (v2). MSW rather than an axios spy (ADR 0032, and
because network-layer interception keeps `trimStringsDeep` and the ETag/If-Match
interceptors **inside** the tested loop — that wiring is exactly where field bugs live).

`frontend/vite.config.ts` — split vitest into projects so the four existing node-only
tests stay unpolluted (Vitest 4 removed `environmentMatchGlobs`):

```ts
test: {
  projects: [
    { extends: true, test: { name: 'node', environment: 'node', include: ['src/**/*.test.ts'] } },
    { extends: true, test: { name: 'dom', environment: 'jsdom',
        include: ['src/**/*.test.tsx'], setupFiles: ['./src/test/setup.ts'] } },
  ],
},
```

Convention: `.test.ts` = pure logic (node), `.test.tsx` = component (jsdom). `vitest run`
runs both; no CI script changes. Default jsdom over happy-dom — happy-dom's historical gaps
are form/submit/focus fidelity, this suite's entire subject; revisit only if the dom
project exceeds ~30 s.

New `src/test/`: `setup.ts` (jest-dom matchers, MSW server lifecycle), `msw.ts`
(`setupServer` plus a `capturePatch(path)` helper that registers a one-shot handler
resolving a promise with the request body and responding with the post-save fixture and a
fresh `ETag`), `render.tsx` (`renderWithProviders`: fresh QueryClient with retries off,
minimal router context).

### The harness: `src/test/form-field-roundtrip.tsx`

For each **manifested** field: render the form against an MSW-served fixture (with `ETag`,
so the real If-Match flow runs), change *only that field*, save, and assert the captured
PATCH body **deep-equals exactly** `{ [field]: value }` (line fields via a `wrap` fn:
`{ lines: [{ id, [field]: value }] }`). Exact equality is the point — it proves presence
of the changed key *and absence of every sibling*, which is precisely what E2E never
checked and what the price-TBC bug required.

```ts
export function describeFieldRoundTrips<
  TRequest extends object,
  F extends { [K in keyof TRequest]?: FieldSpec },
>(opts: {
  name: string
  manifest: FormManifest<TRequest, F>
  renderForm: () => Promise<void>
  save: (user: UserEvent) => Promise<void>
  capturePatch: () => Promise<unknown>
  /** One interaction per manifested field — keyed on F (the exact fields object), so an
   *  omission is a tsc error and an excluded key is never demanded. */
  edit: { [K in keyof F]-?:
    (user: UserEvent) => Promise<{ wire: unknown; wrap?: (v: unknown) => unknown }> }
}): void
```

Plus one standing case per form: a no-op save sends no PATCH (or the empty patch is
suppressed before the wire).

Cost: ~15 fields × ~100–200 ms jsdom render ≈ 2–3 s per form — three orders of magnitude
cheaper than the equivalent E2E coverage.

## Layer 4 — E2E is a smoke layer

What stays E2E: **one happy path per feature** ("create PO, edit one field, reload, value
persisted") plus cross-cutting flows component tests cannot honestly exercise: login/logout,
ETag 412 → retry-bus recovery, delta streaming. All per-field behaviour lives in Layer 3.
Porting rule (matches CLAUDE.md's test-porting rule): a v1 spec that fills a form and
asserts a payload or server-side value ports as a component round-trip, **not** an E2E spec.
Target ≤ 2–3 specs per feature and a suite under ~5 minutes, at which point Playwright
joins CI (needs postgres service + Django + `preview:e2e` in the workflow).

Why v1 took ~25 minutes, measured (test-history run `e8rdus2x`, 107 tests, 2026-08-01):
~13 min of tests + ~10 min of pg_dump backup, psql restore, integrity passes and a
hard-coded 90 s "Xero settle" sleep. Inside the 13 min: full UI login per test
(105 × ~2 s ≈ 3.5 min), 342 `networkidle` waits (5.5 min), 348 `waitForTimeout` sleeps
(1.4 min), all on `workers: 1` because tests shared the real dev database.

The port therefore changes four things:

1. **Login once, via API.** A Playwright `setup` project posts to the token endpoint with a
   request context (cookies are server-set HttpOnly, `storageState` captures them), saves
   `playwright/.auth/user.json`; the browser project declares `dependencies: ['setup']` and
   `use: { storageState }`. Only `login.spec.ts` keeps the real UI login.
2. **Parallelism via data isolation, not serialization.** `fullyParallel: true`, multiple
   workers. Each test seeds its own uniquely-named entities through a test-support router —
   `apps/e2e_support/`, mounted only when an `E2E_TEST_SUPPORT` setting is true (e.g.
   `config/settings_e2e.py`) — exposing factory endpoints and a `reset` used only in global
   setup. **No pg_dump/restore, no settle sleep.** Per-worker databases are the escalation
   path if cross-test interference appears; do not build them speculatively.
3. **Ban `networkidle` and `waitForTimeout`.** New `frontend/scripts/check-e2e-hygiene.mjs`
   (same walk pattern as the boundary script) fails on either token under `tests/e2e/`;
   wire into CI. Prerequisite: `dismissToasts` in `frontend/tests/e2e/helpers.ts` uses
   `waitForTimeout` twice — rewrite with expect-polling (`toHaveCount(0)`) first.
4. **Keep** the `autoId` / `data-automation-id` convention, the production-build preview
   harness, `trace: 'on'`, and port v1's console-error-fails-test fixture.

## Landmines to defuse (both live today)

1. **Generated zod defaults re-create the bug client-side.** `zod.gen.ts` update-request
   schemas carry v1 DRF serializer defaults (`price_tbc: z.boolean().optional().default(false)`,
   `quantity: …default(0)`). Any outbound `.parse()` injects the omitted keys, and the
   backend's `model_fields_set` gate then sees them as explicitly provided — resurrecting
   exactly the bug the backend fixed. Rules: outbound request bodies are **never**
   zod-parsed (generated zod serves response validation and key introspection only); do
   not enable hey-api's request `validator`; the boundary script's `Request.parse(`
   tripwire enforces it. When the codegen input flips to v2's export, check whether
   django-ninja emits `default:` on optional update-request fields — if any survive, fix
   the backend schema declaration (`Optional[...] = None`), never post-process generator
   output. Note: ADR 0021 currently implies runtime request validation is intended and
   cites stale v1 paths — correct it when the Phase A ADR is written.
2. **The generated client is the contract's only static check.** It means the
   generated client currently tracks v1, not the live v2 backend; CI's "generated client
   is current" step checks internal consistency only. Fix: new
   `scripts/checks/export_openapi.py` — `django.setup()`, `from config.api import api`,
   `api.get_openapi_schema(path_prefix="/api")` (the exact pattern at
   the exporter), deterministic dump (sorted keys) to a
   committed **`frontend/schema.v2.yml`**; a CI backend step runs it and
   `git diff --exit-code` (same shape as the delta-goldens freshness check);
   `openapi-ts.config.ts` input flips to
   `schema.v2.yml`. Do the flip at the very start of the frontend phase, while auth is the
   only consumer of generated code — the 16k-line regen churn is at its lifetime minimum.
   Expect operation/component renames vs the DRF schema; repairing `src/api/index.ts`'s
   auth re-exports is the bounded blast radius.

## Sequenced tasks

### Phase A — start of the frontend phase, before the first feature ports
1. ~~`scripts/checks/export_openapi.py` + CI freshness step; commit `frontend/schema.v2.yml`~~
   **DONE.** Still worth doing: inspect exported update-request schemas for `default:` and
   fix at the backend if any survive.
2. ~~Flip `openapi-ts.config.ts` to `schema.v2.yml`~~ **DONE.**
3. Write the ADR (*every form field is manifested, diffed, and round-trip tested*). **0044 is
   free again** — it held "v1's frozen schema is the contract authority", deleted 2026-08-07
   with the parity gate; 0042 is still reserved. Correct ADR 0021's stale claims at the same
   time.
4. `src/lib/forms/` (`patch.ts`, `lines.ts`, `manifest.ts`) with pure unit tests, TDD:
   the ADR 0040 table, revert-emits-nothing, line diff sparse/create/delete/untouched-absent.
5. Extend `check-api-boundary.mjs` (Patch brand + zod-parse rules); add
   `check-e2e-hygiene.mjs` (rewrite `dismissToasts` first); wire both into CI.
6. Vitest projects config + `src/test/` harness + one trivial `.test.tsx` smoke proving the
   dom project runs in CI.

### Phase B — first ported edit form (PO edit, the motivating case)
7. Verify sparse-`lines` semantics in the purchasing service (Layer 1 precondition).
8. PO edit built on `buildPatch`/`buildLinesPatch`; manifests in
   `features/purchasing/po-edit/fields.ts`; `updateRequestKeys` in `src/api/index.ts`;
   registry + coverage meta-test; full `describeFieldRoundTrips` suite **including the
   regression case: untick `price_tbc` → body is exactly `{ lines: [{ id, price_tbc: false }] }`**.
9. E2E: `auth.setup.ts` storageState project; one PO happy-path spec;
   `fullyParallel: true`; `apps/e2e_support` router behind `E2E_TEST_SUPPORT`.

### Phase C — template for every subsequent feature slice
10. Each new form: manifest → registry line → round-trip suite → one E2E happy path.
    Playwright joins CI once the backend E2E harness exists and the suite is < ~5 min.

## Open items to be resolved by doing, not deciding

None of these is resolved yet — each states how it WILL be settled when its phase runs.
- jsdom vs happy-dom → start with jsdom; benchmark only if the dom project exceeds ~30 s.
- django-ninja `default:` emission → observe on the first `export_openapi.py` run (Phase A);
  record the command output beside this line when it happens.
- Sparse-`lines` semantics → read the purchasing service before Phase B step 8.
- Data isolation without per-worker DBs → empirical; escalation path documented above.
