# Fix client dropdown E2E failure (regex with unescaped parens)

## Context

`frontend/tests/job/edit-job-settings.spec.ts:479` uses
`new RegExp(`^${shopClientName}`)` to find the shop client option. With
`shopClientName = "MSM (Shop)"` the unescaped parens become a regex capture
group, so the pattern actually matches `"MSM Shop"` — which doesn't exist.
`waitFor` times out and this is the single blocking failure when running
`npm run test:e2e` against production.

The regex was introduced by commit `5ee56a61` ("Fix client option match (name
includes email)") because `ClientLookup.vue` renders the client name and email
as two sibling `<div>`s inside `role="option"`, making the option's accessible
name `"MSM (Shop) lakeland@gmail.com"` and breaking the original
`{ name, exact: true }` matcher. The dev switched to a prefix regex but forgot
to escape the interpolated string.

The email line in the dropdown is a low-value convenience and is not used to
disambiguate near-duplicate client names. Product decision: drop it. Once the
option's accessible name is just the client name again, the test can revert
to plain string equality, which sidesteps regex escaping entirely.

## Changes

### 1. `frontend/src/components/ClientLookup.vue`
Remove the email line from the option rendering. Delete line 47:

```vue
<div v-if="client.email" class="text-sm text-gray-500">{{ client.email }}</div>
```

Keep the selected-client preview block at lines 92–97 untouched (that's outside
the `role="option"` and unrelated to the test failure). Do not touch any other
styling in this component.

### 2. `frontend/tests/job/edit-job-settings.spec.ts`
Three call sites in the `change client` test (lines 479, 491, 500) all interpolate
`shopClientName` into a `RegExp` and have the same unescaped-parens bug. Once the
option's accessible name is exactly the client name, plain string matching works:

- **Line 479:** revert to `page.getByRole('option', { name: shopClientName, exact: true })`
- **Line 491:** change `toHaveValue(new RegExp(shopClientName))` to `toHaveValue(shopClientName)`
- **Line 500:** same as line 491

Lines 491/500 aren't reached today because 480 times out first, but they have
the identical bug and would fail once 479 is unblocked. Same test function, same
root cause — fixing them together keeps the test green end-to-end.

Do not touch any other test in this file.

## Critical files

- `frontend/src/components/ClientLookup.vue` (line 47)
- `frontend/tests/job/edit-job-settings.spec.ts` (lines 479, 491, 500)

## Verification

From `frontend/`:

1. `npm run type-check`
2. `npm run lint`
3. Confirm the dev DB is clean and production is reachable at `APP_DOMAIN`
   from backend `.env`. If the DB is stale:
   `npm run test:e2e:reset -- --confirm`
4. `npx playwright test tests/job/edit-job-settings.spec.ts -g "change client"`

Pass criteria: the `change client` test runs to completion (option found,
client selected, autosave confirmed, value persisted across reload).

## Out of scope

- Other `ClientLookup.vue` styling, the selected-client preview block, or the
  composable.
- Other tests in `edit-job-settings.spec.ts`.
- Anything outside `frontend/`.
