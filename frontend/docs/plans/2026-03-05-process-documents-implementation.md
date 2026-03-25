# Process Documents Frontend — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the Process Documents frontend — a procedures library, form entries pages, and dynamic nav — replacing the current placeholder safety menu items.

**Architecture:** New Pinia store + service layer for API calls. Three new views: library list, prose detail, form entries. AppNavbar updated with dynamic form template nav items. All built on existing shadcn-vue + TanStack table + Reka-UI patterns.

**Tech Stack:** Vue 3 + TypeScript, Pinia, TanStack Vue Table, Reka-UI/shadcn-vue, Zodios API client, Vitest

**Design doc:** `docs/plans/2026-03-05-process-documents-frontend-design.md`

---

## Prerequisites

Before starting, the backend must:

1. Have all process document endpoints in the OpenAPI schema
2. Include `?parent_template_id=<id>` filter on list endpoint
3. Include entry PUT endpoint for editing

Then run: `npm run update-schema && npm run gen:api`

If the schema isn't ready yet, start at Task 2 with manual types and stub the service. Wire up the real API once generated.

---

### Task 1: Generate API client from updated schema

**Files:**

- Modify: `src/api/generated/api.ts` (auto-generated)

**Step 1:** Pull latest backend OpenAPI schema

```bash
npm run update-schema
```

**Step 2:** Regenerate API client

```bash
npm run gen:api
```

**Step 3:** Verify process document endpoints exist in generated output

```bash
grep -c "process.document" src/api/generated/api.ts
```

Expected: Multiple matches for the new endpoints.

**Step 4:** Run type-check to confirm no breakage

```bash
npm run type-check
```

**Step 5:** Commit

```bash
git add src/api/generated/api.ts
git commit -m "chore: regenerate API client with process document endpoints"
```

**If schema not ready:** Skip to Task 2 and use manual types. Come back to this task later.

---

### Task 2: Create types and service layer

**Files:**

- Create: `src/types/processDocument.types.ts`
- Create: `src/services/processDocuments.service.ts`

**Step 1:** Create the types file.

Reference the spec types in `docs/plans/2026-03-03-process-documents-frontend-spec.md` lines 250-313. If the generated API has schemas for these, use `z.infer<typeof schemas.X>` instead. If not yet generated, define manually for now:

```typescript
// src/types/processDocument.types.ts

export type ProcessDocumentType = 'procedure' | 'form' | 'register' | 'reference'
export type ProcessDocumentStatus = 'draft' | 'active' | 'completed' | 'archived'
export type FormFieldType = 'text' | 'textarea' | 'date' | 'boolean' | 'number' | 'select'

export interface FormField {
  key: string
  label: string
  type: FormFieldType
  required?: boolean
  options?: string[]
}

export interface FormSchema {
  fields: FormField[]
}

export interface ProcessDocument {
  id: string
  document_type: ProcessDocumentType
  document_number: string
  title: string
  tags: string[]
  is_template: boolean
  status: ProcessDocumentStatus
  form_schema: FormSchema | Record<string, never>
  google_doc_id: string
  google_doc_url: string
  parent_template_id: string | null
  job_id: string | null
  job_number: string | null
  company_name: string
  site_location: string
  created_at: string
  updated_at: string
}

export interface ProcessDocumentList {
  id: string
  document_type: ProcessDocumentType
  document_number: string
  title: string
  tags: string[]
  is_template: boolean
  status: ProcessDocumentStatus
  form_schema: FormSchema | Record<string, never>
  google_doc_url: string
  job_number: string | null
  site_location: string
  created_at: string
  updated_at: string
}

export interface ProcessDocumentEntry {
  id: string
  document: string
  entry_date: string
  entered_by: string | null
  entered_by_name: string | null
  data: Record<string, unknown>
  created_at: string
}

export interface ProcessDocumentFilters {
  type: ProcessDocumentType | null
  tags: string[]
  status: ProcessDocumentStatus | 'all'
  isTemplate: boolean | null
  search: string
}

export interface CreateProcessDocumentPayload {
  title: string
  document_number?: string
  document_type: ProcessDocumentType
  tags: string[]
  is_template: boolean
  form_schema?: FormSchema
}

export interface CreateEntryPayload {
  entry_date: string
  data: Record<string, unknown>
}
```

**Step 2:** Create the service file.

Follow the pattern from `src/services/safety.service.ts`. Use axios directly since the generated Zodios endpoints may not exist yet. Switch to `api.xyz()` calls once the schema is generated.

