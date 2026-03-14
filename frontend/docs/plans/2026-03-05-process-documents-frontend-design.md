# Process Documents Frontend Design

## Overview

Two user-facing experiences built on one backend model:

1. **Procedures Library** — browsable list of prose documents (SOPs, SWPs, references) that link out to Google Docs
2. **Form Entries Pages** — each form template (Incident Register, Equipment Maintenance, etc.) gets its own dedicated entries list, accessible directly from the nav

Plus admin capabilities: creating/editing templates, managing all documents from the library page.

---

## Navigation

The "Process" dropdown in `AppNavbar.vue` becomes:

```
┌─ Process ──────────────────────────┐
│ Procedures              (library)  │
│ ─────────────────────────────────  │
│ Incident Register       (form)     │
│ Equipment Maintenance   (form)     │
│ Training Sign-offs      (form)     │
│ ... (dynamic from form templates)  │
│ ─────────────────────────────────  │
│ Job Safety Analyses     (existing) │
│ Staff Training          (external) │
└────────────────────────────────────┘
```

**Behaviour:**

- Form templates fetched on app load: `GET /rest/process-documents/?type=form&is_template=true&status=active`
- Cached in the process documents store
- Each form template rendered as a nav item linking to `/process-documents/forms/:id`
- "Procedures" links to `/process-documents` (library page)
- JSA and Staff Training unchanged
- **Empty state**: If no form templates exist, show greyed-out "No forms configured" text that links to the library page (nudge for admins to create templates)

---

## Page 1: Procedures Library (`/process-documents`)

Browsable library of all process documents. Default view filtered to procedures. Admins can view/manage all types including form templates.

### Layout

```
┌─────────────────────────────────────────────────────┐
│ Process Documents                  [Search...] [+New]│
├─────────────────────────────────────────────────────┤
│ Type: [All] [Procedures] [Forms] [Registers] [Ref]  │
│ Tags: [safety] [machinery] [training] ...            │
│ Status: [Active ▾]    [ ] Templates only             │
├─────────────────────────────────────────────────────┤
│ Doc# │ Title              │ Type │ Tags │ Status │ ↻ │
│ 355  │ Drill Press SOP    │ proc │ ●●   │ active │   │
│ 412  │ Incident Register  │ form │ ●    │ active │   │
│ ...  │                    │      │      │        │   │
└─────────────────────────────────────────────────────┘
```

### Filters

- **Type pills**: Toggle buttons, one active at a time. Default: "Procedures". "All" shows everything.
- **Tag pills**: Multi-select toggles, AND logic. Generated from tags in the current response.
- **Status dropdown**: Active (default) | Draft | Completed | Archived | All
- **Templates toggle**: Checkbox "Templates only"
- **Search**: Debounced 300ms, filters on title + document_number

### Table

- TanStack Vue Table
- **Columns**: Doc# (numeric sort), Title, Type (badge), Tags (chips, max 3 + "+N"), Status (badge), Template icon, Updated (relative date), Actions
- **Actions**: Open in Google Docs (prose only, external link), Fill (templates), Delete (soft delete, confirmation dialog)
- **Row click**: Procedures → `/process-documents/:id` (detail). Forms → `/process-documents/forms/:id` (entries list).
- **Empty state**: "No process documents found. Try adjusting your filters or create a new document."

### New Document Modal

```
┌─ New Process Document ──────────────────┐
│ Title*:         [________________________]│
│ Document #:     [________________________]│
│ Type*:          [Procedure ▾            ]│
│ Tags:           [safety, sop            ]│
│ [ ] This is a template                   │
│                                          │
│ ┌─ Form Schema (JSON) ─────────────────┐│
│ │ (visible when Type=Form + Template)  ││
│ │ {"fields": [...]}                    ││
│ └──────────────────────────────────────┘│
│                                          │
│                    [Cancel] [Create]     │
└──────────────────────────────────────────┘
```

- Tags: comma-separated text input
- Form schema JSON textarea: only shown when type is "form" AND template checkbox is checked
- Documents created with status `active` (skip draft for now)

