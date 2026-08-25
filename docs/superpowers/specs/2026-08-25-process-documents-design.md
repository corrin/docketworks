# Process documents — design

Owner-approved design for the process-documents domain (forms, form entries,
procedures, JSA, safety AI). Supersedes v1's shape wherever they differ; v1 is
a reference, not an authority (see CLAUDE.md porting rules). Built as three
slices, each shipping its own E2E spec. Slice 1 closes the MUST-tier
`form-entries-page-scroll` spec.

## Concepts

- **Form** — a template. Every form is a template: it carries a JSON field
  schema, and filling it in creates a FormEntry. There is no `is_template`
  flag. `document_type` distinguishes `form` from `register`, which is purely
  a categorisation — behaviour is identical.
- **FormEntry** — a filled-in form: a formal record ("Ben signed that he read
  this document on this date"). Editable by any authenticated staff member;
  every change writes an audit event that the UI shows. Soft-deletable
  (`is_active`), never hard-deleted. An entry may link to a **parent entry**:
  a meeting's minutes are one entry, and the attendance sign-offs and the
  action items extracted from that meeting are entries in their own right,
  each linked back to the minutes entry. Parent and child may belong to
  different forms (an Action entry linking to a Meeting Minutes entry).
- **Procedure** — a Google-Docs-backed document (JSA, SWP, reference, general
  procedure), distinguished by `document_type` + `category`. Row click opens
  the Google Doc. JSAs additionally hang off a job's Safety tab.
- **Category** — a stored, exclusive field on Form and Procedure. Not tags
  (tags remain for search), not a model, not a URL-segment filter.

## Permission model

Regular staff exist in this domain to **sign**: "I read this form", "I
completed this form". Therefore:

- Read anything, create entries, edit entries, soft-delete entries:
  **any authenticated staff**. The audit trail is the control.
- Create/update/archive forms and procedures, generate JSA: **office staff**.

Finer-grained rules about what regular staff can and cannot do are a planned
later feature; nothing in this design should pre-build for them beyond keeping
permission checks in one obvious place per endpoint.

## Data model

All in `apps/process` (models already ported field-for-field; changes below
are additive migrations plus one removal).

1. **`category`** — CharField with choices, required.
   - Form: `safety`, `training`, `incident`, `meeting`, `register`.
   - Procedure: `safety`, `jsa`, `training`, `reference`.
   - Classified data migration backfills from `tags`, most-specific-first:
     forms `incident > register > meeting > training > safety`; procedures
     `jsa > reference > training > safety`. (So docs 202/205, tagged
     safety+incident, land in `incident`; every JSA lands in `jsa`.)
   - The import command's `DOC_MAPPING` gains a category per document and
     stops relying on tag inference.
2. **`ProcessEvent`** — the domain's one audit model, in `JobEvent`'s shape:
   `id`, `timestamp`, `staff` (PROTECT), `event_type`, `delta_before`,
   `delta_after` (JSONFields), `detail`, and nullable FKs `form`,
   `form_entry`, `procedure` (CASCADE). A derived human description property.
   No checksum, no undo, no envelope machinery — those exist for the job
   screen's optimistic concurrency, which this domain does not need.
   Event types: `entry_created`, `entry_updated`, `entry_archived`,
   `form_created`, `form_updated`, `schema_updated`, `form_archived`,
   `procedure_created`, `procedure_updated`, `procedure_archived`,
   `jsa_generated` (job-side JobEvent also written, hook already exists).
   A schema edit is an event because it re-interprets existing entries.
   Hoisting a shared event mechanism (JobEvent + ProcessEvent) into
   `apps/core` is recorded as post-cutover work, not done now.
3. **Remove `HistoricalRecords`** from Form, FormEntry, Procedure. v2 moved
   off django-simple-history in favour of custom delta logs; leaving it
   recording beside ProcessEvent would be a second live audit implementation.
   The migration drops the three `process_historical*` tables, so v1's
   historical rows for this domain do not survive the restore.
   **OWNER VETO POINT: confirmed acceptable? The domain barely functioned in
   v1, so the lost history is thin.**
4. **`FormEntry.updated_at`** — added; an editable record without one is an
   audit gap.
5. **`FormEntry.parent_entry`** — nullable self-FK (`related_name=
   "child_entries"`, SET_NULL: a linked record keeps standing on its own if
   its parent is ever hard-removed outside the app). This is the
   meeting-minutes → attendance/actions linkage; it is cross-form by design.
   No depth limit is enforced — a chain is legal but the UI only surfaces one
   level.
6. Categories and `document_type` stay code-level enums. More will come
   (owner: meetings and their derivatives are one known family); extension
   is a one-line choice addition plus a ledger note, and nothing —
   validation, navbar, filters — hardcodes today's list anywhere except the
   enum itself.
7. Wire contract: `document_number` and `site_location` are `NullableText`
   (ADR 0040) — blank string is a 422 before the database, which removes
   v1's certain 500 (blank `site_location` vs the CHECK constraint) by
   construction.

## API

New shapes; v1's URLs are not preserved (no external party holds them). All
under `/api/process/`. Category is a query filter, not a path segment.

Forms:
- list (filters: `category`, `q`, `status`; unpaginated — bounded by
  authoring, ~30 documents)
- create, retrieve, update — update includes `form_schema`
- archive = status update; **no destroy endpoint**

Form schema is a typed, validated contract (`fields: [{key, label, type,
required?, options?}]`, types `text|textarea|date|boolean|number|select`),
enforced server-side with 422 on violation — never an opaque JSONField.
Validation rejects duplicate keys and `options` on non-select fields.

Entries:
- list (paginated — entries grow without bound; page size 50; filters:
  `parent` for one entry's children, `staff`, `job`)
- create — `entry_date`, `data`, optional `job`, optional `staff`, optional
  `parent_entry`; `entered_by` stamped from the request user
- update, soft-delete (sets `is_active=False`)
- **history** — the ProcessEvent read for one entry, newest first

Entry `data` is validated against the form's schema at write time: unknown
keys are a 422, required fields must be present, values must match the field
type. (v1 accepted anything.)

Categories:
- one GET returning both choice lists with machine keys and display labels;
  drives the navbar menus.

Procedures (slice 2): list/create/retrieve/update + archive-by-status in the
same shape; content read/write (Google Docs); JSA list + generate under the
job. Procedure create makes the blank Google Doc only after validation
passes — v1 orphaned a doc, then 500ed.

Dropped from v1's surface, recorded by hand in
`scripts/v1-frontend-operations.yml` (`dropped:` with reasons):
- `process_forms_destroy`, `process_procedures_destroy` — archive-only ruling
- all four `*_partial_update` — zero callers in v1's frontend
- `process_forms_entries_destroy` — replaced by the soft-delete update path
- `process_forms_fill_create` — fill is entry-create; one operation
- `process_procedures_safety_generate_sop_create` — dead vertical, zero callers

## Google Drive client (slice 2)

New integrations-tier app **`apps/google`**: the single home for Drive and
Docs access (Sheets joins later with the job-quote slice). Import-linter
places it in the integrations layer beside xero/ai.

- Credentials per ADR 0053: `IntegrationSettings.google_service_account_json`
  (write-only on the wire, `has_google_service_account_json` boolean out)
  plus a single `google_drive_enabled` switch. No env var, no fallback; fail
  at point of use.
- `import_dropbox_hs_documents` and `scripts/gdocs/gauth.py` migrate onto the
  client (the command drops its `--credentials` flag).
- Follow-on (recorded, not this slice): promote
  `scripts/ops/outbound_links_probe.py` to `manage.py check_links` per
  ADR 0049, now that the app can read Google credentials.
- Archive never touches the Google Doc. Nothing in this domain deletes docs.

## Frontend

`frontend/src/features/process/` + thin routes:

- `/process-documents/forms/:category` — list page (shared component with
  procedures; Google-doc column hidden for forms)
- `/process-documents/forms/:category/:id` — entries page
- `/process-documents/procedures/:category` — slice 2; row click opens
  `google_doc_url` (wired properly — v1's button emitted into the void)

Navbar: Forms menu (slice 1) and Procedures menu (slice 2) under a Process
Documents group, items driven by the categories endpoint. Nothing renders
before its slice lands (a deferred capability is hidden, not inert).

Components:
- **One** schema-driven entry form component, used by both the entries-page
  add-entry card and the Fill dialog on the forms list. Optional job picker
  and staff picker; staff defaults to the signed-in user ("sign for myself"
  is the common case).
- Entries table built from the schema, with a history panel per entry
  rendering ProcessEvent rows (who, when, field-level before/after).
- Linked entries: an entry's detail surface lists its child entries
  ("Actions (3)", "Attendance (7)" grouped by the child's form) and offers
  "add linked entry" — pick a form, and the shared entry component opens
  with `parent_entry` preset. One level deep in the UI.
- Schema editor: JSON textarea that actually loads and saves the schema,
  server-validated, with a live preview pane rendering the real entry form
  as you type.
- Archive replaces delete everywhere in the UI; archived documents are
  hidden by default and reachable via the status filter.

TanStack Query only; generated client (camelCase, option factories); errors
route to toasts (the console.error E2E guard).

## Slices and specs

**Slice 1 — forms (MUST).** Migrations (category backfill, ProcessEvent,
simple-history removal, updated_at, parent_entry), forms/entries/categories
API, both pages, Fill dialog, history panel, linked entries, navbar Forms
menu, e2e_cleanup extension. Specs: the ported `form-entries-page-scroll`
(adapted to v2 URLs/wire — its green is the MUST milestone) plus an authored
lifecycle spec: create form → fill as regular staff → add a linked entry →
edit → history shows the delta → archive.

**Slice 2 — procedures library + JSA.** `apps/google`, ADR 0053 column +
switch, procedures API and pages, job Safety tab with Generate JSA (AI call
through `apps/ai`, ADR 0041), `jsa_generated` events both sides. Own spec;
Drive-touching paths get an `integration`-marked test (ADR 0050) — a faked
Docs API cannot prove the real one accepts our shapes.

**Slice 3 — safety-AI wizard + SWP.** The four safety-AI operations through
the gateway, wizard port (side-by-side editor, hazards/controls/PPE), SWP
generation reachable for the first time — including settling `equipment_type`,
which v1's serializer silently dropped. Own spec.

Not ported (dead or superseded surface): `is_template` and
`FillTemplateModal` as a separate path, SOP generation, `JsaListView` /
`SwpListView` (unrouted in v1), `ChildRecordsTable`, the parallel
`jsaSwpDocuments` store (v2 has no hand-written store layer at all).

## E2E hygiene

`e2e_cleanup` gains Form, FormEntry, Procedure sweeps by the `[TEST]` title
prefix — v1's spec leaked one permanent form per run into the incident list.
ProcessEvent rows go with their entries via CASCADE.

## Error handling and testing

- Guard-clause shape throughout; unknown category, invalid schema, invalid
  entry data are 422s with transparent messages (ADR 0038).
- Google/AI failures during procedure create surface as errors; no partial
  rows — the doc is created after validation and the row is written in the
  same service call, with the failure path persisting an AppError.
- Unit tests per service (schema validation, entry validation, event writes,
  backfill migration); the migration ships classified for
  `test_data_migration_script`.
- Behaviour-ledger entries: archive-only deletion, exclusive categories,
  entry-data validation, paginated entries.

## Open items (owner)

1. Historical-tables drop (veto point above).
2. The two registers (docs 380 and 403) have no schemas and have never been
   usable; once slice 1 ships, author their schemas in the app — no code
   task.
3. Later feature (out of scope here): granular regular-staff permissions.