```typescript
// src/services/processDocuments.service.ts

import axios from 'axios'
import { toast } from 'vue-sonner'
import type {
  ProcessDocument,
  ProcessDocumentList,
  ProcessDocumentEntry,
  ProcessDocumentFilters,
  CreateProcessDocumentPayload,
  CreateEntryPayload,
} from '@/types/processDocument.types'

function buildQueryParams(filters: ProcessDocumentFilters): Record<string, string> {
  const params: Record<string, string> = {}
  if (filters.type) params.type = filters.type
  if (filters.tags.length) params.tags = filters.tags.join(',')
  if (filters.status !== 'all') params.status = filters.status
  if (filters.isTemplate !== null) params.is_template = String(filters.isTemplate)
  if (filters.search) params.q = filters.search
  return params
}

export async function listProcessDocuments(
  filters: ProcessDocumentFilters,
): Promise<ProcessDocumentList[]> {
  const params = buildQueryParams(filters)
  const response = await axios.get('/rest/process-documents/', { params })
  return response.data
}

export async function getProcessDocument(id: string): Promise<ProcessDocument> {
  const response = await axios.get(`/rest/process-documents/${id}/`)
  return response.data
}

export async function createProcessDocument(
  payload: CreateProcessDocumentPayload,
): Promise<ProcessDocument> {
  const response = await axios.post('/rest/process-documents/', payload)
  return response.data
}

export async function updateProcessDocument(
  id: string,
  payload: Partial<CreateProcessDocumentPayload>,
): Promise<ProcessDocument> {
  const response = await axios.put(`/rest/process-documents/${id}/`, payload)
  return response.data
}

export async function deleteProcessDocument(id: string): Promise<void> {
  await axios.delete(`/rest/process-documents/${id}/`)
}

export async function fillTemplate(
  id: string,
  jobId: string | null = null,
): Promise<ProcessDocument> {
  const response = await axios.post(`/rest/process-documents/${id}/fill/`, {
    job_id: jobId,
  })
  return response.data
}

export async function completeDocument(id: string): Promise<ProcessDocument> {
  const response = await axios.post(`/rest/process-documents/${id}/complete/`)
  return response.data
}

export async function listEntries(documentId: string): Promise<ProcessDocumentEntry[]> {
  const response = await axios.get(`/rest/process-documents/${documentId}/entries/`)
  return response.data
}

export async function createEntry(
  documentId: string,
  payload: CreateEntryPayload,
): Promise<ProcessDocumentEntry> {
  const response = await axios.post(`/rest/process-documents/${documentId}/entries/`, payload)
  return response.data
}

export async function updateEntry(
  documentId: string,
  entryId: string,
  payload: CreateEntryPayload,
): Promise<ProcessDocumentEntry> {
  const response = await axios.put(
    `/rest/process-documents/${documentId}/entries/${entryId}/`,
    payload,
  )
  return response.data
}
```

**Step 3:** Run type-check

```bash
npm run type-check
```

**Step 4:** Commit

```bash
git add src/types/processDocument.types.ts src/services/processDocuments.service.ts
git commit -m "feat(process-docs): add types and service layer"
```

---

### Task 3: Create Pinia store

**Files:**

- Create: `src/stores/processDocuments.ts`

**Step 1:** Create the store following the composition pattern from `src/stores/safetyDocuments.ts`.

