# Backend Requirements: Process Documents API Gaps

**Context:** The frontend needs these API changes to build the Process Documents UI. The ProcessDocument and ProcessDocumentEntry models already exist. Some endpoints exist but several are missing.

---

## 1. Add UPDATE to ProcessDocument endpoint

**What exists:** `GET /rest/process-documents/<id>/` (retrieve) and `DELETE /rest/process-documents/<id>/` (destroy) work. There is no PUT or PATCH.

**What's needed:** `PUT /rest/process-documents/<id>/` that accepts partial or full updates to document metadata.

**Writable fields:**

| Field             | Type             | Notes                                                 |
| ----------------- | ---------------- | ----------------------------------------------------- |
| `title`           | string           | Required, max 255                                     |
| `document_number` | string           | Optional, max 50                                      |
| `document_type`   | string           | One of: `procedure`, `form`, `register`, `reference`  |
| `tags`            | array of strings | e.g. `["safety", "machinery"]`                        |
| `is_template`     | boolean          |                                                       |
| `form_schema`     | object           | JSON schema for form fields. `{}` when not applicable |
| `site_location`   | string           | Optional, max 500                                     |
| `status`          | string           | One of: `draft`, `active`, `completed`, `archived`    |

**Read-only fields** (should NOT be writable via PUT): `id`, `google_doc_id`, `google_doc_url`, `parent_template_id`, `job_id`, `job_number`, `company_name`, `created_at`, `updated_at`

**Response:** Full detail representation (same as GET retrieve).

---

## 2. Add `parent_template_id` filter to list endpoint

**What exists:** `GET /rest/process-documents/` supports these query params: `?type=`, `?q=`, `?tags=`, `?status=`, `?is_template=`

**What's needed:** Add `?parent_template_id=<uuid>` filter.

**Behaviour:** When provided, return only documents whose `parent_template` foreign key matches the given UUID. This lets the frontend show "records created from this template" on a template's detail page.

**Example:**

```
GET /rest/process-documents/?parent_template_id=abc-123-def
```

Returns all filled records that were created from template `abc-123-def`.

---

## 3. ProcessDocumentEntry CRUD endpoints

**What exists:** The `ProcessDocumentEntry` model and a serializer exist, but there are NO API endpoints wired up — no views, no URL patterns.

**What's needed:** Full CRUD nested under each document:

### 3a. List entries

```
GET /rest/process-documents/<document_id>/entries/
```

**Response:** Array of entry objects, ordered by `-entry_date`, then `-created_at` (newest first).

```json
[
  {
    "id": "uuid",
    "document": "parent-document-uuid",
    "entry_date": "2026-03-05",
    "entered_by": "staff-uuid",
    "entered_by_name": "John Smith",
    "data": {
      "equipment_name": "Press Brake",
      "condition": "OK",
      "inspected": true
    },
    "created_at": "2026-03-05T10:00:00Z"
  }
]
```

**Fields:**
| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Read-only |
| `document` | UUID | Read-only, set from URL |
| `entry_date` | date (YYYY-MM-DD) | Required |
| `entered_by` | UUID or null | Read-only, set from authenticated user |
| `entered_by_name` | string or null | Read-only, display name of the staff member |
| `data` | object | Keys should match the parent document's `form_schema.fields[].key` values |
| `created_at` | datetime | Read-only |

### 3b. Create entry

```
POST /rest/process-documents/<document_id>/entries/
```

**Request body:**

```json
{
  "entry_date": "2026-03-05",
  "data": {
    "equipment_name": "Press Brake",
    "condition": "OK",
    "inspected": true
  }
}
```

**Behaviour:**

- `document` is set automatically from the URL path (not from request body)
- `entered_by` is set automatically from the authenticated user's staff profile
- Return the full entry object (same shape as list items)
- Return `201 Created`

### 3c. Update entry

```
PUT /rest/process-documents/<document_id>/entries/<entry_id>/
```

**Request body:** Same shape as create (`entry_date` + `data`).

**Behaviour:**

- Only `entry_date` and `data` are writable
- `entered_by` does NOT change on update (stays as original creator)
- Return the full updated entry object
- Return `200 OK`

### 3d. Delete entry

```
DELETE /rest/process-documents/<document_id>/entries/<entry_id>/
```

**Behaviour:**

- Soft delete if the project uses soft delete for entries, otherwise hard delete is fine
- Return `204 No Content`

---

## 4. OpenAPI schema coverage

All process document endpoints need `@extend_schema` decorators (or whatever mechanism the project uses) so they appear in the generated OpenAPI/Swagger schema. The frontend runs `npm run update-schema && npm run gen:api` to pull the schema and generate a typed API client.

**Endpoints that must be in the schema:**

| Endpoint                                      | Method | Notes                       |
| --------------------------------------------- | ------ | --------------------------- |
| `/rest/process-documents/`                    | GET    | List with filters           |
| `/rest/process-documents/`                    | POST   | Create                      |
| `/rest/process-documents/<id>/`               | GET    | Retrieve detail             |
| `/rest/process-documents/<id>/`               | PUT    | **NEW** — Update metadata   |
| `/rest/process-documents/<id>/`               | DELETE | Destroy                     |
| `/rest/process-documents/<id>/content/`       | GET    | Read Google Doc content     |
| `/rest/process-documents/<id>/content/`       | PUT    | Write Google Doc content    |
| `/rest/process-documents/<id>/fill/`          | POST   | Create record from template |
| `/rest/process-documents/<id>/complete/`      | POST   | Mark as completed           |
| `/rest/process-documents/<id>/entries/`       | GET    | **NEW** — List entries      |
| `/rest/process-documents/<id>/entries/`       | POST   | **NEW** — Create entry      |
| `/rest/process-documents/<id>/entries/<eid>/` | PUT    | **NEW** — Update entry      |
| `/rest/process-documents/<id>/entries/<eid>/` | DELETE | **NEW** — Delete entry      |

For each endpoint, the schema should define:

- Request body schema (for POST/PUT)
- Response schema
- Query parameter definitions (for GET list)

**Specifically for the list endpoint**, the schema should document these query params: `type`, `q`, `tags`, `status`, `is_template`, `parent_template_id` (new).

---

## Acceptance criteria

After these changes, the following should work:

1. `PUT /rest/process-documents/<id>/` updates a document's title, tags, etc. and returns the updated detail
2. `GET /rest/process-documents/?parent_template_id=<uuid>` returns only children of that template
3. `POST /rest/process-documents/<id>/entries/` creates an entry with `entered_by` auto-set from auth user
4. `GET /rest/process-documents/<id>/entries/` returns entries newest-first
5. `PUT /rest/process-documents/<id>/entries/<eid>/` updates entry_date and data
6. `DELETE /rest/process-documents/<id>/entries/<eid>/` removes an entry
7. All endpoints appear in the OpenAPI schema with request/response types defined
