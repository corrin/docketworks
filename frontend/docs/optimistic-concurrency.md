# Optimistic concurrency: ETags and If-Match

How the frontend cooperates with the backend's optimistic-concurrency contract
(ADR 0003) on Job and Purchase Order mutations. The design goal is that
**feature code never touches an ETag** — capture, storage, header attachment,
and conflict handling are all centralized.

## The contract

- Every versioned GET returns a **strong** ETag derived from the resource's
  `updated_at` (`apps/core/etag.py` — value shape
  `<resource>:<id>:<iso-timestamp>`). Mutation responses carry the fresh
  version in the `X-Resource-Version` header.
- Mutations require `If-Match` with the exact current version. A mismatch is
  **412 Precondition Failed**; a missing header is **428 Precondition
  Required**.
- `If-None-Match` on GET yields 304 when unchanged.
- Weak validators (`W/…`) are ignored by the client on capture — only strong
  values enter the store. (The pre-rewrite backend issued weak `W/"job:…"`
  tags; the current backend issues strong ones.)

Covered resources and mutation endpoints (the single source of truth is
`RULES` in `src/lib/concurrency/interceptors.ts`):

- **job** — versions captured from `/api/job/jobs/…` responses (excluding
  `status-choices` and `weekly-metrics`); `If-Match` required on job detail
  PUT/PATCH/DELETE, `POST …/events`, `POST …/undo-change`,
  `POST …/quote/accept`.
- **po** — versions captured from `/api/purchasing/purchase-orders/…`;
  `If-Match` required on PO detail PATCH and on
  `POST /api/purchasing/delivery-receipts/` (the PO id comes from the request
  body there, not the URL).

## How it works client-side

All of it lives in `src/lib/concurrency/` and is wired once onto the generated
hey-api client's axios instance in `src/api/client.ts`:

1. **Capture** — a response interceptor recognises versioned endpoints,
   extracts the strong `X-Resource-Version`/`ETag`, and stores it in the
   module-level map in `etag-store.ts`, keyed `<kind>:<id>` (`job:<uuid>`,
   `po:<uuid>`). One generic store for every resource kind — a per-resource
   sibling store is the duplication this layout exists to prevent.
2. **Attach** — a request interceptor recognises mutation endpoints and adds
   `If-Match` from the store. Feature code calls the generated mutation hooks
   and never sets the header.
3. **Conflict** — on 412 or 428 the response interceptor:
   - invalidates the resource's TanStack Query cache through the invalidator
     registered in `src/api/query-client.ts`
     (`registerConcurrencyInvalidator('job' | 'po', …)`), so the UI refetches
     the server's current state and re-captures the fresh version;
   - shows a toast ("This job was updated by another user. Data reloaded.")
     with a **Retry** action that emits on the retry bus (`retry-bus.ts`);
   - rejects with `ConcurrencyError` so the caller can distinguish a conflict
     from an ordinary failure (`isConcurrencyError`).
4. **Retry** — a feature that supports replaying the user's rejected input
   subscribes with `onConcurrencyRetry(kind, id, handler)`. The live example is
   `useJobFieldSave` (`src/features/job/`), which keeps the rejected field
   changes and replays them against the refreshed server baseline when the
   user clicks Retry.
5. **Logout** — `clearEtags()` drops the store.

## Adding a new versioned resource

Do not write a parallel mechanism. Extend the existing one:

1. Add the kind to `ResourceKind` (`retry-bus.ts`).
2. Add a `ResourceRule` to `RULES` in `interceptors.ts` (versioned-endpoint
   matcher, mutation matcher, id extraction, 412/428 copy).
3. Register its query invalidator in `src/api/query-client.ts`.
4. Extend `src/lib/concurrency/__tests__/interceptors.test.ts`.

## UI expectations

- On conflict the user sees the toast, the form re-renders with the server's
  current data (query invalidation), and Retry re-applies their input where a
  feature supports it.
- Disable/serialize submission while a mutation is in flight; the store always
  holds at most one version per resource, so overlapping mutations from the
  same tab race on it.

## Manual testing checklist

- GET a job, mutate it from a second tab, then mutate from the first: expect
  the 412 toast, a refreshed form, and a successful Retry.
- Mutate with the store cleared (fresh reload straight to a deep-linked
  mutation): expect 428 handled the same way.
- Confirm delivery-receipt POSTs conflict correctly — their PO id lives in the
  body, and the interceptor parses it from there.