```typescript
// src/stores/processDocuments.ts

import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { toast } from 'vue-sonner'
import type {
  ProcessDocument,
  ProcessDocumentList,
  ProcessDocumentEntry,
  ProcessDocumentFilters,
  CreateProcessDocumentPayload,
  CreateEntryPayload,
} from '@/types/processDocument.types'
import * as processDocService from '@/services/processDocuments.service'

export const useProcessDocumentsStore = defineStore('processDocuments', () => {
  // --- State ---
  const documents = ref<ProcessDocumentList[]>([])
  const currentDocument = ref<ProcessDocument | null>(null)
  const entries = ref<ProcessDocumentEntry[]>([])
  const formTemplates = ref<ProcessDocumentList[]>([])

  const isLoading = ref(false)
  const isLoadingDocument = ref(false)
  const isLoadingEntries = ref(false)
  const isSaving = ref(false)
  const error = ref<string | null>(null)

  const filters = ref<ProcessDocumentFilters>({
    type: null,
    tags: [],
    status: 'active',
    isTemplate: null,
    search: '',
  })

  // --- Getters ---
  const hasFormSchema = computed(() => {
    const schema = currentDocument.value?.form_schema
    return schema && 'fields' in schema && Array.isArray(schema.fields) && schema.fields.length > 0
  })

  const isTemplate = computed(() => currentDocument.value?.is_template ?? false)

  const isProse = computed(() => !hasFormSchema.value)

  // --- Actions ---

  const loadDocuments = async (): Promise<void> => {
    isLoading.value = true
    error.value = null
    try {
      documents.value = await processDocService.listProcessDocuments(filters.value)
    } catch (e) {
      error.value = 'Failed to load documents'
      toast.error('Failed to load process documents')
    } finally {
      isLoading.value = false
    }
  }

  const loadDocument = async (id: string): Promise<void> => {
    isLoadingDocument.value = true
    error.value = null
    try {
      currentDocument.value = await processDocService.getProcessDocument(id)
    } catch (e) {
      error.value = 'Failed to load document'
      toast.error('Failed to load document')
    } finally {
      isLoadingDocument.value = false
    }
  }

  const createDocument = async (
    payload: CreateProcessDocumentPayload,
  ): Promise<ProcessDocument | null> => {
    isSaving.value = true
    try {
      const doc = await processDocService.createProcessDocument(payload)
      toast.success('Document created')
      await loadDocuments()
      return doc
    } catch (e) {
      toast.error('Failed to create document')
      return null
    } finally {
      isSaving.value = false
    }
  }

  const updateDocument = async (
    id: string,
    payload: Partial<CreateProcessDocumentPayload>,
  ): Promise<ProcessDocument | null> => {
    isSaving.value = true
    try {
      const doc = await processDocService.updateProcessDocument(id, payload)
      currentDocument.value = doc
      toast.success('Document updated')
      return doc
    } catch (e) {
      toast.error('Failed to update document')
      return null
    } finally {
      isSaving.value = false
    }
  }

  const deleteDocument = async (id: string): Promise<boolean> => {
    try {
      await processDocService.deleteProcessDocument(id)
      documents.value = documents.value.filter((d) => d.id !== id)
      toast.success('Document deleted')
      return true
    } catch (e) {
      toast.error('Failed to delete document')
      return false
    }
  }

  const fillTemplate = async (
    id: string,
    jobId: string | null = null,
  ): Promise<ProcessDocument | null> => {
    isSaving.value = true
    try {
      const doc = await processDocService.fillTemplate(id, jobId)
      toast.success('Record created from template')
      return doc
    } catch (e) {
      toast.error('Failed to create record from template')
      return null
    } finally {
      isSaving.value = false
    }
  }

  const completeDocument = async (id: string): Promise<boolean> => {
    try {
      const doc = await processDocService.completeDocument(id)
      currentDocument.value = doc
      toast.success('Document marked as completed')
      return true
    } catch (e) {
      toast.error('Failed to complete document')
      return false
    }
  }

  const loadFormTemplates = async (): Promise<void> => {
    try {
      formTemplates.value = await processDocService.listProcessDocuments({
        type: 'form',
        tags: [],
        status: 'active',
        isTemplate: true,
        search: '',
      })
    } catch (e) {
      // Silent — nav just won't show form items
      console.error('Failed to load form templates for nav', e)
    }
  }

  const loadEntries = async (documentId: string): Promise<void> => {
    isLoadingEntries.value = true
    try {
      entries.value = await processDocService.listEntries(documentId)
    } catch (e) {
      toast.error('Failed to load entries')
    } finally {
      isLoadingEntries.value = false
    }
  }

  const addEntry = async (
    documentId: string,
    payload: CreateEntryPayload,
  ): Promise<ProcessDocumentEntry | null> => {
    isSaving.value = true
    try {
      const entry = await processDocService.createEntry(documentId, payload)
      entries.value = [entry, ...entries.value]
      toast.success('Entry added')
      return entry
    } catch (e) {
      toast.error('Failed to add entry')
      return null
    } finally {
      isSaving.value = false
    }
  }

  const updateEntry = async (
    documentId: string,
    entryId: string,
    payload: CreateEntryPayload,
  ): Promise<ProcessDocumentEntry | null> => {
    isSaving.value = true
    try {
      const entry = await processDocService.updateEntry(documentId, entryId, payload)
      entries.value = entries.value.map((e) => (e.id === entryId ? entry : e))
      toast.success('Entry updated')
      return entry
    } catch (e) {
      toast.error('Failed to update entry')
      return null
    } finally {
      isSaving.value = false
    }
  }

  const setFilters = (newFilters: Partial<ProcessDocumentFilters>): void => {
    filters.value = { ...filters.value, ...newFilters }
    loadDocuments()
  }

  const clearCurrentDocument = (): void => {
    currentDocument.value = null
    entries.value = []
  }

  return {
    // State
    documents,
    currentDocument,
    entries,
    formTemplates,
    isLoading,
    isLoadingDocument,
    isLoadingEntries,
    isSaving,
    error,
    filters,
    // Getters
    hasFormSchema,
    isTemplate,
    isProse,
    // Actions
    loadDocuments,
    loadDocument,
    createDocument,
    updateDocument,
    deleteDocument,
    fillTemplate,
    completeDocument,
    loadFormTemplates,
    loadEntries,
    addEntry,
    updateEntry,
    setFilters,
    clearCurrentDocument,
  }
})
```

