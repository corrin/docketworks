# Person archive (retire departed people) — design

## Context

In the first-class people model a `Person` is a shared record linked to companies via
`CompanyPersonLink`. `Person.is_active` exists as a soft-delete flag but **no HTTP path toggles it** —
only offline merge/cleanup services do. There is no way for a user to retire a person who has left or
become irrelevant.

The need surfaced while restoring the job-settings person selector's delete button. A first attempt made
`remove_company_link` archive the person on last-link removal, but it only flipped `is_active` while every
person/link endpoint still gated on `get_object_or_404(Person, is_active=True)`. That made archived people
unviewable and their links un-restorable, breaking the existing CRM restore-link lifecycle
(`frontend/tests/crm/people.spec.ts`). That cascade was reverted (`00b2bce8`).

This design does it properly: archiving is driven mainly by links, archived people stay reachable, and
restoring a link brings them back.

## Purpose

Retire departed/irrelevant people from everyday views (directory search, person selectors) without
hard-deleting — history preserved, reversible.

## The rule (Person.is_active state machine)

- **Removing a person's last *active* company link → archive** (`is_active=False`). Removing one of
  several active links leaves the person active.
- **Restoring or adding any company link to an archived person → un-archive** (`is_active=True`). This is
  the implicit un-archive; there is no separate un-archive button.
- **Explicit "Archive person" (PersonDetail) → deactivate all active links + `is_active=False`** ("retire
  everywhere now"). Secondary path.
- **Active-but-company-less remains valid** when it arises from *creation* without a link (unchanged;
  `test_directory_includes_person_without_company`). Only *removal* archives.

Rationale for driving off links rather than a computed "zero active links = archived": a freshly created
person with no link yet is intentionally active, and an explicit archive of a multi-company person cannot be
expressed as "zero links". `is_active` is the single source of truth.

## Backend

All in `apps/company/` (models unchanged — `Person.is_active` and `CompanyPersonLink.is_active` already
exist).

1. **`services/person_service.py`**
   - `remove_company_link`: after deactivating the link, if the person has no remaining active company links
     (reuse the already-computed `projected_company_ids`), set `person.is_active = False`
     (`update_fields=["is_active", "updated_at"]`).
   - Link add/reactivate (`add_company_link` and the reactivate branch used by the company-links PUT): if the
     target person is archived, set `person.is_active = True` in the same transaction.
   - New `archive_person(*, person)`: deactivate all active `CompanyPersonLink`s for the person and set
     `is_active = False`. Schedule phone rematch consistent with `remove_company_link`.
2. **`views/person_views.py`** — relax the `is_active=True` gate on the endpoints restore needs, so archived
   people are viewable/operable:
   - `PersonDetailView` GET (retrieve): look up by id without the `is_active=True` filter.
   - `PersonCompanyLinksView` / `PersonCompanyLinkDetailView`: person lookup without `is_active=True` so
     restore-link works on an archived person.
   - `PersonContactMethodsView` GET/POST: **also ungated.** (This section originally said "keep contact-methods
     gated — out of scope". That was a mistake, caught by the final review: PersonDetail loads person +
     contact-methods + company-links in one `Promise.all`, so a 404 there rejects the whole load and the
     archived person renders "Failed to load person" with no restore-link button — the exact unreachable state
     this design exists to prevent.)
   - New explicit archive route (e.g. `POST /api/people/{person_id}/archive/`) → `archive_person`.
3. **`views/person_views.py` `PersonListView`** (directory search): add an `include_archived` query param
   (default `false` → keep the existing `is_active=True` filter; `true` → include archived).
4. **Serializers (`person_serializers.py`)**: expose `is_active` on `PersonSummary` (directory rows) and
   `PersonDetail` so the frontend can badge/branch. `CompanyPerson` unchanged (company lists only ever show
   active links).

## Frontend

Regenerate the API client after the schema changes (`npm run update-schema && npm run gen:api`).

1. **`/crm/people` directory**: a "Show archived" filter/toggle that sets `include_archived=true`; archived
   rows render an **Archived** badge. (Files: the people directory page + its list/row components.)
2. **PersonDetail page**: render an archived person (Archived badge); the existing **restore-link** button
   already round-trips through the reactivate path, which now un-archives — verify it displays correctly for
   an archived person. Add an explicit **Archive person** button calling the new archive endpoint.
3. **Job-settings person selector**: unchanged. Its delete already calls `people_company_links_destroy`; for a
   single-company person that now archives via the shared cascade, for multi-company it just unlinks. This is
   the original job-settings request, satisfied by the shared rule.

## Search / visibility (unchanged where it matters)

- Directory default: archived hidden (existing `is_active=True` filter), shown only via the filter.
- Company people list and person selector already filter to active links → archived people never appear. No
  change.

## Testing

- Existing `frontend/tests/crm/people.spec.ts` restore-lifecycle passes again (remove sole link →
  archived + viewable → restore → active).
- Backend (`apps/company/tests/test_person_api.py`): last-link removal archives; restore-link un-archives;
  removing one of several links keeps the person active; explicit archive deactivates all links + archives;
  `PersonDetailView` returns an archived person; directory `include_archived` includes/excludes correctly.
- Frontend unit: directory badge + filter; PersonDetail archived state + archive button.
- E2E: show-archived filter → open archived person → restore → active.

## Out of scope for v1 (accepted)

- **Phone-number *reuse* by someone else.** An archived person still "owns" their phone number, so
  `can_create_person` stays `False` for that number — you cannot create a *different* person on it. Left
  as-is; the one-number-one-company rule is unchanged.
- No standalone "un-archive to a company-less state" button — coming back always happens via restoring/adding
  a company link.

## Corrections made during implementation

The original draft of this spec put two things out of scope that turned out to be load-bearing. The final
review caught both; the user authorised overriding the spec, and both are now fixed:

1. **Contact-methods views must be ungated** (see Backend §2) — otherwise archived people are unreachable and
   unrestorable.
2. **`classify_phone_ownership` must not skip archived people.** It previously did, which — because
   `ContactMethod.conflicting_company` still saw their number — produced `status='company'` with an empty
   owner list and no way forward ("It belongs to  and cannot be assigned to a person."). That was a
   *regression* of a pre-existing recovery path. Skipping only `person is None` restores the intended flow:
   the archived owner is listed with a working "Restore company link" button, which reactivates the link and
   un-archives them. This does not loosen the reuse rule above — `can_create_person` was already `False`.
