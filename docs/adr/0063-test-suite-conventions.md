# 0063 — A test asserts over what it created, takes its actors from the root conftest, and an E2E wait never filters on status
Ratified: owner, 2026-10-01

Every test asserts over what it created and takes its actors from the root `conftest.py` by name; an E2E spec waits on URL and method, never on a status or a disabled control.

## Rules

- **Assert over what the test creates, not over the whole table.** `assert [row["name"] for row in response.json()] == ["Acme", "Zeta"]` looks like a list assertion but is really an assertion that the installation is empty, and it breaks the moment the world is realistic. Scope the query, filter to the rows the test made, or assert the property — sortedness, inclusion, exclusion.
- Actors come from the root conftest by fixture name: `office_staff`, `superuser`, `api` (authenticated office staff), `superuser_api`. `client` stays pytest-django's ANONYMOUS client — an authenticated fixture named `client` is how a `test_requires_authentication` silently stops testing authentication.
- Controls are located by `data-automation-id` (`frontend/docs/data-automation-ids.md`), never by incidental DOM position.
- An E2E wait on a mutation's response matches URL and method only — never status — then asserts success explicitly, with the actual status and body in the failure message. A status-filtered wait can never match a real failure, so a failed mutation surfaces as a generic timeout that hides exactly the regression the wait exists to catch.
- A control whose disabled state is also its in-flight state can be asserted, never awaited. Waiting for it to become enabled passes before the request it guards has landed, so the spec waits on something that can only become true after the response: the next action's control enabling, the row the response creates. `stocktake.spec.ts` waits on "Post stocktake" enabling for this reason.