**Step 2:** Run type-check

```bash
npm run type-check
```

**Step 3:** Commit

```bash
git add src/stores/processDocuments.ts
git commit -m "feat(process-docs): add Pinia store"
```

---

### Task 4: Create ProcessDocumentFilters component

**Files:**

- Create: `src/components/process-documents/ProcessDocumentFilters.vue`

**Context:** This renders the type pills, tag pills, status dropdown, templates toggle, and search input above the library table. See design doc "Filters" section.

**Step 1:** Create the component.

- Type pills: row of toggle buttons (All, Procedures, Forms, Registers, References). One active at a time.
- Tag pills: multi-select toggles generated from a `availableTags` prop (extracted from documents by the parent view). Click to toggle.
- Status: `<select>` dropdown defaulting to "Active"
- Templates toggle: checkbox
- Search: text input with debounced emit (300ms)

Use `@/components/ui/input`, `@/components/ui/badge`, `@/components/ui/checkbox` from shadcn-vue.

Props:

```typescript
interface Props {
  filters: ProcessDocumentFilters
  availableTags: string[]
}
```

Emits: `update:filters` with the new filters object.

**Key behaviour:**

- Type pills use `variant="outline"` for inactive, `variant="default"` for active
- Tag pills are small badges, clickable, highlighted when active
- Search input uses `watchDebounced` or manual `setTimeout`/`clearTimeout` (300ms) before emitting
- All filter changes emit immediately except search

**Step 2:** Run type-check

```bash
npm run type-check
```

**Step 3:** Commit

```bash
git add src/components/process-documents/ProcessDocumentFilters.vue
git commit -m "feat(process-docs): add filters component"
```

---

### Task 5: Create ProcessDocumentTable component

**Files:**

- Create: `src/components/process-documents/ProcessDocumentTable.vue`

**Context:** TanStack Vue Table showing the document list. See design doc "Table" section.

**Step 1:** Create the component using the pattern from `src/views/JobTable.vue`.

Props:

```typescript
interface Props {
  documents: ProcessDocumentList[]
  isLoading: boolean
}
```

Emits: `row-click`, `fill`, `complete`, `delete`, `open-google-doc`

Columns (defined using TanStack `ColumnDef`):

1. **Doc #** — `document_number`, custom sort: numeric (`(a, b) => Number(a) - Number(b)`)
2. **Title** — `title`, main column, flex grow
3. **Type** — `document_type`, render as `<Badge>` with variant by type
4. **Tags** — `tags`, render as small `<Badge variant="outline">` chips, show max 3 + "+N" overflow
5. **Status** — `status`, render as `<Badge>` with colour per status (green=active, yellow=draft, gray=completed, red=archived)
6. **Template** — `is_template`, render template icon (📋) if true, empty otherwise
7. **Updated** — `updated_at`, render as relative date (e.g. "2 days ago") using `Intl.RelativeTimeFormat` or a simple helper
8. **Actions** — render action buttons:
   - External link icon → emit `open-google-doc` (only if `google_doc_url` exists)
   - "Fill" button → emit `fill` (only if `is_template`)
   - "Complete" button → emit `complete` (only if `status === 'draft'`)
   - Delete icon → emit `delete`

Row click: emit `row-click` with the document. Parent handles navigation (procedures → detail, forms → entries page).

Loading state: skeleton rows or spinner overlay.

Empty state: centered message "No process documents found."

**Step 2:** Run type-check

```bash
npm run type-check
```

**Step 3:** Commit

```bash
git add src/components/process-documents/ProcessDocumentTable.vue
git commit -m "feat(process-docs): add document table component"
```