---

## Page 2: Procedure Detail (`/process-documents/:id`)

For prose documents (procedures, references). Content lives in Google Docs.

### Layout

```
┌─────────────────────────────────────────────────────┐
│ ← Back to Library                                    │
│                                                      │
│ Drill Press Safe Operating Procedure        [Edit ▾] │
│ #355  [procedure]  [active]                          │
│                                                      │
│ Tags: [safety] [sop] [machinery]                     │
│ Company: Morris Sheetmetal                           │
│ Created: 3 Mar 2026 · Updated: 3 Mar 2026           │
│ Job: #1234 - Some Job Name (if associated)           │
│ Template: ← View original template (if filled)       │
├─────────────────────────────────────────────────────┤
│                                                      │
│  📄 This document lives in Google Docs               │
│                                                      │
│  [Open in Google Docs ↗]                             │
│                                                      │
├─────────────────────────────────────────────────────┤
│ (if template — show child records table)             │
│ Records created from this template:                  │
│ Created │ Status │ Job │ → link                      │
└─────────────────────────────────────────────────────┘
```

**Edit dropdown**: Edit Metadata (opens modal pre-populated), Delete (soft delete, confirmation dialog).

**Fill workflow** (for prose templates):

1. User clicks "Fill in this form" (prominent button, shown for templates)
2. Small modal with optional job picker (search by job number/name, like `JobSelect.vue` pattern)
3. POST `/fill/` → new record created
4. Open new Google Doc in new tab
5. Navigate current tab to new record's detail page
6. Toast: "Record created from [template name]"

---

## Page 3: Form Entries (`/process-documents/forms/:id`)

The primary page for form-type documents. Each form template gets its own dedicated entries list. This is what nav items like "Incident Register" link to.

### Layout

```
┌─────────────────────────────────────────────────────┐
│ Incident Register                      [+ New Entry] │
│ Report and track workplace incidents                  │
├─────────────────────────────────────────────────────┤
│ [Search...]  Date range: [From] [To]                 │
├─────────────────────────────────────────────────────┤
│ Date    │ Reported By  │ Description    │ Severity   │
│ 5 Mar   │ John Smith   │ Near miss at...│ Minor      │
│ 2 Mar   │ Jane Doe     │ Hand injury... │ Major      │
│ ...     │              │                │            │
└─────────────────────────────────────────────────────┘
```

### Behaviour

**First visit (template, no filled record yet):**

- Auto-create a filled record from the template (POST `/fill/` with no job_id)
- Then show the entries list (empty initially)
- Or: show a "Get started" state with a button to activate the register

**Active filled record:**

- Entries table with columns derived from `form_schema.fields`
- Newest entries first
- Search filters across all text fields in entry data
- Date range filter on `entry_date`
- Each entry row has edit action (for corrections)

### New Entry

"+ New Entry" opens a modal or inline form:

```
┌─ New Entry ────────────────────────────────────────┐
│ Entry Date: [2026-03-05]                            │
│                                                     │
│ Equipment Name*: [_________________________________]│
│ Condition:       [OK ▾                             ]│
│ Inspected:       [✓]                                │
│ Date Checked:    [____]                             │
│ Fault Desc:      [_________________________________]│
│ Quantity:        [___]                              │
│                                                     │
│                              [Cancel] [Add Entry]   │
└─────────────────────────────────────────────────────┘
```

- Form dynamically rendered from `form_schema.fields`
- Field type mapping: text→input, textarea→textarea, date→date picker, boolean→checkbox, number→number input, select→dropdown from `options`
- Required fields validated before submission
- Entry date defaults to today
- POST to `/rest/process-documents/<record-id>/entries/`
- On success: entry appears at top of table, form resets

### Entry Editing

- Click edit icon on entry row → opens same form pre-populated with entry data
- PUT to `/rest/process-documents/<record-id>/entries/<entry-id>/`
- Requires backend PUT endpoint (not yet in spec — needs requesting)

---

## Fill Workflow (consolidated)

Used for both prose templates (from library) and form templates (less common — most forms auto-activate from nav).

