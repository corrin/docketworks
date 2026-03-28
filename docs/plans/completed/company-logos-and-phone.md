# Add Company Logos to CompanyDefaults

## Context

CompanyDefaults has no logo fields. Logos are currently hardcoded to `static/logo_msm.png` in both PDF services. This change adds `logo` and `logo_wide` ImageFields to CompanyDefaults with a dedicated upload endpoint, updates both PDF services to read from the model, and adds image upload support to the frontend settings UI.

---

## Step 1: Model — Add ImageFields

**File:** `apps/workflow/models/company_defaults.py` (after `company_url`, ~line 199)

```python
logo = models.ImageField(
    upload_to="company_logos/",
    null=True,
    blank=True,
    help_text="Company logo (square/standard)",
)
logo_wide = models.ImageField(
    upload_to="company_logos/",
    null=True,
    blank=True,
    help_text="Wide company logo for letterheads and PDFs",
)
```

**File:** `apps/workflow/models/settings_metadata.py`

- Add `"logo": "company"` and `"logo_wide": "company"` to `COMPANY_DEFAULTS_FIELD_SECTIONS`
- Add `models.ImageField: "image"` to `DJANGO_TO_UI_TYPE` (before `CharField` since ImageField inherits from FileField not CharField — but add it at the top of the dict for clarity)

Run `poetry run python manage.py makemigrations workflow`

---

## Step 2: Serializer — Add logo_url / logo_wide_url

**File:** `apps/workflow/serializers.py`

Update `CompanyDefaultsSerializer`:
- Add `logo` and `logo_wide` as `write_only=True` (exclude raw paths from GET responses)
- Add `logo_url` and `logo_wide_url` as `SerializerMethodField(read_only=True)`
- Helper function `_build_logo_url(instance, field_name, context)` following the staff icon pattern from `apps/accounts/serializers.py:14`

---

## Step 3: Upload Endpoint

**New file:** `apps/workflow/views/company_defaults_logo_api.py`

`CompanyDefaultsLogoAPIView(APIView)`:
- `parser_classes = [MultiPartParser, FormParser]`
- `permission_classes = [IsAuthenticated]`
- **POST**: accepts `field_name` (must be `"logo"` or `"logo_wide"`) and `file`. Saves to the appropriate ImageField. Returns updated CompanyDefaults via serializer.
- **DELETE**: accepts JSON `field_name`. Clears the field, deletes the file from disk. Returns updated CompanyDefaults.

**File:** `apps/workflow/urls.py` — Add route:
```python
path("company-defaults/upload-logo/", CompanyDefaultsLogoAPIView.as_view(), name="api_company_defaults_upload_logo"),
```

---

## Step 4: PDF Services — Read from CompanyDefaults

**File:** `apps/purchasing/services/purchase_order_pdf_service.py` (lines 74-114, `add_logo` method)

Replace entire method body:
```python
def add_logo(self, y_position):
    company = CompanyDefaults.get_solo()
    if not company.logo_wide:
        raise ValueError("No wide logo uploaded in Company Defaults")
    logo = ImageReader(company.logo_wide.path)
    self.pdf.drawImage(
        logo,
        PAGE_WIDTH - MARGIN - 120,
        y_position - 80,
        width=120, height=80,
        preserveAspectRatio=True, mask="auto",
    )
    return y_position - 90
```

**File:** `apps/job/services/workshop_pdf_service.py` (lines 519-527, `add_logo` function)

Replace entire function body:
```python
def add_logo(pdf, y_position):
    company = CompanyDefaults.get_solo()
    if not company.logo_wide:
        raise ValueError("No wide logo uploaded in Company Defaults")
    logo = ImageReader(company.logo_wide.path)
    x = MARGIN + (CONTENT_WIDTH - 150) / 2
    pdf.drawImage(logo, x, y_position - 150, width=150, height=150, mask="auto")
    return y_position - 200
```

---

## Step 5: Frontend — Image Upload Support in Settings UI

**File:** `frontend/src/components/SectionModal.vue`

Add new branch in field type rendering (before the fallback `<Input>`):
```
v-else-if="field.type === 'image'"
```
Renders:
- Current image thumbnail if URL exists (from `logo_url`/`logo_wide_url` in form data)
- File input / upload button
- Delete button to clear
- On file select: immediately calls upload endpoint, refreshes form data
- Image fields skipped from the JSON `saveAll()` payload

**File:** `frontend/src/views/AdminCompanyView.vue`

In `saveAll()`: skip fields where `field.type === 'image'` when building the JSON payload.

**File:** `frontend/src/services/admin-company-defaults-service.ts`

Add:
- `uploadLogo(fieldName: string, file: File): Promise` — POST multipart to `/api/company-defaults/upload-logo/`
- `deleteLogo(fieldName: string): Promise` — DELETE to `/api/company-defaults/upload-logo/`

---

## Step 6: Cleanup

- Delete `static/logo_msm.png` (no longer referenced)
- Run `poetry run python scripts/update_init.py`

---

## Key Files Modified

| File | Change |
|------|--------|
| `apps/workflow/models/company_defaults.py` | Add `logo`, `logo_wide` ImageFields |
| `apps/workflow/models/settings_metadata.py` | Add section mappings + `image` UI type |
| `apps/workflow/serializers.py` | Add `logo_url`, `logo_wide_url` read-only fields |
| `apps/workflow/views/company_defaults_logo_api.py` | **New** — upload/delete endpoint |
| `apps/workflow/urls.py` | Add upload-logo route |
| `apps/purchasing/services/purchase_order_pdf_service.py` | Read logo from CompanyDefaults |
| `apps/job/services/workshop_pdf_service.py` | Read logo from CompanyDefaults |
| `frontend/src/components/SectionModal.vue` | Add image type rendering |
| `frontend/src/views/AdminCompanyView.vue` | Skip image fields in JSON save |
| `frontend/src/services/admin-company-defaults-service.ts` | Add upload/delete functions |

## Verification

1. `poetry run python manage.py makemigrations --check` — migration exists
2. `poetry run python manage.py migrate` — applies cleanly
3. `poetry run python -m pytest apps/workflow/tests/test_company_defaults_schema.py` — all fields have sections
4. `GET /api/company-defaults/schema/` — `logo` and `logo_wide` appear with `type: "image"` in company section
5. `POST /api/company-defaults/upload-logo/` with a test image — file appears in `mediafiles/company_logos/`, `logo_wide_url` returned in GET response
6. `DELETE /api/company-defaults/upload-logo/` — field cleared, file removed
7. Generate a PO PDF — uses uploaded wide logo
8. Generate a workshop PDF — uses uploaded wide logo
9. Frontend: open Company settings, see image upload widgets, upload/delete works