---

### Task 6: Create ProcessDocumentModal (create/edit)

**Files:**

- Create: `src/components/process-documents/ProcessDocumentModal.vue`

**Context:** Dialog for creating a new document or editing metadata. See design doc "New Document Modal" section. Follow the pattern from `src/components/JobFormModal.vue`.

**Step 1:** Create the component.

Props:

```typescript
interface Props {
  open: boolean
  editDocument?: ProcessDocument | null // null = create mode, set = edit mode
}
```

Emits: `close`, `saved`

Uses: `Dialog`, `DialogContent`, `DialogHeader`, `DialogTitle` from `@/components/ui/dialog`

Form fields:

- **Title** (required): `<Input>` text
- **Document #** (optional): `<Input>` text
- **Type** (required): `<select>` with options: procedure, form, register, reference
- **Tags**: `<Input>` text, comma-separated (split on submit)
- **Is template**: `<Checkbox>`
- **Form Schema (JSON)**: `<Textarea>` — only visible when type === 'form' AND is_template is checked. Validate JSON on submit.

Submit: call store's `createDocument()` or `updateDocument()`, emit `saved` on success, emit `close`.

Loading state on submit button (like `JobFormModal.vue`).

**Step 2:** Run type-check

```bash
npm run type-check
```

**Step 3:** Commit

```bash
git add src/components/process-documents/ProcessDocumentModal.vue
git commit -m "feat(process-docs): add create/edit document modal"
```

---

### Task 7: Create ProcessDocumentsView (library page)

**Files:**

- Create: `src/views/ProcessDocumentsView.vue`

**Context:** The main library page at `/process-documents`. Composes filters + table + modal. See design doc "Page 1: Procedures Library".

**Step 1:** Create the view.

Structure:

```html
<template>
  <div class="p-6 max-w-7xl mx-auto">
    <!-- Header -->
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold">Process Documents</h1>
      <button @click="showCreateModal = true"><Plus class="w-4 h-4 mr-1" /> New Document</button>
    </div>

    <!-- Filters -->
    <ProcessDocumentFilters
      :filters="store.filters"
      :available-tags="availableTags"
      @update:filters="store.setFilters"
    />

    <!-- Table -->
    <ProcessDocumentTable
      :documents="store.documents"
      :is-loading="store.isLoading"
      @row-click="handleRowClick"
      @fill="handleFill"
      @complete="handleComplete"
      @delete="handleDelete"
      @open-google-doc="openGoogleDoc"
    />

    <!-- Create/Edit Modal -->
    <ProcessDocumentModal
      :open="showCreateModal"
      :edit-document="editingDocument"
      @close="closeModal"
      @saved="handleSaved"
    />
  </div>
</template>
```

Key logic:

- `onMounted` → call `store.loadDocuments()`
- `availableTags` = computed, extract unique tags from `store.documents`
- `handleRowClick`: if `document_type === 'form'` → `router.push('/process-documents/forms/' + id)`, else → `router.push('/process-documents/' + id)`
- `handleFill`: open FillTemplateModal (Task 10)
- `handleDelete`: confirmation dialog (use `window.confirm` initially, upgrade to proper dialog later), then `store.deleteDocument(id)`
- `openGoogleDoc`: `window.open(url, '_blank')`

**Step 2:** Run type-check and dev server

```bash
npm run type-check
npm run dev
```

Manually verify the page loads at `/process-documents` (will show empty state until backend is connected).

**Step 3:** Commit

```bash
git add src/views/ProcessDocumentsView.vue
git commit -m "feat(process-docs): add library page view"
```

---

### Task 8: Add routes

**Files:**

- Modify: `src/router/index.ts`

**Step 1:** Add three routes before the safety routes (around line 272):

```typescript
{
  path: '/process-documents',
  name: 'process-documents',
  component: () => import('@/views/ProcessDocumentsView.vue'),
  meta: { requiresAuth: true, title: 'Process Documents - DocketWorks' },
},
{
  path: '/process-documents/forms/:id',
  name: 'form-entries',
  component: () => import('@/views/FormEntriesView.vue'),
  meta: { requiresAuth: true, title: 'Form Entries - DocketWorks' },
},
{
  path: '/process-documents/:id',
  name: 'process-document-detail',
  component: () => import('@/views/ProcessDocumentDetailView.vue'),
  meta: { requiresAuth: true, title: 'Process Document - DocketWorks' },
},
```

