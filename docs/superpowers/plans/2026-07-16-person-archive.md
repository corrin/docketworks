# Person Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users retire departed people so they drop out of everyday views (directory search, person selectors) without hard-deleting, reversibly.

**Architecture:** `Person.is_active` is the retirement flag. Removing a person's last active company link archives them; adding/restoring any link un-archives them. Archived people stay viewable so the CRM restore-link lifecycle keeps working. An explicit PersonDetail "Archive person" action and a directory "Show archived" filter round it out. Backend-first (5 tasks), then regen the client and do the frontend (4 tasks).

**Tech Stack:** Django REST Framework + DRF-spectacular (backend), Vue 3 + TS + zodios generated client + Playwright/vitest (frontend).

## Global Constraints

- Every exception handler persists once via `persist_app_error(exc)` and re-raises through the `AlreadyLoggedException` two-arm pattern (ADR 0019/0001). Match surrounding service style.
- Backend authoritative type check: `bash scripts/check_mypy.sh`. New code must be fully type-clean; no `Any`/casts/ignores as shortcuts (ADR 0028).
- Frontend: generated `api` client only (`@/api/client`); immutable state updates; `<script setup lang="ts">`; new/touched interactive elements expose stable `data-automation-id`s.
- `is_active` is the single source of truth for archived state — do not compute "archived" from link counts anywhere.
- Backend tests run with `poetry run python manage.py test <dotted.path> -v1`. Do not run the ~25-min e2e suite during implementation; write the spec only.
- Never hand-edit `mypy-baseline.txt` or `__init__.py`.

---

### Task 1: Archive a person when their last active company link is removed

**Files:**
- Modify: `apps/company/services/person_service.py` (`remove_company_link`, ~`:325-357`)
- Test: `apps/company/tests/test_person_api.py`