1. User clicks "Fill in this form" on a template
2. Modal: "Create a record from this template"
   - Optional job search (type-ahead, like `JobSelect.vue`)
   - [Cancel] [Create]
3. POST `/fill/` with `{ job_id: selected || null }`
4. Response: new record
5. **Prose**: open Google Doc in new tab + navigate to new record detail
6. **Form**: navigate to `/process-documents/forms/:newId` (entries list)
7. Toast: "Record created from [template name]"

---

## Component Architecture

```
src/
  views/
    ProcessDocumentsView.vue          # Library page (procedures + admin)
    ProcessDocumentDetailView.vue     # Prose document detail
    FormEntriesView.vue               # Form entries list page
  components/
    process-documents/
      ProcessDocumentTable.vue        # TanStack table for library
      ProcessDocumentFilters.vue      # Type pills, tag pills, status, search
      ProcessDocumentModal.vue        # Create/edit metadata modal
      FillTemplateModal.vue           # Fill modal with job picker
      FormSchemaPreview.vue           # Read-only schema field list (library)
      DynamicFormEntry.vue            # Renders form inputs from schema
      EntriesTable.vue                # Entries table (dynamic columns from schema)
      ChildRecordsTable.vue           # Records created from template
  stores/
    processDocuments.ts               # Pinia composition store
  services/
    processDocuments.service.ts       # API calls
```

---

## Store

```typescript
// stores/processDocuments.ts — Pinia composition store

state: {
  // Library
  documents: ProcessDocumentList[]
  currentDocument: ProcessDocument | null
  isLoading: boolean
  error: string | null
  filters: {
    type: ProcessDocumentType | null
    tags: string[]
    status: ProcessDocumentStatus | 'all'
    isTemplate: boolean | null
    search: string
  }

  // Form templates (for nav)
  formTemplates: ProcessDocumentList[]

  // Entries (for form entries page)
  entries: ProcessDocumentEntry[]
  isLoadingEntries: boolean
}

actions: {
  // Library
  loadDocuments()
  loadDocument(id)
  createDocument(data)
  updateDocument(id, data)
  deleteDocument(id)               // soft delete
  setFilters(filters)

  // Templates & nav
  loadFormTemplates()              // for nav population

  // Fill
  fillTemplate(id, jobId?)

  // Status
  completeDocument(id)

  // Entries
  loadEntries(documentId)
  addEntry(documentId, data)
  updateEntry(documentId, entryId, data)
}
```

---

## Backend Requests

Before full implementation, we need from the backend:

1. **`?parent_template_id=<id>` filter** on list endpoint — for "records from this template" table
2. **Entry PUT endpoint** (`PUT /rest/process-documents/<id>/entries/<entry-id>/`) — for editing entries
3. **Entry DELETE endpoint** (optional, lower priority) — for removing erroneous entries
4. **OpenAPI schema updated** with all new endpoints so we can generate types

---

## Routes

```typescript
{ path: '/process-documents', name: 'process-documents', component: ProcessDocumentsView }
{ path: '/process-documents/:id', name: 'process-document-detail', component: ProcessDocumentDetailView }
{ path: '/process-documents/forms/:id', name: 'form-entries', component: FormEntriesView }
```

Existing `/safety/jsa` and `/safety/swp` routes remain functional (not in nav, but bookmarks don't break).

---

## Key Design Decisions

1. **Nav-first forms**: Each form template is a direct nav item. Users go straight to their form, no browsing.
2. **Library for procedures**: The library page is primarily for browsing prose documents and admin management.
3. **Active by default**: New documents skip draft, go straight to active.
4. **Dynamic form rendering**: Form inputs generated from `form_schema.fields` at runtime.
5. **Soft delete everywhere**: Confirmation dialog, backend soft-deletes.
6. **Reuse existing patterns**: Job picker like `JobSelect.vue`, TanStack tables, Reka-UI dialogs, shadcn-vue components.
7. **Existing safety UI untouched**: JSA generation, SWP generation, Safety Wizard all continue working.