**Important:** The `/process-documents/forms/:id` route MUST come before `/process-documents/:id` so Vue Router matches it first (more specific route first).

**Step 2:** Create stub views for the two views that don't exist yet:

Create minimal `src/views/FormEntriesView.vue` and `src/views/ProcessDocumentDetailView.vue` with just a `<template><div>TODO</div></template>` so the routes don't break.

**Step 3:** Run type-check

```bash
npm run type-check
```

**Step 4:** Commit

```bash
git add src/router/index.ts src/views/FormEntriesView.vue src/views/ProcessDocumentDetailView.vue
git commit -m "feat(process-docs): add routes and stub views"
```

---

### Task 9: Create ProcessDocumentDetailView (prose detail)

**Files:**

- Modify: `src/views/ProcessDocumentDetailView.vue` (replace stub)

**Context:** Detail page for prose documents (procedures, references). See design doc "Page 2: Procedure Detail".

**Step 1:** Build the view.

Structure:

- Back link to `/process-documents`
- Header: title, badges for document_number, document_type, status, template indicator
- Metadata: created/updated dates, company, site_location, linked job (if job_id), parent template link (if parent_template_id)
- Tags: display as badges (editable in future, read-only for now)
- Content section: "This document lives in Google Docs" + "Open in Google Docs" button
- If template: "Fill in this form" button (opens FillTemplateModal)
- If template: ChildRecordsTable showing records created from this template

Uses `store.loadDocument(id)` on mount (get `id` from `route.params.id`).

**Step 2:** Create `src/components/process-documents/ChildRecordsTable.vue`:

Simple table showing records created from a template. Props: `templateId: string`. On mount, fetches documents filtered by `parent_template_id`. Columns: Created date, Status, Job #, link to detail.

Uses `processDocService.listProcessDocuments()` with a `parent_template_id` param (once backend supports it). For now, can be a placeholder.

**Step 3:** Run type-check

```bash
npm run type-check
```

**Step 4:** Commit

```bash
git add src/views/ProcessDocumentDetailView.vue src/components/process-documents/ChildRecordsTable.vue
git commit -m "feat(process-docs): add prose document detail view"
```

---

### Task 10: Create FillTemplateModal

**Files:**

- Create: `src/components/process-documents/FillTemplateModal.vue`

**Context:** Modal shown when user clicks "Fill in this form" on a template. Has optional job picker. See design doc "Fill Workflow" section.

**Step 1:** Create the component.

Props:

```typescript
interface Props {
  open: boolean
  template: ProcessDocument | ProcessDocumentList | null
}
```

Emits: `close`, `filled` (with the new ProcessDocument)

Structure:

- Dialog with title "Create a record from [template title]"
- Optional job search field — reuse the pattern from `src/components/purchasing/JobSelect.vue`. Import it or build a simpler version: text input that searches jobs, dropdown with results.
- [Cancel] [Create] buttons

On submit:

1. Call `store.fillTemplate(template.id, selectedJobId)`
2. If result is prose (has google_doc_url): `window.open(result.google_doc_url, '_blank')`
3. If result is form: navigate to `/process-documents/forms/${result.id}`
4. Else: navigate to `/process-documents/${result.id}`
5. Emit `filled` and `close`

**Step 2:** Run type-check

```bash
npm run type-check
```

**Step 3:** Commit

```bash
git add src/components/process-documents/FillTemplateModal.vue
git commit -m "feat(process-docs): add fill template modal with job picker"
```

---

### Task 11: Create DynamicFormEntry component

**Files:**

- Create: `src/components/process-documents/DynamicFormEntry.vue`

**Context:** Renders a form from `form_schema.fields`. Used in the form entries page for adding/editing entries. See design doc "Form entry UI".

**Step 1:** Create the component.

Props:

```typescript
interface Props {
  schema: FormSchema
  initialData?: Record<string, unknown> // for editing existing entries
  isSubmitting?: boolean
}
```

Emits: `submit` (with `{ entry_date: string, data: Record<string, unknown> }`)

Logic:

- `entry_date` field: date input, defaults to today (`new Date().toISOString().split('T')[0]`)
- For each field in `schema.fields`, render the appropriate input:
  - `text` → `<Input type="text">`
  - `textarea` → `<Textarea>`
  - `date` → `<Input type="date">`
  - `boolean` → `<Checkbox>`
  - `number` → `<Input type="number">`
  - `select` → `<select>` with `<option>` for each item in `field.options`