**Interfaces:**
- Consumes: existing `remove_company_link(*, person: Person, company: Company) -> None`, which already computes `projected_company_ids` (the person's remaining active links excluding this company).
- Produces: after this task, removing a person's last active link sets `person.is_active = False`.

Note: `test_person_api.py` currently contains `test_removing_last_link_keeps_person_active` (asserts the person stays active). This task **replaces** that test's intent — the person is now archived.

- [ ] **Step 1: Replace the stale test with the archive assertion**

In `apps/company/tests/test_person_api.py`, replace the whole `test_removing_last_link_keeps_person_active` method with:

```python
    def test_removing_last_link_archives_person(self) -> None:
        """Removing a person's only active company link retires (archives) them."""
        person = self._person(company=self.company_a)

        with patch("apps.crm.tasks.rematch_phone_calls_task.delay"):
            response = self.client.delete(
                f"/api/people/{person.id}/company-links/{self.company_a.id}/"
            )

        self.assertEqual(response.status_code, 204)
        person.refresh_from_db()
        self.assertFalse(person.is_active)
        link = CompanyPersonLink.objects.get(person=person, company=self.company_a)
        self.assertFalse(link.is_active)
```

- [ ] **Step 2: Run the test, verify it FAILS**

Run: `poetry run python manage.py test apps.company.tests.test_person_api.PersonApiTests.test_removing_last_link_archives_person -v2`
Expected: FAIL — `person.is_active` is still `True` (assertFalse fails).

- [ ] **Step 3: Add the cascade in `remove_company_link`**

In `apps/company/services/person_service.py`, change the tail of `remove_company_link` from:

```python
        link.is_active = False
        link.is_primary = False
        link.save(update_fields=["is_active", "is_primary", "updated_at"])
        _schedule_person_phone_rematch(person)
```
to:
```python
        link.is_active = False
        link.is_primary = False
        link.save(update_fields=["is_active", "is_primary", "updated_at"])
        if not projected_company_ids and person.is_active:
            # Removing the person's last active company link retires them.
            person.is_active = False
            person.save(update_fields=["is_active", "updated_at"])
        _schedule_person_phone_rematch(person)
```

- [ ] **Step 4: Run tests, verify PASS**

Run: `poetry run python manage.py test apps.company.tests.test_person_api -v1`
Expected: PASS (all tests, including `test_removing_link_preserves_person_and_other_company` which keeps the person active because company_b link remains).

- [ ] **Step 5: Commit**

```bash
git add apps/company/services/person_service.py apps/company/tests/test_person_api.py
git commit -m "feat(crm): archive a person when their last company link is removed"
```

---

### Task 2: Un-archive a person when a company link is added or restored

**Files:**
- Modify: `apps/company/services/person_service.py` (`put_company_link`, `:281-322`)
- Test: `apps/company/tests/test_person_api.py`

**Interfaces:**
- Consumes: `put_company_link(*, person, company, data) -> CompanyPersonLink` (create/reactivate a link), reached by `PUT /api/people/{person_id}/company-links/{company_id}/`.
- Produces: after this task, `put_company_link` sets `person.is_active = True` when the target person was archived.

Note: this task depends on Task 3's gate relaxation to be reachable via HTTP for an archived person, but the service-level behaviour and its unit test stand alone. Test at the service layer here to avoid the ordering coupling.

- [ ] **Step 1: Write the failing test (service-level)**

Add to `apps/company/tests/test_person_api.py`:

```python
    def test_restoring_a_link_unarchives_the_person(self) -> None:
        """Adding/reactivating any company link brings an archived person back."""
        from apps.company.services.person_service import (
            put_company_link,
            remove_company_link,
        )

        person = self._person(company=self.company_a)
        with patch("apps.crm.tasks.rematch_phone_calls_task.delay"):
            remove_company_link(person=person, company=self.company_a)
        person.refresh_from_db()
        self.assertFalse(person.is_active)

        with patch("apps.crm.tasks.rematch_phone_calls_task.delay"):
            put_company_link(
                person=person,
                company=self.company_a,
                data={"position": None, "notes": None, "is_primary": False},
            )
        person.refresh_from_db()
        self.assertTrue(person.is_active)
```

- [ ] **Step 2: Run the test, verify it FAILS**

Run: `poetry run python manage.py test apps.company.tests.test_person_api.PersonApiTests.test_restoring_a_link_unarchives_the_person -v2`
Expected: FAIL — person stays archived (`assertTrue(person.is_active)` fails).

- [ ] **Step 3: Un-archive in `put_company_link`**

In `apps/company/services/person_service.py`, inside `put_company_link`, immediately before `_schedule_person_phone_rematch(person)` (after the `if existing is None / else` block that sets `link`), add:

```python
        if not person.is_active:
            person.is_active = True
            person.save(update_fields=["is_active", "updated_at"])
```

- [ ] **Step 4: Run tests, verify PASS**

Run: `poetry run python manage.py test apps.company.tests.test_person_api -v1`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/company/services/person_service.py apps/company/tests/test_person_api.py
git commit -m "feat(crm): un-archive a person when a company link is added or restored"
```

---

### Task 3: Make archived people viewable and their links restorable over HTTP

**Files:**
- Modify: `apps/company/views/person_views.py` (`PersonDetailView` `:76`; `PersonCompanyLinksView.get` `:161`; `PersonCompanyLinkDetailView.put` `:176`, `.delete` `:197`)
- Test: `apps/company/tests/test_person_api.py`

**Interfaces:**
- Consumes: the archive/un-archive behaviour from Tasks 1-2.
- Produces: `GET /api/people/{id}/` returns archived people (200, not 404); `PUT /api/people/{id}/company-links/{company_id}/` works on an archived person and (via Task 2) un-archives them.

Rationale: these four person lookups currently filter `is_active=True`, which 404s archived people and blocks the restore-link lifecycle. Contact-method views stay gated (out of scope).

- [ ] **Step 1: Write the failing HTTP tests**

Add to `apps/company/tests/test_person_api.py`:

```python
    def test_detail_returns_an_archived_person(self) -> None:
        person = self._person(company=self.company_a)
        with patch("apps.crm.tasks.rematch_phone_calls_task.delay"):
            self.client.delete(
                f"/api/people/{person.id}/company-links/{self.company_a.id}/"
            )

        response = self.client.get(f"/api/people/{person.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_active"])

    def test_restore_link_over_http_unarchives_archived_person(self) -> None:
        person = self._person(company=self.company_a)
        with patch("apps.crm.tasks.rematch_phone_calls_task.delay"):
            self.client.delete(
                f"/api/people/{person.id}/company-links/{self.company_a.id}/"
            )
        person.refresh_from_db()
        self.assertFalse(person.is_active)

        with patch("apps.crm.tasks.rematch_phone_calls_task.delay"):
            response = self.client.put(
                f"/api/people/{person.id}/company-links/{self.company_a.id}/",
                data={"position": "", "notes": "", "is_primary": False},
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_active"])
        person.refresh_from_db()
        self.assertTrue(person.is_active)
```

- [ ] **Step 2: Run the tests, verify they FAIL**

Run: `poetry run python manage.py test apps.company.tests.test_person_api.PersonApiTests.test_detail_returns_an_archived_person apps.company.tests.test_person_api.PersonApiTests.test_restore_link_over_http_unarchives_archived_person -v2`
Expected: FAIL — both 404 (archived person filtered out).

- [ ] **Step 3: Relax the four person lookups**

In `apps/company/views/person_views.py`:

1. `PersonDetailView` — change `queryset = Person.objects.filter(is_active=True)` to:
```python
    queryset = Person.objects.all()
```
2. `PersonCompanyLinksView.get` — change `person = get_object_or_404(Person, id=person_id, is_active=True)` to:
```python
        person = get_object_or_404(Person, id=person_id)
```
3. `PersonCompanyLinkDetailView.put` — same change:
```python
        person = get_object_or_404(Person, id=person_id)
```
4. `PersonCompanyLinkDetailView.delete` — same change:
```python
        person = get_object_or_404(Person, id=person_id)
```

- [ ] **Step 4: Run tests, verify PASS**

Run: `poetry run python manage.py test apps.company.tests.test_person_api -v1`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/company/views/person_views.py apps/company/tests/test_person_api.py
git commit -m "feat(crm): let archived people be viewed and their links restored"
```

---

### Task 4: Explicit "Archive person" service + endpoint

**Files:**
- Modify: `apps/company/services/person_service.py` (add `archive_person`)
- Modify: `apps/company/views/person_views.py` (add `PersonArchiveView`)
- Modify: `apps/company/urls_people_rest.py` (add route)
- Test: `apps/company/tests/test_person_api.py`

**Interfaces:**
- Produces: `archive_person(*, person: Person) -> None` (deactivate all active links + set `is_active=False`); `POST /api/people/{person_id}/archive/` → 200 with `PersonDetailSerializer` body.

- [ ] **Step 1: Write the failing test**

Add to `apps/company/tests/test_person_api.py`:

```python
    def test_archive_person_endpoint_deactivates_links_and_archives(self) -> None:
        person = self._person(company=self.company_a)
        CompanyPersonLink.objects.create(company=self.company_b, person=person)

        with patch("apps.crm.tasks.rematch_phone_calls_task.delay"):
            response = self.client.post(f"/api/people/{person.id}/archive/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_active"])
        person.refresh_from_db()
        self.assertFalse(person.is_active)
        self.assertFalse(
            CompanyPersonLink.objects.filter(person=person, is_active=True).exists()
        )
```

- [ ] **Step 2: Run the test, verify it FAILS**

Run: `poetry run python manage.py test apps.company.tests.test_person_api.PersonApiTests.test_archive_person_endpoint_deactivates_links_and_archives -v2`
Expected: FAIL — 404 (no such route).

- [ ] **Step 3: Add the service function**

In `apps/company/services/person_service.py`, add near `remove_company_link`:

```python
def archive_person(*, person: Person) -> None:
    """Retire a person everywhere: deactivate all active links, then archive."""
    with transaction.atomic():
        locked = Person.objects.select_for_update().get(pk=person.pk)
        CompanyPersonLink.objects.filter(person=locked, is_active=True).update(
            is_active=False, is_primary=False
        )
        if locked.is_active:
            locked.is_active = False
            locked.save(update_fields=["is_active", "updated_at"])
        _schedule_person_phone_rematch(locked)
```

- [ ] **Step 4: Add the view**

In `apps/company/views/person_views.py`: import `archive_person` in the existing `from apps.company.services.person_service import (...)` block, then add:

```python
class PersonArchiveView(APIView):
    """Explicitly retire a person (deactivate all links + archive)."""

    permission_classes = PERSON_PERMISSIONS

    @extend_schema(request=None, responses={200: PersonDetailSerializer})
    def post(self, request: Request, person_id: str) -> Response:
        person = get_object_or_404(Person, id=person_id)
        archive_person(person=person)
        person.refresh_from_db()
        return Response(PersonDetailSerializer(person).data)
```

- [ ] **Step 5: Add the route**

In `apps/company/urls_people_rest.py`, import `PersonArchiveView` in the existing view import block and add to `urlpatterns`:

```python
    path(
        "<uuid:person_id>/archive/",
        PersonArchiveView.as_view(),
        name="person_archive",
    ),
```

- [ ] **Step 6: Run tests, verify PASS**

Run: `poetry run python manage.py test apps.company.tests.test_person_api -v1`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/company/services/person_service.py apps/company/views/person_views.py apps/company/urls_people_rest.py apps/company/tests/test_person_api.py
git commit -m "feat(crm): add explicit archive-person endpoint"
```

---

### Task 5: Directory `include_archived` filter + expose `is_active` on summaries

**Files:**
- Modify: `apps/company/services/person_service.py` (`PersonDirectoryService.search`, `:65-103`)
- Modify: `apps/company/views/person_views.py` (`PersonListView`, `:49-70`)
- Modify: `apps/company/person_serializers.py` (`PersonSummarySerializer.Meta.fields`, `:40`)
- Test: `apps/company/tests/test_person_api.py`

**Interfaces:**
- Produces: `PersonDirectoryService.search(query: str, *, include_archived: bool = False)`; `GET /api/people/?include_archived=true` includes archived people; `PersonSummary` gains `is_active`.

- [ ] **Step 1: Write the failing tests**

Add to `apps/company/tests/test_person_api.py`:

```python
    def test_directory_excludes_archived_by_default(self) -> None:
        person = self._person(company=self.company_a)
        with patch("apps.crm.tasks.rematch_phone_calls_task.delay"):
            self.client.delete(
                f"/api/people/{person.id}/company-links/{self.company_a.id}/"
            )

        response = self.client.get("/api/people/")
        ids = [row["id"] for row in response.json()["results"]]
        self.assertNotIn(str(person.id), ids)

    def test_directory_includes_archived_when_requested(self) -> None:
        person = self._person(company=self.company_a)
        with patch("apps.crm.tasks.rematch_phone_calls_task.delay"):
            self.client.delete(
                f"/api/people/{person.id}/company-links/{self.company_a.id}/"
            )

        response = self.client.get("/api/people/", {"include_archived": "true"})
        rows = {row["id"]: row for row in response.json()["results"]}
        self.assertIn(str(person.id), rows)
        self.assertFalse(rows[str(person.id)]["is_active"])
```

- [ ] **Step 2: Run the tests, verify they FAIL**

Run: `poetry run python manage.py test apps.company.tests.test_person_api.PersonApiTests.test_directory_excludes_archived_by_default apps.company.tests.test_person_api.PersonApiTests.test_directory_includes_archived_when_requested -v2`
Expected: FAIL — `include_archived` test fails (archived person absent) and/or `is_active` missing from row (KeyError).

- [ ] **Step 3: Thread `include_archived` through the service**

In `apps/company/services/person_service.py`, change `search`'s signature and base queryset:

```python
    @staticmethod
    def search(query: str, *, include_archived: bool = False) -> QuerySet[Person]:
        base = Person.objects.all() if include_archived else Person.objects.filter(
            is_active=True
        )
        people = (
            base
            .annotate(
```
(leave the rest of the method body unchanged.)

- [ ] **Step 4: Pass the query param from the view**

In `apps/company/views/person_views.py`, `PersonListView.get_queryset`:

```python
    def get_queryset(self) -> QuerySet[Person]:
        include_archived = (
            self.request.query_params.get("include_archived", "").lower() == "true"
        )
        return PersonDirectoryService.search(
            self.request.query_params.get("q", ""),
            include_archived=include_archived,
        )
```
Also add an `include_archived` OpenApiParameter to the `@extend_schema` `parameters` list on `PersonListView.get` (mirror the existing `q` parameter, `type=OpenApiTypes.BOOL`).

- [ ] **Step 5: Expose `is_active` on the summary serializer**

In `apps/company/person_serializers.py`, `PersonSummarySerializer.Meta.fields`, add `"is_active"`:

```python
        fields = ["id", "name", "email", "is_active", "primary_phone", "companies"]
```

- [ ] **Step 6: Run tests, verify PASS**

Run: `poetry run python manage.py test apps.company.tests.test_person_api -v1`
Expected: PASS.

- [ ] **Step 7: Type-check the backend and commit**

Run: `bash scripts/check_mypy.sh`
Expected: no new errors.

```bash
git add apps/company/services/person_service.py apps/company/views/person_views.py apps/company/person_serializers.py apps/company/tests/test_person_api.py
git commit -m "feat(crm): directory include_archived filter and is_active on summaries"
```

---

### Task 6: Regenerate the frontend API client

**Files:**
- Modify: `frontend/src/api/generated/api.ts` (generated — do not hand-edit), plus the schema snapshot the generator reads.

**Interfaces:**
- Produces: generated client ops `api.people_archive_create` (or the name the generator derives for `POST /people/{person_id}/archive/`), `include_archived` query on `people_list`, and `is_active` on `schemas.PersonSummary`.

- [ ] **Step 1: Regenerate**

Run (from `frontend/`): `npm run update-schema && npm run gen:api`
Expected: `frontend/src/api/generated/api.ts` updates; `git status` shows it modified.

- [ ] **Step 2: Confirm the new surface exists**

Run: `grep -nE "person_archive|include_archived|PersonSummary" frontend/src/api/generated/api.ts | head`
Expected: matches for the archive endpoint operation, the `include_archived` query param, and `is_active` inside the `PersonSummary` schema. Note the exact generated operation name for the archive POST — Tasks 7-8 use it.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/generated/api.ts
git commit -m "chore(api): regenerate client for person archive endpoints"
```

---

### Task 7: Directory "Show archived" filter + Archived badge

**Files:**
- Modify: `frontend/src/pages/crm/people/(index).vue`
- Test: `frontend/src/pages/crm/people/__tests__/people-directory.test.ts`

**Interfaces:**
- Consumes: `api.people_list({ queries: { ..., include_archived } })`; `PersonSummary.is_active`.
- Produces: a `data-automation-id="PeopleDirectory-show-archived"` checkbox; archived rows show a badge with `data-automation-id="PeopleDirectory-archived-badge-${person.id}"`.

- [ ] **Step 1: Write the failing unit test**

Add a test to `frontend/src/pages/crm/people/__tests__/people-directory.test.ts` following the existing mount/mock pattern in that file: mock `api.people_list` to return one row with `is_active: false`; assert the row renders the archived badge, and assert that toggling the `PeopleDirectory-show-archived` control calls `api.people_list` with `queries.include_archived === true`. (Read the file's existing helpers/mocks first and mirror them.)

- [ ] **Step 2: Run it, verify FAIL**

Run (from `frontend/`): `npx vitest run src/pages/crm/people/__tests__/people-directory.test.ts`
Expected: FAIL — control/badge not present.

- [ ] **Step 3: Add the filter state + control**

In `(index).vue` script, add `const includeArchived = ref(false)`. In `loadPeople`, pass it:

```ts
    const response = await api.people_list({
      queries: {
        page: page.value,
        page_size: 50,
        q: query.value || undefined,
        include_archived: includeArchived.value || undefined,
      },
    })
```

In the search Card (next to the Search input, `:52-62`), add:

```html
            <label class="flex items-center gap-2 text-sm text-gray-600">
              <input
                type="checkbox"
                v-model="includeArchived"
                data-automation-id="PeopleDirectory-show-archived"
                @change="applySearch"
              />
              Show archived
            </label>
```

- [ ] **Step 4: Add the Archived badge in the row**

In the person cell (`:94-97`), after the name/email, add:

```html
                    <Badge
                      v-if="!person.is_active"
                      variant="secondary"
                      :data-automation-id="`PeopleDirectory-archived-badge-${person.id}`"
                    >
                      Archived
                    </Badge>
```
Import `Badge` from `@/components/ui/badge` in the script.

- [ ] **Step 5: Run tests + type-check, verify PASS**

Run (from `frontend/`): `npx vitest run src/pages/crm/people/__tests__/people-directory.test.ts && npm run type-check`
Expected: PASS, clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/crm/people/'(index).vue' frontend/src/pages/crm/people/__tests__/people-directory.test.ts
git commit -m "feat(crm): show-archived filter and Archived badge in people directory"
```

---

### Task 8: PersonDetail — Archived badge + "Archive person" button

**Files:**
- Modify: `frontend/src/pages/crm/people/[id].vue`
- Test: none dedicated (covered by the e2e in Task 9); add a small unit test only if the file already has one.

**Interfaces:**
- Consumes: `person.is_active` (already on `PersonDetail`); the generated archive op from Task 6 (confirm the exact name; assume `api.people_archive_create(undefined, { params: { person_id } })`).
- Produces: `data-automation-id="PersonDetail-archived-badge"` shown when `!person.is_active`; `data-automation-id="PersonDetail-archive"` button that archives and refreshes.

- [ ] **Step 1: Add the archived badge in the header**

In `[id].vue` template header area (near the page title, ~`:11`), add:

```html
        <Badge
          v-if="person && !person.is_active"
          variant="secondary"
          data-automation-id="PersonDetail-archived-badge"
        >
          Archived
        </Badge>
```
Ensure `Badge` is imported (the file already imports it for link status).

- [ ] **Step 2: Add the Archive-person button + handler**

Add a button in the header actions, shown only when the person is currently active:

```html
        <Button
          v-if="person && person.is_active"
          type="button"
          variant="outline"
          size="sm"
          data-automation-id="PersonDetail-archive"
          @click="archivePerson"
        >
          Archive person
        </Button>
```

In the script, add (using the confirmed generated op name from Task 6):

```ts
const archiving = ref(false)
async function archivePerson(): Promise<void> {
  archiving.value = true
  try {
    await api.people_archive_create(undefined, { params: { person_id: props.id } })
    toast.success('Person archived')
    await loadPerson()
  } catch (err) {
    toast.error(err instanceof Error ? err.message : 'Failed to archive person')
  } finally {
    archiving.value = false
  }
}
```

- [ ] **Step 3: Verify the restore-link path already un-archives via UI**

No code change expected: `restoreLink` calls `api.people_company_links_update`, which the backend now un-archives (Task 2). Confirm `loadPerson()` runs after `restoreLink` so the badge clears. If `restoreLink` does not already refresh `person`, add `await loadPerson()` at its end.

- [ ] **Step 4: Type-check, verify PASS**

Run (from `frontend/`): `npm run type-check`
Expected: clean (no `any`, generated op name resolves).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/crm/people/'[id].vue'
git commit -m "feat(crm): archived badge and Archive-person button on PersonDetail"
```

---

### Task 9: E2E — archive via directory show-archived → restore

**Files:**
- Create: `frontend/tests/crm/people-archive.spec.ts`

**Interfaces:**
- Consumes: automation ids from Tasks 7-8 and the existing `PersonDetail-*` / `PeopleDirectory-*` ids.

Note: the existing `frontend/tests/crm/people.spec.ts` "manages link lifecycle" test now exercises archive-on-remove → restore implicitly and must still pass — do not modify it.

- [ ] **Step 1: Write the e2e spec**

Create `frontend/tests/crm/people-archive.spec.ts`, mirroring the patterns in `frontend/tests/crm/people.spec.ts` (import `{ expect, test }` from `../fixtures/auth`, `autoId`/`waitForCompanyCreateResponse` from `../fixtures/helpers`, the `createCompany` / `createPersonForSelectedCompany` helpers — copy those two helpers into this file or import if exported). The test:

```ts
test('archived person is hidden by default, findable via filter, and restorable', async ({
  authenticatedPage: page,
}) => {
  const suffix = Math.floor(Math.random() * 1_000_000)
  const companyName = `[TEST] Archive Company ${suffix}`
  const personName = `[TEST] Archive Person ${suffix}`

  // Create a single-company person, then archive by removing their only link.
  await page.goto('/crm/people')
  await autoId(page, 'PeopleDirectory-create').click()
  await createCompany(page, companyName)
  await createPersonForSelectedCompany(page, personName, `0219${String(suffix).padStart(6, '0')}`)

  await autoId(page, 'PeopleDirectory-search').fill(personName)
  await autoId(page, 'PeopleDirectory-search').press('Enter')
  const row = page.locator('[data-automation-id^="PeopleDirectory-row-"]').filter({ hasText: personName })
  await row.getByRole('button', { name: 'Manage' }).click()

  const link = page.locator('[data-automation-id^="PersonDetail-company-link-"]').filter({ hasText: companyName })
  const linkId = (await link.getAttribute('data-automation-id'))!.replace('PersonDetail-company-link-', '')
  page.once('dialog', (d) => d.accept())
  await autoId(page, `PersonDetail-remove-link-${linkId}`).click()
  await expect(autoId(page, 'PersonDetail-archived-badge')).toBeVisible()

  // Hidden from default directory search.
  await page.goto('/crm/people')
  await autoId(page, 'PeopleDirectory-search').fill(personName)
  await autoId(page, 'PeopleDirectory-search').press('Enter')
  await expect(
    page.locator('[data-automation-id^="PeopleDirectory-row-"]').filter({ hasText: personName }),
  ).toHaveCount(0)

  // Visible with the show-archived filter.
  await autoId(page, 'PeopleDirectory-show-archived').check()
  await expect(
    page.locator('[data-automation-id^="PeopleDirectory-row-"]').filter({ hasText: personName }),
  ).toHaveCount(1)

  // Restore brings them back active.
  await page.locator('[data-automation-id^="PeopleDirectory-row-"]').filter({ hasText: personName })
    .getByRole('button', { name: 'Manage' }).click()
  await autoId(page, `PersonDetail-restore-link-${linkId}`).click()
  await expect(link).toContainText('Active')
  await expect(autoId(page, 'PersonDetail-archived-badge')).toHaveCount(0)
})
```

- [ ] **Step 2: Confirm it compiles / is discovered (no full run)**

Run (from `frontend/`): `npx playwright test tests/crm/people-archive.spec.ts --list`
Expected: the test is listed with no compile error.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/crm/people-archive.spec.ts
git commit -m "test(crm): e2e for archive → show-archived → restore"
```

---

## Self-review

- **Spec coverage:** rule/state-machine → Tasks 1,2,4; relaxed gates → Task 3; explicit archive → Task 4; directory filter + `is_active` exposure → Task 5; client regen → Task 6; directory UI → Task 7; PersonDetail UI → Task 8; testing incl. existing `people.spec.ts` → Tasks 1-9 + Task 9. Out-of-scope (contact-method/phone-ownership for archived) intentionally untouched.
- **Placeholder scan:** none — every code step shows the code; the only deferred detail is the generated archive op name, which Task 6 Step 2 pins down before Tasks 7-8 use it.
- **Type/name consistency:** `archive_person`, `PersonArchiveView`, `include_archived`, `PersonDirectoryService.search(query, *, include_archived=False)`, `is_active` used consistently across tasks.