- Track form data in a reactive `Record<string, unknown>` keyed by `field.key`
- Required field validation: check all fields with `required: true` have non-empty values before emitting submit
- Show validation errors inline per field
- Submit button disabled when `isSubmitting` or validation fails

**Step 2:** Run type-check

```bash
npm run type-check
```

**Step 3:** Commit

```bash
git add src/components/process-documents/DynamicFormEntry.vue
git commit -m "feat(process-docs): add dynamic form entry component"
```

---

### Task 12: Create EntriesTable component

**Files:**

- Create: `src/components/process-documents/EntriesTable.vue`

**Context:** Table showing entries for a form document. Columns are dynamic, derived from `form_schema.fields`. See design doc "Entries" section.

**Step 1:** Create the component.

Props:

```typescript
interface Props {
  entries: ProcessDocumentEntry[]
  schema: FormSchema
  isLoading: boolean
}
```

Emits: `edit` (with entry)

Build TanStack table columns dynamically:

1. **Date** column — `entry_date`, sorted descending by default
2. **Entered By** column — `entered_by_name`
3. **One column per schema field** — for each `field` in `schema.fields`, create a column where the accessor is `(row) => row.data[field.key]`. Display label is `field.label`. Boolean values render as ✓/✗. Dates formatted. Select values as-is.
4. **Actions** column — edit icon button, emits `edit`

Empty state: "No entries yet. Add the first entry above."

**Step 2:** Run type-check

```bash
npm run type-check
```

**Step 3:** Commit

```bash
git add src/components/process-documents/EntriesTable.vue
git commit -m "feat(process-docs): add dynamic entries table component"
```

---

### Task 13: Create FormEntriesView

**Files:**

- Modify: `src/views/FormEntriesView.vue` (replace stub)

**Context:** The main page for form-type documents — what users see when they click "Incident Register" in the nav. Composes DynamicFormEntry + EntriesTable. See design doc "Page 3: Form Entries".

**Step 1:** Build the view.

Structure:

```html
<template>
  <div class="p-6 max-w-7xl mx-auto">
    <!-- Header -->
    <h1 class="text-2xl font-bold">{{ store.currentDocument?.title }}</h1>
    <p class="text-gray-500 mt-1">{{ description or metadata }}</p>

    <!-- Status + actions bar -->
    <div class="flex items-center gap-4 mt-4">
      <Badge>{{ store.currentDocument?.status }}</Badge>
      <button v-if="store.currentDocument?.status === 'draft'" @click="handleComplete">
        Mark as Completed
      </button>
    </div>

    <!-- Add Entry form (collapsible or always visible) -->
    <Card class="mt-6">
      <CardHeader>
        <CardTitle>Add Entry</CardTitle>
      </CardHeader>
      <CardContent>
        <DynamicFormEntry
          v-if="store.hasFormSchema"
          :schema="store.currentDocument.form_schema"
          :is-submitting="store.isSaving"
          @submit="handleAddEntry"
        />
      </CardContent>
    </Card>

    <!-- Entries table -->
    <div class="mt-6">
      <h2 class="text-lg font-semibold mb-3">Entries ({{ store.entries.length }})</h2>
      <EntriesTable
        :entries="store.entries"
        :schema="store.currentDocument?.form_schema"
        :is-loading="store.isLoadingEntries"
        @edit="handleEditEntry"
      />
    </div>
  </div>
</template>
```

Key logic:

- Get `id` from `route.params.id`
- On mount: `store.loadDocument(id)` then `store.loadEntries(id)`
- `handleAddEntry`: call `store.addEntry(id, payload)`
- `handleEditEntry`: open DynamicFormEntry in edit mode (modal or inline), call `store.updateEntry()`
- `handleComplete`: `store.completeDocument(id)`
- On unmount: `store.clearCurrentDocument()`

**Step 2:** Run type-check and dev server

```bash
npm run type-check
npm run dev
```

**Step 3:** Commit

```bash
git add src/views/FormEntriesView.vue
git commit -m "feat(process-docs): add form entries view"
```

---

### Task 14: Update AppNavbar with dynamic form templates

**Files:**

- Modify: `src/components/AppNavbar.vue`

**Context:** Replace the current safety dropdown contents with: Procedures link, dynamic form template links, JSA link, Staff Training link. See design doc "Navigation" section. Both desktop and mobile menus need updating.

**Step 1:** Import and use the process documents store in the navbar.

In the `<script setup>` section, add:

```typescript
import { useProcessDocumentsStore } from '@/stores/processDocuments'
import { FileText, ClipboardList } from 'lucide-vue-next'

const processDocsStore = useProcessDocumentsStore()

onMounted(() => {
  processDocsStore.loadFormTemplates()
})
```

**Step 2:** Replace the desktop "safety" dropdown contents (lines ~155-181).

Replace the current items (JSA, SWP, Machine Maintenance, Staff Training) with:

```html
<!-- Procedures -->
<RouterLink
  to="/process-documents"
  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
>
  <FileText class="w-4 h-4 mr-2" /> Procedures
</RouterLink>

<div class="border-t border-gray-200 my-1"></div>

<!-- Dynamic form templates -->
<template v-if="processDocsStore.formTemplates.length > 0">
  <RouterLink
    v-for="template in processDocsStore.formTemplates"
    :key="template.id"
    :to="`/process-documents/forms/${template.id}`"
    class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
  >
    <ClipboardList class="w-4 h-4 mr-2" /> {{ template.title }}
  </RouterLink>
</template>
<div v-else class="px-4 py-2 text-sm text-gray-400 italic">No forms configured</div>

<div class="border-t border-gray-200 my-1"></div>

<!-- JSA (existing) -->
<RouterLink
  to="/safety/jsa"
  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
>
  <ShieldCheck class="w-4 h-4 mr-2" /> Job Safety Analyses
</RouterLink>

<!-- Staff Training (existing) -->
<a
  href="/manual/"
  target="_blank"
  @click="activeDropdown = null"
  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-gray-50 font-medium transition-all"
>
  <GraduationCap class="w-4 h-4 mr-2" /> Staff Training
</a>
```

**Step 3:** Make the same changes to the mobile menu section (lines ~570-600). Follow the same structure: Procedures, dynamic forms, JSA, Staff Training.

**Step 4:** Remove the SWP link and Machine Maintenance button from both desktop and mobile menus (they're now accessible via the process documents library).

**Step 5:** Run type-check and dev server

```bash
npm run type-check
npm run dev
```

Manually verify the dropdown renders correctly.

**Step 6:** Commit

```bash
git add src/components/AppNavbar.vue
git commit -m "feat(process-docs): update nav with dynamic form templates"
```

---

### Task 15: Integration testing and polish

**Files:**

- All created files from previous tasks

**Step 1:** Run full type-check

```bash
npm run type-check
```

Fix any type errors.

**Step 2:** Run existing tests to verify nothing broke

```bash
npm run test
```

**Step 3:** Run the dev server and manually test:

```bash
npm run dev
```

Test checklist:

- [ ] `/process-documents` loads with empty state
- [ ] "New Document" modal opens and form works
- [ ] Type/tag/status filters change the request params
- [ ] Row click navigates to correct page (prose → detail, form → entries)
- [ ] Procedure detail page shows metadata, Google Docs button
- [ ] Form entries page shows dynamic form from schema
- [ ] Adding an entry works and appears in table
- [ ] Nav dropdown shows "Procedures", form templates, JSA, Staff Training
- [ ] Empty state in nav when no form templates exist
- [ ] Delete confirmation dialog works
- [ ] Fill template modal opens with job picker
- [ ] Mobile nav menu updated and working

**Step 4:** Fix any issues found during testing.

**Step 5:** Final commit

```bash
git add -A
git commit -m "feat(process-docs): integration polish and fixes"
```

---

## Summary of files created/modified

**New files (12):**

- `src/types/processDocument.types.ts`
- `src/services/processDocuments.service.ts`
- `src/stores/processDocuments.ts`
- `src/components/process-documents/ProcessDocumentFilters.vue`
- `src/components/process-documents/ProcessDocumentTable.vue`
- `src/components/process-documents/ProcessDocumentModal.vue`
- `src/components/process-documents/FillTemplateModal.vue`
- `src/components/process-documents/DynamicFormEntry.vue`
- `src/components/process-documents/EntriesTable.vue`
- `src/components/process-documents/ChildRecordsTable.vue`
- `src/views/ProcessDocumentsView.vue`
- `src/views/FormEntriesView.vue`
- `src/views/ProcessDocumentDetailView.vue`

**Modified files (2):**

- `src/router/index.ts` — add 3 routes
- `src/components/AppNavbar.vue` — replace safety dropdown with dynamic process docs nav

**Backend dependencies:**

- `?parent_template_id=<id>` filter on list endpoint
- Entry PUT endpoint for editing
- OpenAPI schema with all process document endpoints
