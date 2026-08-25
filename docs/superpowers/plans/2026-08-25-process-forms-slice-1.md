# Process Forms (Slice 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the forms half of the process-documents domain — forms, entries with audit events and cross-entry links, categories — ending with the MUST-tier `form-entries-page-scroll` E2E spec green plus an authored lifecycle spec.

**Architecture:** Django-ninja router at `/api/process/` over the existing `apps/process` models (extended with `category`, `parent_entry`, `updated_at`, minus simple-history, plus a new `ProcessEvent` audit model). Services own validation and event writes; API handlers stay thin. React feature `features/process/` with a shared schema-driven entry form. All list/nav/dialog idioms copy named precedent files.

**Tech Stack:** Django 6 + django-ninja + pydantic v2 (backend), React + TanStack Router/Query + generated openapi-ts client + shadcn primitives (frontend), pytest, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-25-process-documents-design.md` — read it first; this plan implements its Slice 1 exactly, with two recorded refinements:
1. *422 vs 400*: schema-structure violations are 422 (typed request schema — pydantic rejects them), entry-data violations are 400 via `HttpError(400, ...)`, matching the codebase's only established convention for post-parse validation (`apps/accounts/api.py:225-245`). The spec's "422s" sentence is satisfied for schema structure and refined for entry data.
2. *Navbar*: the Forms menu is static `NavMenuLink`s like every other AppNavbar menu (categories are code-level enums; a new enum is a code change anyway), not fetched from the categories endpoint. The categories endpoint still ships — the list pages and dialogs use it.

## Global Constraints

- Every gate from CLAUDE.md runs on commit; never `--no-verify`. The regenerating hooks (exported schema, generated client, status table, code-quality) rewrite artifacts — on hook failure, `git add` the refreshed files and commit again.
- mypy strict, zero baseline; no `Any`, no bare `# type: ignore`.
- ADR 0040: nullable text is `NullableText` on the wire; services never coerce `value or None`.
- ADR 0038: transparent error messages after authentication.
- ADR 0043: comments record the rejected alternative, prefixed `Fable:` when AI-originated.
- A GET never writes. Guard-clause shape. `raise X from exc` on conversions.
- Wire field names are snake_case (verified convention; the "camelCase" note in rewrite-status constraint 3 applies only to two aliased fields).
- No emojis anywhere.
- E2E-seeded rows use the `[TEST]` title prefix.
- Frontend loop check is `npm run type-check`, never `npm run build`. Backend loop is scoped pytest (`uv run pytest apps/process`), never the full suite.
- Commit at the end of every task (stage explicit paths). Branch: `process-documents`.

---

### Task 1: Hoist pagination to `apps/core/pagination.py`

The company app's `paginate` docstring says "hoist to `apps/core` when a second domain app pages a list"; crm already re-implemented it inline, and process would be a third copy — which `find-duplicates` (pre-commit) may reject and ADR 0039 certainly does.

**Files:**
- Create: `apps/core/pagination.py`
- Create: `apps/core/tests/test_pagination.py`
- Modify: `apps/company/api.py` (delete `PageData`/`paginate`/`DEFAULT_PAGE_SIZE`/`MAX_PAGE_SIZE` at `:140-181`, import from core)
- Modify: `apps/crm/api.py:294-340` (delete the inline `_effective_page_size` copy, import from core)

**Interfaces:**
- Produces: `apps.core.pagination.PageData[M]` (frozen dataclass: `rows: list[M]`, `count: int`, `page: int`, `page_size: int`, `total_pages: int`) and `paginate(queryset, *, page: int, page_size: int | None) -> PageData[M]` raising `Http404` on an out-of-range page. `DEFAULT_PAGE_SIZE = 50`, `MAX_PAGE_SIZE = 100`.
- Consumed by: Task 8 (entries list), and immediately by company + crm.

- [ ] **Step 1: Write the failing test**

`apps/core/tests/test_pagination.py`:

```python
"""The one pagination envelope (results/count/page/page_size/total_pages).

Company, CRM and process all page lists; this module is the single
implementation they share (the company app's docstring asked for the hoist
on the second consumer).
"""

import pytest
from django.http import Http404

from apps.accounts.models import Staff
from apps.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, paginate

pytestmark = pytest.mark.django_db


def make_staff(count: int) -> None:
    for index in range(count):
        Staff.objects.create_user(
            office_email=f"page{index}@example.com",
            password="s3cret-Pass!",
            first_name="Page",
            last_name=str(index),
        )


class TestPaginate:
    def test_defaults_to_page_size_50(self) -> None:
        make_staff(3)
        page = paginate(Staff.objects.order_by("office_email"), page=1, page_size=None)
        assert page.page_size == DEFAULT_PAGE_SIZE
        assert page.count == 3
        assert page.total_pages == 1
        assert len(page.rows) == 3

    def test_caps_page_size_at_100(self) -> None:
        make_staff(1)
        page = paginate(Staff.objects.all(), page=1, page_size=9999)
        assert page.page_size == MAX_PAGE_SIZE

    def test_zero_or_negative_page_size_falls_back_to_default(self) -> None:
        make_staff(1)
        assert paginate(Staff.objects.all(), page=1, page_size=0).page_size == DEFAULT_PAGE_SIZE
        assert paginate(Staff.objects.all(), page=1, page_size=-5).page_size == DEFAULT_PAGE_SIZE

    def test_out_of_range_page_is_404(self) -> None:
        make_staff(1)
        with pytest.raises(Http404):
            paginate(Staff.objects.all(), page=99, page_size=None)

    def test_slices_the_requested_page(self) -> None:
        make_staff(5)
        page = paginate(Staff.objects.order_by("office_email"), page=2, page_size=2)
        assert page.page == 2
        assert page.count == 5
        assert page.total_pages == 3
        assert len(page.rows) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/core/tests/test_pagination.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.core.pagination'`

- [ ] **Step 3: Move the implementation**

Create `apps/core/pagination.py` by moving `DEFAULT_PAGE_SIZE`, `MAX_PAGE_SIZE`, `PageData` and `paginate` **verbatim** from `apps/company/api.py:140-181` (a move, not a copy — ADR 0039). Update the docstring's last sentence from "Lives here because the company app is currently its only consumer; hoist to `apps/core` when a second domain app pages a list." to "Lives in core because company, CRM and process all page lists."

Then in `apps/company/api.py`: delete the moved block and add `from apps.core.pagination import paginate`. In `apps/crm/api.py`: delete the inline `_effective_page_size`/page-size constants block (`:294-340` region) and call `apps.core.pagination.paginate`, keeping the response dict keys identical. CRM raised `HttpError(404, "Invalid page.")` where core raises `Http404` — both surface as a 404 envelope; if a crm test pins the literal message, keep the test's assertion on status only and note the message change in the test docstring.

- [ ] **Step 4: Run the affected suites**

Run: `uv run pytest apps/core/tests/test_pagination.py apps/company apps/crm -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add apps/core/pagination.py apps/core/tests/test_pagination.py apps/company/api.py apps/crm/api.py
git commit -m "One pagination envelope, hoisted to apps/core"
```

---

### Task 2: Model changes — category, parent_entry, updated_at, drop simple-history

**Files:**
- Modify: `apps/process/models/form.py`
- Modify: `apps/process/models/form_entry.py`
- Modify: `apps/process/models/procedure.py`
- Create: `apps/process/migrations/0002_*.py` (generated by makemigrations)
- Create: `apps/process/tests/test_models.py`

**Interfaces:**
- Produces: `Form.Category` and `Procedure.Category` (`models.TextChoices`), `Form.category` / `Procedure.category` (`CharField(max_length=20, choices=..., null=True)`), `FormEntry.parent_entry` (nullable self-FK, `related_name="child_entries"`, SET_NULL), `FormEntry.updated_at` (`auto_now=True`). The three models lose their `history` attribute.
- Category values (spec): Form — `safety, training, incident, meeting, register`; Procedure — `safety, jsa, training, reference`.

- [ ] **Step 1: Write the failing test**

`apps/process/tests/test_models.py`:

```python
"""Model-level contracts for the process domain.

Category is stored and exclusive (one home per document); entries link to a
parent entry (a meeting's actions and attendance sign-offs point back at the
minutes entry); simple-history is gone because ProcessEvent is the one audit
implementation.
"""

import pytest

from apps.process.models import Form, FormEntry, Procedure

pytestmark = pytest.mark.django_db


def make_form(**overrides: object) -> Form:
    defaults: dict[str, object] = {
        "document_type": "form",
        "category": Form.Category.SAFETY,
        "title": "Site inspection",
        "form_schema": {"fields": []},
    }
    defaults.update(overrides)
    return Form.objects.create(**defaults)


class TestCategory:
    def test_form_categories_are_the_five_agreed_values(self) -> None:
        assert [choice[0] for choice in Form.Category.choices] == [
            "safety", "training", "incident", "meeting", "register",
        ]

    def test_procedure_categories_are_the_four_agreed_values(self) -> None:
        assert [choice[0] for choice in Procedure.Category.choices] == [
            "safety", "jsa", "training", "reference",
        ]


class TestFormEntryLinks:
    def test_an_entry_can_link_to_a_parent_entry_on_another_form(self) -> None:
        minutes_form = make_form(category=Form.Category.MEETING, title="Meeting minutes")
        actions_form = make_form(category=Form.Category.MEETING, title="Actions")
        minutes = FormEntry.objects.create(
            form=minutes_form, entry_date="2026-08-25", data={}
        )
        action = FormEntry.objects.create(
            form=actions_form, entry_date="2026-08-25", data={}, parent_entry=minutes
        )
        assert list(minutes.child_entries.all()) == [action]

    def test_entries_carry_updated_at(self) -> None:
        entry = FormEntry.objects.create(
            form=make_form(), entry_date="2026-08-25", data={}
        )
        assert entry.updated_at is not None


class TestSimpleHistoryIsGone:
    def test_no_history_manager_on_any_process_model(self) -> None:
        for model in (Form, FormEntry, Procedure):
            assert not hasattr(model, "history")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/process/tests/test_models.py -v`
Expected: FAIL (`Form.Category` does not exist)

- [ ] **Step 3: Edit the three models**

`apps/process/models/form.py`:
- Remove `from simple_history.models import HistoricalRecords` (line 11) and the `history: HistoricalRecords = HistoricalRecords()` attribute (line 66).
- Add inside `class Form`, after the existing `DOCUMENT_TYPES`/`STATUS_CHOICES`:

```python
    class Category(models.TextChoices):
        """One home per document; a form lists in exactly one category."""

        SAFETY = "safety", "Safety"
        TRAINING = "training", "Training"
        INCIDENT = "incident", "Incident"
        MEETING = "meeting", "Meeting"
        REGISTER = "register", "Register"
```

- Add the field beside `document_type`:

```python
    # Fable: null=True at the database because the v1 data restore is data-only
    # into this schema (the dump has no category column); the backfill
    # migration reruns after the restore and the API requires the field, so
    # NULL never survives past provisioning.
    category = models.CharField(max_length=20, choices=Category.choices, null=True)
```

`apps/process/models/procedure.py`: same simple-history removal (import line 10, attribute line 90); same field; its `Category`:

```python
    class Category(models.TextChoices):
        """One home per document; a procedure lists in exactly one category."""

        SAFETY = "safety", "Safety"
        JSA = "jsa", "JSA"
        TRAINING = "training", "Training"
        REFERENCE = "reference", "Reference"
```

`apps/process/models/form_entry.py`: remove the simple-history import (line 11) and attribute (line 74); add after `created_at`:

```python
    updated_at = models.DateTimeField(auto_now=True)
```

and after the `entered_by` FK:

```python
    # Fable: SET_NULL, not CASCADE — an action extracted from a meeting stands
    # on its own as a record; only test cleanup hard-deletes, and orphaning a
    # child there is harmless. NULL parent is the normal unlinked state.
    parent_entry = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_entries",
    )
```

Do NOT remove `simple_history` from `INSTALLED_APPS` or `pyproject.toml` — `apps/accounts/models.py:181` still uses it.

- [ ] **Step 4: Generate the migration and run the tests**

Run: `uv run python manage.py makemigrations process`
Expected: one migration with `AddField` ×4 (category ×2, parent_entry, updated_at) and `DeleteModel` ×3 (`HistoricalForm`, `HistoricalFormEntry`, `HistoricalProcedure`). If makemigrations prompts for a default for `updated_at`, accept `timezone.now`.

Run: `uv run pytest apps/process -v`
Expected: PASS (new tests plus the existing import-command tests)

- [ ] **Step 5: Commit**

```bash
git add apps/process/models/ apps/process/migrations/ apps/process/tests/test_models.py
git commit -m "Process models: stored category, entry parent links, updated_at; simple-history removed"
```

Note: the pre-push migrations check and mypy run on commit; if `mypy` flags the removed import or `code-quality.md` shifts, stage the regenerated artifacts and commit again.

---

### Task 3: Category backfill migration + import-command category

**Files:**
- Create: `apps/process/migrations/0003_backfill_categories.py` (hand-written data migration)
- Modify: `apps/process/management/commands/import_dropbox_hs_documents.py` (`DOC_MAPPING` gains a category; `_import_form`/`_import_procedure` write it)
- Modify: `config/tests/test_data_migration_script.py` (classify the migration)
- Modify: `scripts/ops/migrate_v1_data.sh` (rerun after restore)
- Modify: `apps/process/tests/test_import_dropbox_hs_documents.py` (imports carry category)
- Create: `apps/process/tests/test_backfill_categories.py`

**Interfaces:**
- Produces: every existing Form/Procedure row has a non-null `category`; `DOC_MAPPING` entries become 3-tuples `(document_type, category, tags)`.
- Backfill rule (spec, most-specific-first): forms — `incident` if `"incident" in tags`, else `register` if `document_type == "register"`, else `meeting` if `"meeting" in tags`, else `training` if `"training" in tags`, else `safety`. Procedures — `jsa` if `"jsa" in tags`, else `reference` if `document_type == "reference"`, else `training` if `"training" in tags`, else `safety`.

- [ ] **Step 1: Write the failing backfill test**

`apps/process/tests/test_backfill_categories.py`:

```python
"""The category backfill assigns each document exactly one category from tags.

The rule is most-specific-first, so a doc tagged safety+incident lands in
incident (v1 listed it under both — the double-listing defect this field
exists to remove).
"""

import pytest

from apps.process.migrations.utils_backfill_categories import (
    form_category,
    procedure_category,
)


class TestFormCategory:
    def test_incident_beats_safety(self) -> None:
        assert form_category("form", ["safety", "incident"]) == "incident"

    def test_register_document_type_wins_over_safety_tags(self) -> None:
        assert form_category("register", ["safety", "hazard"]) == "register"

    def test_meeting_then_training_then_safety(self) -> None:
        assert form_category("form", ["meeting"]) == "meeting"
        assert form_category("form", ["training", "refresher"]) == "training"
        assert form_category("form", ["safety", "inspection"]) == "safety"

    def test_untagged_forms_default_to_safety(self) -> None:
        assert form_category("form", []) == "safety"


class TestProcedureCategory:
    def test_jsa_beats_safety(self) -> None:
        assert procedure_category("procedure", ["jsa", "safety"]) == "jsa"

    def test_reference_type_then_training_then_safety(self) -> None:
        assert procedure_category("reference", ["safety", "planning"]) == "reference"
        assert procedure_category("procedure", ["training"]) == "training"
        assert procedure_category("procedure", ["safety", "sop"]) == "safety"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/process/tests/test_backfill_categories.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Write the rule module and the migration**

Create `apps/process/migrations/utils_backfill_categories.py` (a plain module beside the migrations so both the migration and its tests import one implementation; migrations may import helpers that never change meaning — this one is frozen once shipped):

```python
"""Category assignment from v1 tags. Frozen: edits here rewrite history.

Most-specific-first; the fallbacks mirror what the v1 category dicts meant,
minus the overlap (a doc listed once, not twice).
"""


def form_category(document_type: str, tags: list[str]) -> str:
    if "incident" in tags:
        return "incident"
    if document_type == "register":
        return "register"
    if "meeting" in tags:
        return "meeting"
    if "training" in tags:
        return "training"
    return "safety"


def procedure_category(document_type: str, tags: list[str]) -> str:
    if "jsa" in tags:
        return "jsa"
    if document_type == "reference":
        return "reference"
    if "training" in tags:
        return "training"
    return "safety"
```

Create `apps/process/migrations/0003_backfill_categories.py` following the classified-migration idioms of `apps/timesheet/migrations/0004_public_holiday_posts_nowhere.py` (module docstring stating defect and fix; `apps.get_model`; count guard; noop reverse):

```python
"""Assign every existing Form and Procedure its stored category.

v1 categorised by overlapping tag filters, so a document could list twice
and the category URL segment was decorative. The stored field is exclusive;
this backfill derives it from tags most-specific-first. Runs against the
empty database at provision time (finds nothing) and again after the v1
data restore (see scripts/ops/migrate_v1_data.sh), which is when it works.
"""

from typing import Any

from django.db import migrations

from apps.process.migrations.utils_backfill_categories import (
    form_category,
    procedure_category,
)


def backfill_categories(apps: Any, schema_editor: Any) -> None:
    """Set category on every row where it is NULL; refuse to leave any NULL."""
    Form = apps.get_model("process", "Form")
    Procedure = apps.get_model("process", "Procedure")

    for form in Form.objects.filter(category__isnull=True):
        form.category = form_category(form.document_type, list(form.tags))
        form.save(update_fields=["category"])
    for procedure in Procedure.objects.filter(category__isnull=True):
        procedure.category = procedure_category(
            procedure.document_type, list(procedure.tags)
        )
        procedure.save(update_fields=["category"])

    remaining = (
        Form.objects.filter(category__isnull=True).count()
        + Procedure.objects.filter(category__isnull=True).count()
    )
    if remaining:
        raise RuntimeError(f"{remaining} process documents still have no category.")


class Migration(migrations.Migration):
    """Every document gets its one category; NULL is a provisioning-only state."""

    dependencies = [
        ("process", "0002_<generated name from Task 2>"),
    ]

    operations = [
        # Fable: reverse is a noop so the migrate script can unapply/reapply
        # around the data-only restore; re-running forward is idempotent
        # (filters on NULL).
        migrations.RunPython(backfill_categories, migrations.RunPython.noop),
    ]
```

- [ ] **Step 4: Classify the migration**

In `config/tests/test_data_migration_script.py`, add to `DATA_MIGRATIONS_RERUN_AFTER_RESTORE`:

```python
    # Derives the stored category from v1 tags; the rows it fixes arrive with
    # the restore, so the empty-database run finds none.
    ("process", "0003_backfill_categories"),
```

In `scripts/ops/migrate_v1_data.sh`, after the `pg_restore --data-only` line, following the existing unapply/reapply pattern:

```bash
# process/0003 derives each document's stored category from its v1 tags. The
# rows it fixes arrive with the restore; its reverse is a no-op, so replaying
# it here is the same tested code against the rows that now exist.
DB_NAME="$V2_DB" uv run python manage.py migrate process 0002 --no-input
DB_NAME="$V2_DB" uv run python manage.py migrate process 0003 --no-input
```

(Use the real 0002 name generated in Task 2.)

- [ ] **Step 5: Thread category through the import command**

In `apps/process/management/commands/import_dropbox_hs_documents.py`:
- Change `DOC_MAPPING` to `dict[str, tuple[str, str, list[str]]]` — `(document_type, category, tags)`. Derive each row's category by applying the Task 3 rules to its current tags by hand (they are ~100 literal lines; e.g. `"202": ("form", "incident", ["safety", "incident"])`, `"108": ("form", "safety", ["safety", "inspection"])`, `"252": ("form", "training", ["training", "refresher"])`, `"380": ("register", "register", [...])`, `"100": ("procedure", "safety", ["safety", "policy"])`, `"102": ("reference", "reference", ["safety", "planning"])`).
- Update the unpack at `:575` to `doc_type, category, tags = DOC_MAPPING[doc_number]`, thread `category` through `_import_form` and `_import_procedure` (update their `PLR0913` count comments), and add `category=category` to both `objects.create(...)` calls.
- Update `apps/process/tests/test_import_dropbox_hs_documents.py` to assert an imported form and procedure carry the mapped category.

- [ ] **Step 6: Run the suites and the gate**

Run: `uv run pytest apps/process config/tests/test_data_migration_script.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/process/migrations/ apps/process/management/ apps/process/tests/ config/tests/test_data_migration_script.py scripts/ops/migrate_v1_data.sh
git commit -m "Category backfill from v1 tags, classified for the restore; import command writes categories"
```

---

### Task 4: ProcessEvent model + events service

**Files:**
- Create: `apps/process/models/process_event.py`
- Modify: `apps/process/models/__init__.py` (export `ProcessEvent`)
- Create: `apps/process/migrations/0004_processevent.py` (generated)
- Create: `apps/process/services/__init__.py` (empty)
- Create: `apps/process/services/process_events.py`
- Create: `apps/process/tests/test_process_events.py`

**Interfaces:**
- Produces model `ProcessEvent`: `id` UUID PK, `timestamp` (`default=now`), `staff` FK `accounts.Staff` PROTECT (NOT NULL), `event_type` CharField(50), `form` / `form_entry` / `procedure` nullable FKs (CASCADE), `delta_before` / `delta_after` JSONField(null=True, blank=True), `detail` JSONField(default=dict, blank=True), property `description: str`. `Meta.ordering = ["-timestamp"]`.
- Produces service functions (all keyword-only):
  - `record_form_event(*, form: Form, staff: Staff, event_type: str, changes: list[FieldChange], before: dict | None = None, after: dict | None = None) -> ProcessEvent`
  - `record_entry_event(*, entry: FormEntry, staff: Staff, event_type: str, changes: list[FieldChange], before: dict | None = None, after: dict | None = None) -> ProcessEvent`
  - `FieldChange` TypedDict: `{"field_name": str, "old_value": str, "new_value": str}`
  - `json_safe(value: object) -> str | int | float | bool | None` (dates isoformat, Decimal str, scalars passthrough, else str — mirror `_json_safe` at `apps/job/models/job.py:38-48`)
- Event types (spec): `entry_created`, `entry_updated`, `entry_archived`, `form_created`, `form_updated`, `schema_updated`, `form_archived` (procedure types arrive with slice 2).

- [ ] **Step 1: Write the failing test**

`apps/process/tests/test_process_events.py`:

```python
"""ProcessEvent is the domain's one visible audit implementation.

An entry is a formal record ("Ben signed reading this on this date"); edits
are allowed for anyone authenticated, so the event log is the control — it
must say who changed what, when, in words a reader can use.
"""

import pytest

from apps.accounts.models import Staff
from apps.process.models import Form, FormEntry, ProcessEvent
from apps.process.services.process_events import record_entry_event

pytestmark = pytest.mark.django_db


def make_staff() -> Staff:
    return Staff.objects.create_user(
        office_email="auditor@example.com",
        password="s3cret-Pass!",
        first_name="Audrey",
        last_name="Auditor",
    )


def make_entry() -> FormEntry:
    form = Form.objects.create(
        document_type="form",
        category=Form.Category.SAFETY,
        title="Inspection",
        form_schema={"fields": [{"key": "area", "label": "Area", "type": "text"}]},
    )
    return FormEntry.objects.create(form=form, entry_date="2026-08-25", data={"area": "Bay 1"})


class TestRecordEntryEvent:
    def test_writes_one_event_with_deltas_and_changes(self) -> None:
        entry = make_entry()
        event = record_entry_event(
            entry=entry,
            staff=make_staff(),
            event_type="entry_updated",
            changes=[{"field_name": "Area", "old_value": "Bay 1", "new_value": "Bay 2"}],
            before={"data": {"area": "Bay 1"}},
            after={"data": {"area": "Bay 2"}},
        )
        assert ProcessEvent.objects.count() == 1
        assert event.form_entry == entry
        assert event.delta_before == {"data": {"area": "Bay 1"}}
        assert event.description == "Area changed from 'Bay 1' to 'Bay 2'"

    def test_created_event_describes_itself(self) -> None:
        entry = make_entry()
        event = record_entry_event(
            entry=entry, staff=make_staff(), event_type="entry_created", changes=[]
        )
        assert event.description == "Entry created"

    def test_events_cascade_with_their_entry(self) -> None:
        entry = make_entry()
        record_entry_event(
            entry=entry, staff=make_staff(), event_type="entry_created", changes=[]
        )
        entry.delete()
        assert ProcessEvent.objects.count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/process/tests/test_process_events.py -v`
Expected: FAIL (no ProcessEvent)

- [ ] **Step 3: Write the model**

`apps/process/models/process_event.py`:

```python
"""The process domain's append-only audit trail.

Mirrors JobEvent's delta shape (staff, event_type, delta_before/after,
detail.changes, derived description) without the envelope machinery —
checksums, undo and change ids exist for the job screen's optimistic
concurrency, which this domain does not have. Hoisting a shared event
mechanism into apps/core is recorded post-cutover work (see the design doc).
"""

import uuid
from typing import Any, ClassVar

from django.db import models
from django.utils.timezone import now


def _default_descriptor(field_name: str, old: object, new: object) -> str:
    return f"{field_name} changed from '{old}' to '{new}'"


def _render_change(change: dict[str, Any]) -> str:
    return _default_descriptor(
        change.get("field_name", ""), change.get("old_value", ""), change.get("new_value", "")
    )


_EVENT_LABELS: dict[str, str] = {
    "entry_created": "Entry created",
    "entry_archived": "Entry archived",
    "form_created": "Form created",
    "form_archived": "Form archived",
    "schema_updated": "Form schema updated",
}


class ProcessEvent(models.Model):
    """One audit event on a form, entry, or procedure."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(default=now)
    staff = models.ForeignKey("accounts.Staff", on_delete=models.PROTECT)
    event_type = models.CharField(max_length=50)
    form = models.ForeignKey(
        "process.Form", on_delete=models.CASCADE, null=True, blank=True,
        related_name="events",
    )
    form_entry = models.ForeignKey(
        "process.FormEntry", on_delete=models.CASCADE, null=True, blank=True,
        related_name="events",
    )
    procedure = models.ForeignKey(
        "process.Procedure", on_delete=models.CASCADE, null=True, blank=True,
        related_name="events",
    )
    delta_before = models.JSONField(null=True, blank=True)
    delta_after = models.JSONField(null=True, blank=True)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering: ClassVar = ["-timestamp"]

    def __str__(self) -> str:
        return f"{self.event_type} at {self.timestamp:%Y-%m-%d %H:%M}"

    @property
    def description(self) -> str:
        """Human-readable sentence for the history panel."""
        changes = (self.detail or {}).get("changes", [])
        if changes:
            parts = [_render_change(change) for change in changes]
            rendered = ". ".join(part for part in parts if part)
            if rendered:
                return rendered
        label = _EVENT_LABELS.get(self.event_type)
        if label:
            return label
        return f"({self.event_type})"
```

Export from `apps/process/models/__init__.py`.

- [ ] **Step 4: Write the service**

`apps/process/services/process_events.py`:

```python
"""Event writes for the process domain — the one place audit rows are made.

Services call these inside the same transaction as the row write, so an
entry change and its audit event commit or roll back together.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import TypedDict

from apps.accounts.models import Staff
from apps.process.models import Form, FormEntry, ProcessEvent


class FieldChange(TypedDict):
    field_name: str
    old_value: str
    new_value: str


def json_safe(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def record_form_event(
    *,
    form: Form,
    staff: Staff,
    event_type: str,
    changes: list[FieldChange],
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
) -> ProcessEvent:
    return ProcessEvent.objects.create(
        form=form,
        staff=staff,
        event_type=event_type,
        detail={"changes": changes},
        delta_before=before,
        delta_after=after,
    )


def record_entry_event(
    *,
    entry: FormEntry,
    staff: Staff,
    event_type: str,
    changes: list[FieldChange],
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
) -> ProcessEvent:
    return ProcessEvent.objects.create(
        form_entry=entry,
        form=entry.form,
        staff=staff,
        event_type=event_type,
        detail={"changes": changes},
        delta_before=before,
        delta_after=after,
    )
```

- [ ] **Step 5: Generate migration, run tests**

Run: `uv run python manage.py makemigrations process` then `uv run pytest apps/process -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/process/models/ apps/process/migrations/ apps/process/services/ apps/process/tests/test_process_events.py
git commit -m "ProcessEvent: the process domain's audit trail, JobEvent-shaped without the envelope machinery"
```

---

### Task 5: Wire schemas — typed form schema, request/response models

**Files:**
- Create: `apps/process/schemas.py`
- Create: `apps/process/tests/test_schemas.py`

**Interfaces (produced; Tasks 6–8 and the generated TS client consume exactly these):**

```python
FieldType = Literal["text", "textarea", "date", "boolean", "number", "select", "staff", "entry_ref"]
FormCategory = Literal["safety", "training", "incident", "meeting", "register"]

class FormFieldSchema(Schema): ...      # key, label, type, required, options?, source_form?, display_key?
class FormSchemaSpec(Schema): ...       # fields: list[FormFieldSchema]; rejects duplicate keys
class FormCreateIn(Schema): ...         # document_type, category, title, document_number?, tags?, form_schema
class FormUpdateIn(Schema): ...         # all-optional PATCH body (exclude_unset)
class FormOut(Schema): ...              # id, document_type, category, title, document_number, tags, status, form_schema, entry_count, created_at, updated_at
class EntryCreateIn(Schema): ...        # entry_date, data, job?, staff?, parent_entry?
class EntryUpdateIn(Schema): ...        # all-optional PATCH body
class EntryOut(Schema): ...             # id, form, entry_date, staff, staff_name, entered_by, entered_by_name, job, parent_entry, child_count, data, display_data, is_active, created_at, updated_at
class PaginatedEntryList(Schema): ...   # results, count, page, page_size, total_pages
class CategoryOut(Schema): ...          # key, label
class CategoriesOut(Schema): ...        # forms: list[CategoryOut], procedures: list[CategoryOut]
class EntryEventOut(Schema): ...        # id, timestamp, event_type, staff_name, description, changes
```

- [ ] **Step 1: Write the failing test**

`apps/process/tests/test_schemas.py` (schema-structure violations must be 422-shaped, i.e. pydantic `ValidationError`):

```python
"""The form schema is a typed contract, not an opaque JSONField.

v1 stored anything (form_schema=42 persisted); here the request schema
rejects malformed field lists before the database, so invalid structure is
a 422 by construction.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from apps.process.schemas import FormFieldSchema, FormSchemaSpec


def field(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {"key": "area", "label": "Area", "type": "text"}
    base.update(overrides)
    return base


class TestFormFieldSchema:
    def test_plain_field_parses(self) -> None:
        parsed = FormFieldSchema.model_validate(field())
        assert parsed.required is False

    def test_unknown_type_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FormFieldSchema.model_validate(field(type="rating"))

    def test_select_requires_options(self) -> None:
        with pytest.raises(ValidationError):
            FormFieldSchema.model_validate(field(type="select"))

    def test_options_off_select_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FormFieldSchema.model_validate(field(options=["a"]))

    def test_entry_ref_requires_source_form_and_display_key(self) -> None:
        with pytest.raises(ValidationError):
            FormFieldSchema.model_validate(field(type="entry_ref"))
        parsed = FormFieldSchema.model_validate(
            field(type="entry_ref", source_form=str(uuid4()), display_key="name")
        )
        assert parsed.display_key == "name"

    def test_source_form_off_entry_ref_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FormFieldSchema.model_validate(field(source_form=str(uuid4())))

    def test_unknown_keys_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FormFieldSchema.model_validate(field(placeholder="hm"))


class TestFormSchemaSpec:
    def test_duplicate_keys_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FormSchemaSpec.model_validate({"fields": [field(), field()]})

    def test_empty_field_list_is_legal(self) -> None:
        assert FormSchemaSpec.model_validate({"fields": []}).fields == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/process/tests/test_schemas.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Write the schemas**

`apps/process/schemas.py` — the heart of it (docstring conventions per `apps/accounts/schemas.py`; `NonBlankText`, `NullableText`, `omittable` from `apps.core.schemas`):

```python
"""Wire contracts for the process domain.

The form schema is typed here so invalid structure is a 422 at the request
boundary (extra="forbid" everywhere); entry DATA is validated dynamically
against the stored schema in services/entry_validation.py, surfacing as a
transparent 400 (the codebase's convention for post-parse validation).
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, model_validator

from apps.core.schemas import NonBlankText, NullableText, omittable
from apps.process.models import Form, FormEntry

FieldType = Literal[
    "text", "textarea", "date", "boolean", "number", "select", "staff", "entry_ref"
]
FormCategory = Literal["safety", "training", "incident", "meeting", "register"]
FormDocumentType = Literal["form", "register"]
FormStatus = Literal["active", "archived"]


class FormFieldSchema(Schema):
    """One field of a form's entry schema.

    options only on select; source_form + display_key exactly on entry_ref —
    an Asset Register is just another form, and a maintenance record's asset
    field is an entry_ref into it.
    """

    model_config = ConfigDict(extra="forbid")

    key: NonBlankText
    label: NonBlankText
    type: FieldType
    required: bool = False
    options: list[NonBlankText] | None = None
    source_form: UUID | None = None
    display_key: NonBlankText | None = None

    @model_validator(mode="after")
    def _coherent(self) -> "FormFieldSchema":
        if self.type == "select":
            if not self.options:
                raise ValueError(f"Field '{self.key}': a select field needs options.")
        elif self.options is not None:
            raise ValueError(f"Field '{self.key}': options belong only on select fields.")
        if self.type == "entry_ref":
            if self.source_form is None or self.display_key is None:
                raise ValueError(
                    f"Field '{self.key}': an entry_ref field needs source_form and display_key."
                )
        elif self.source_form is not None or self.display_key is not None:
            raise ValueError(
                f"Field '{self.key}': source_form/display_key belong only on entry_ref fields."
            )
        return self


class FormSchemaSpec(Schema):
    """A form's whole entry schema; keys must be unique."""

    model_config = ConfigDict(extra="forbid")

    fields: list[FormFieldSchema]

    @model_validator(mode="after")
    def _unique_keys(self) -> "FormSchemaSpec":
        keys = [field.key for field in self.fields]
        duplicates = {key for key in keys if keys.count(key) > 1}
        if duplicates:
            raise ValueError(f"Duplicate field keys: {sorted(duplicates)}.")
        return self
```

Requests and responses (same file), following the staff-slice shapes:

```python
class FormCreateIn(Schema):
    """POST body. Unknown keys are a 422, not a silent drop."""

    model_config = ConfigDict(extra="forbid")

    document_type: FormDocumentType
    category: FormCategory
    title: NonBlankText
    document_number: NullableText = omittable(None)
    tags: list[NonBlankText] = omittable([])
    form_schema: FormSchemaSpec


class FormUpdateIn(Schema):
    """PATCH body; omission leaves a field alone (exclude_unset)."""

    model_config = ConfigDict(extra="forbid")

    category: FormCategory = omittable("safety")
    title: NonBlankText = omittable("")
    document_number: NullableText = omittable(None)
    tags: list[NonBlankText] = omittable([])
    status: FormStatus = omittable("active")
    form_schema: FormSchemaSpec = omittable(FormSchemaSpec(fields=[]))


class FormOut(Schema):
    """One form, list row and detail alike (the edit dialog reads the row)."""

    id: UUID
    document_type: str
    category: str
    title: str
    document_number: str | None
    tags: list[str]
    status: str
    form_schema: dict[str, object]
    entry_count: int
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_entry_count(obj: Form) -> int:
        # Annotated by the list queryset; fall back to a count for single rows.
        annotated = getattr(obj, "entry_count_annotated", None)
        if annotated is not None:
            return annotated
        return obj.entries.filter(is_active=True).count()
```

Entries (`EntryOut.display_data` carries server-resolved labels for staff/entry_ref values so no client join is needed; `staff_name`/`entered_by_name` resolved via `resolve_*` staticmethods calling `obj.staff.get_display_full_name()` when set; `child_count` from an annotation with the same fallback shape as `entry_count`):

```python
class EntryCreateIn(Schema):
    model_config = ConfigDict(extra="forbid")

    entry_date: datetime.date  # plain `date` — import it
    data: dict[str, object]
    job: UUID | None = omittable(None)
    staff: UUID | None = omittable(None)
    parent_entry: UUID | None = omittable(None)


class EntryUpdateIn(Schema):
    model_config = ConfigDict(extra="forbid")

    entry_date: date = omittable(date(2000, 1, 1))
    data: dict[str, object] = omittable({})
    job: UUID | None = omittable(None)
    staff: UUID | None = omittable(None)
    parent_entry: UUID | None = omittable(None)
```

plus `EntryOut`, `PaginatedEntryList` (five-key envelope exactly as `apps/company/schemas.py:490-497`), `CategoryOut`/`CategoriesOut`, and `EntryEventOut` (`changes: list[dict[str, str]]` from `detail["changes"]`, `staff_name` resolved, `description` from the model property).

Note on `omittable` defaults: they are never observed (every handler reads `model_dump(exclude_unset=True)` / `model_fields_set`), they exist so the field is optional on the wire — same as `StaffUpdateIn`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest apps/process/tests/test_schemas.py -v` — Expected: PASS
Then `uv run mypy apps/process` — Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add apps/process/schemas.py apps/process/tests/test_schemas.py
git commit -m "Process wire contracts: the form schema is typed, invalid structure is a 422"
```

---

### Task 6: Entry-data validation + display resolution service

**Files:**
- Create: `apps/process/services/entry_validation.py`
- Create: `apps/process/tests/test_entry_validation.py`

**Interfaces:**
- Produces:
  - `validate_entry_data(form: Form, data: dict[str, object]) -> None` — raises `ninja.errors.HttpError(400, message)` naming every violation (unknown key; missing required; type mismatch; select value not in options; staff UUID not an existing Staff; entry_ref UUID not an active entry of the field's source form). Messages are one semicolon-joined string, transparent per ADR 0038.
  - `display_data(form: Form, data: dict[str, object]) -> dict[str, str]` — for each `staff`/`entry_ref` field key present in `data`, the human label: staff display name, or the source entry's `data[display_key]` value as str. Missing referents render as the raw UUID string (reads never write, and a read must not 500 on a row an admin hand-deleted).
  - `parse_schema(form: Form) -> FormSchemaSpec` — validates the stored JSON through `FormSchemaSpec`; raises `HttpError(500, ...)` if a stored schema no longer parses (cannot happen through the API; loud if it does).
- Consumes: `FormSchemaSpec` (Task 5).

- [ ] **Step 1: Write the failing test**

`apps/process/tests/test_entry_validation.py`:

```python
"""Entry data is validated against the form's stored schema at write time.

v1 accepted anything into FormEntry.data; every rule here exists so a signed
record means what its form says it means.
"""

from uuid import uuid4

import pytest
from ninja.errors import HttpError

from apps.accounts.models import Staff
from apps.process.models import Form, FormEntry
from apps.process.services.entry_validation import display_data, validate_entry_data

pytestmark = pytest.mark.django_db

SCHEMA = {
    "fields": [
        {"key": "area", "label": "Area", "type": "text", "required": True},
        {"key": "severity", "label": "Severity", "type": "select", "options": ["low", "high"]},
        {"key": "injured", "label": "Injured staff member", "type": "staff"},
        {"key": "count", "label": "Count", "type": "number"},
        {"key": "confirmed", "label": "Confirmed", "type": "boolean"},
        {"key": "when", "label": "When", "type": "date"},
    ]
}


def make_form(schema: dict[str, object] | None = None, **overrides: object) -> Form:
    defaults: dict[str, object] = {
        "document_type": "form",
        "category": Form.Category.INCIDENT,
        "title": "Incident report",
        "form_schema": schema if schema is not None else SCHEMA,
    }
    defaults.update(overrides)
    return Form.objects.create(**defaults)


def make_staff(email: str = "ben@example.com") -> Staff:
    return Staff.objects.create_user(
        office_email=email, password="s3cret-Pass!", first_name="Ben", last_name="Signer"
    )


class TestValidateEntryData:
    def test_valid_data_passes(self) -> None:
        staff = make_staff()
        validate_entry_data(
            make_form(),
            {
                "area": "Bay 1",
                "severity": "low",
                "injured": str(staff.id),
                "count": 3,
                "confirmed": True,
                "when": "2026-08-25",
            },
        )

    def test_unknown_key_is_a_400(self) -> None:
        with pytest.raises(HttpError) as caught:
            validate_entry_data(make_form(), {"area": "x", "mystery": 1})
        assert caught.value.status_code == 400
        assert "mystery" in str(caught.value)

    def test_missing_required_field_is_a_400(self) -> None:
        with pytest.raises(HttpError):
            validate_entry_data(make_form(), {})

    def test_select_value_must_be_an_option(self) -> None:
        with pytest.raises(HttpError):
            validate_entry_data(make_form(), {"area": "x", "severity": "medium"})

    def test_number_and_boolean_and_date_types_are_enforced(self) -> None:
        with pytest.raises(HttpError):
            validate_entry_data(make_form(), {"area": "x", "count": "three"})
        with pytest.raises(HttpError):
            validate_entry_data(make_form(), {"area": "x", "confirmed": "yes"})
        with pytest.raises(HttpError):
            validate_entry_data(make_form(), {"area": "x", "when": "25/08/2026"})

    def test_unknown_staff_uuid_is_a_400(self) -> None:
        with pytest.raises(HttpError):
            validate_entry_data(make_form(), {"area": "x", "injured": str(uuid4())})

    def test_entry_ref_must_point_at_an_active_entry_of_the_source_form(self) -> None:
        register = make_form(
            schema={"fields": [{"key": "name", "label": "Name", "type": "text"}]},
            category=Form.Category.REGISTER,
            document_type="register",
            title="Asset register",
        )
        asset = FormEntry.objects.create(
            form=register, entry_date="2026-08-25", data={"name": "Press brake"}
        )
        maintenance = make_form(
            schema={
                "fields": [
                    {
                        "key": "asset",
                        "label": "Asset",
                        "type": "entry_ref",
                        "source_form": str(register.id),
                        "display_key": "name",
                    }
                ]
            },
            title="Maintenance record",
        )
        validate_entry_data(maintenance, {"asset": str(asset.id)})
        other_entry = FormEntry.objects.create(
            form=maintenance, entry_date="2026-08-25", data={}
        )
        with pytest.raises(HttpError):
            validate_entry_data(maintenance, {"asset": str(other_entry.id)})


class TestDisplayData:
    def test_staff_and_entry_ref_values_resolve_to_names(self) -> None:
        staff = make_staff()
        form = make_form()
        resolved = display_data(form, {"area": "Bay 1", "injured": str(staff.id)})
        assert resolved == {"injured": staff.get_display_full_name()}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/process/tests/test_entry_validation.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement**

`apps/process/services/entry_validation.py` — guard-clause shape, collect all problems then raise once:

```python
"""Entry data validated against its form's stored schema, at write time.

Raises transparent 400s (the post-parse validation convention); the schema
STRUCTURE was already a 422 at form-write time via FormSchemaSpec.
"""

from datetime import date
from uuid import UUID

from ninja.errors import HttpError

from apps.accounts.models import Staff
from apps.process.models import Form, FormEntry
from apps.process.schemas import FormFieldSchema, FormSchemaSpec


def parse_schema(form: Form) -> FormSchemaSpec:
    """The stored schema, re-validated. Loud on corruption: every write path
    validates, so an unparseable stored schema is data damage, not input."""
    try:
        return FormSchemaSpec.model_validate(form.form_schema)
    except ValueError as exc:
        raise HttpError(
            500, f"Stored schema for form '{form.title}' is invalid: {exc}"
        ) from exc


def _check_value(field: FormFieldSchema, value: object, problems: list[str]) -> None:
    if field.type in ("text", "textarea"):
        if not isinstance(value, str):
            problems.append(f"'{field.key}' must be text.")
    elif field.type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(f"'{field.key}' must be a number.")
    elif field.type == "boolean":
        if not isinstance(value, bool):
            problems.append(f"'{field.key}' must be true or false.")
    elif field.type == "date":
        if not isinstance(value, str):
            problems.append(f"'{field.key}' must be an ISO date string.")
            return
        try:
            date.fromisoformat(value)
        except ValueError:
            problems.append(f"'{field.key}' must be an ISO date (YYYY-MM-DD).")
    elif field.type == "select":
        if value not in (field.options or []):
            problems.append(f"'{field.key}' must be one of {field.options}.")
    elif field.type == "staff":
        staff_id = _as_uuid(field.key, value, problems)
        if staff_id is not None and not Staff.objects.filter(pk=staff_id).exists():
            problems.append(f"'{field.key}' does not name a known staff member.")
    elif field.type == "entry_ref":
        entry_id = _as_uuid(field.key, value, problems)
        if entry_id is not None and not FormEntry.objects.filter(
            pk=entry_id, form_id=field.source_form, is_active=True
        ).exists():
            problems.append(
                f"'{field.key}' does not name an active entry of its source form."
            )
    else:  # pragma: no cover - FieldType is a closed Literal
        raise AssertionError(f"Unhandled field type {field.type}")


def _as_uuid(key: str, value: object, problems: list[str]) -> UUID | None:
    if not isinstance(value, str):
        problems.append(f"'{key}' must be an id string.")
        return None
    try:
        return UUID(value)
    except ValueError:
        problems.append(f"'{key}' must be an id string.")
        return None


def validate_entry_data(form: Form, data: dict[str, object]) -> None:
    """Every violation reported at once — a fixable 400, not a guessing game."""
    spec = parse_schema(form)
    by_key = {field.key: field for field in spec.fields}
    problems: list[str] = []

    for key in data:
        if key not in by_key:
            problems.append(f"'{key}' is not a field of this form.")
    for field in spec.fields:
        if field.required and (key_missing := field.key not in data or data[field.key] in ("", None)):
            del key_missing  # explicit: required means present and non-empty
            problems.append(f"'{field.key}' is required.")
            continue
        if field.key in data and data[field.key] is not None:
            _check_value(field, data[field.key], problems)

    if problems:
        raise HttpError(400, " ".join(problems))
```

(The executor should simplify the `required` guard to plain `if field.required and (field.key not in data or data[field.key] in ("", None)):` — no walrus; write it that way directly.)

`display_data` in the same module:

```python
def display_data(form: Form, data: dict[str, object]) -> dict[str, str]:
    """Human labels for reference values, resolved server-side so tables
    never show a UUID. A missing referent renders as the raw id — reads must
    not 500 on rows removed outside the app."""
    spec = parse_schema(form)
    resolved: dict[str, str] = {}
    for field in spec.fields:
        value = data.get(field.key)
        if not isinstance(value, str) or value == "":
            continue
        if field.type == "staff":
            staff = Staff.objects.filter(pk=value).first() if _is_uuid(value) else None
            resolved[field.key] = staff.get_display_full_name() if staff else value
        elif field.type == "entry_ref":
            source = (
                FormEntry.objects.filter(pk=value).first() if _is_uuid(value) else None
            )
            if source is None:
                resolved[field.key] = value
            else:
                label = source.data.get(field.display_key or "")
                resolved[field.key] = str(label) if label not in (None, "") else value
    return resolved


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest apps/process/tests/test_entry_validation.py -v` — Expected: PASS. Then `uv run mypy apps/process`.

- [ ] **Step 5: Commit**

```bash
git add apps/process/services/entry_validation.py apps/process/tests/test_entry_validation.py
git commit -m "Entry data validated against the stored schema; reference values resolve to display names"
```

---

### Task 7: Forms + categories API

**Files:**
- Create: `apps/process/api.py`
- Create: `apps/process/tests/urls.py`
- Create: `apps/process/tests/test_forms_api.py`
- Modify: `config/api.py` (mount the router)

**Interfaces:**
- Produces these operations (paths under `/api/process/`):
  - `GET  /categories/` → `process_categories_retrieve` → `CategoriesOut` (auth: any)
  - `GET  /forms/` → `process_forms_list` → `list[FormOut]`; query `category: FormCategory | None`, `q: str = ""`, `status: FormStatus | None` (default: archived hidden) (auth: any)
  - `POST /forms/` → `process_forms_create` → 201 `FormOut` (auth: office)
  - `GET  /forms/{uuid:form_id}/` → `process_forms_retrieve` → `FormOut` (auth: any)
  - `PATCH /forms/{uuid:form_id}/` → `process_forms_partial_update` → `FormOut` (auth: office; archive = `{"status": "archived"}`)
- Events written: `form_created`; on PATCH one `form_updated` (or `schema_updated` when `form_schema` is among the changed fields; `form_archived` when status flips to archived). Field-change list built from the supplied fields.
- Auth idiom: module-level `auth = CookieJWTAuth()` and `office_auth = OfficeStaffCookieJWTAuth()` from `apps.core.auth`, per `apps/company/api.py:128-137`.
- `request.user` inside an authenticated handler is the `Staff` row (AUTH_USER_MODEL); use it as the event's staff.

- [ ] **Step 1: Write the test URLconf**

`apps/process/tests/urls.py` — copy `apps/accounts/tests/urls.py` verbatim, replacing the import with `from apps.process.api import router`, namespace `"process-tests"`, prefix `"/process/"`.

- [ ] **Step 2: Write the failing tests**

`apps/process/tests/test_forms_api.py` — same fixture idiom as `apps/accounts/tests/test_staff_admin_api.py` (module-level `pytestmark = [pytest.mark.django_db, pytest.mark.urls("apps.process.tests.urls")]`, `make_staff`/`client_for` helpers via `apps.company.tests.conftest.authenticate`, or the root conftest's `api`/`superuser_api` fixtures where they fit):

```python
"""API tests for forms and categories.

Reads are any-staff (regular staff exist in this domain to sign); form
writes are office staff. Archive replaces delete — a form's audit trail
cannot vanish with the form.
"""

# ... imports and helpers per the idiom above ...

VALID_SCHEMA = {"fields": [{"key": "area", "label": "Area", "type": "text", "required": True}]}
CREATE_PAYLOAD = {
    "document_type": "form",
    "category": "incident",
    "title": "Incident report",
    "form_schema": VALID_SCHEMA,
}


class TestAuth:
    def test_anonymous_cannot_list(self) -> None: ...          # 401
    def test_any_staff_can_list(self) -> None: ...             # 200 via non-office staff client
    def test_non_office_staff_cannot_create(self) -> None: ... # 403
    def test_non_office_staff_cannot_update(self) -> None: ... # 403


class TestCategories:
    def test_returns_both_choice_lists_with_labels(self) -> None:
        # GET /api/process/categories/ == 200; body["forms"] includes
        # {"key": "incident", "label": "Incident"}; body["procedures"] includes
        # {"key": "jsa", "label": "JSA"}
        ...


class TestCreate:
    def test_office_staff_creates_a_form_and_an_event(self) -> None:
        # 201; Form row exists; ProcessEvent(event_type="form_created") exists
        ...
    def test_blank_title_is_a_422(self) -> None: ...
    def test_unknown_category_is_a_422(self) -> None: ...
    def test_malformed_schema_is_a_422(self) -> None:
        # form_schema={"fields": [{"key": "a", "label": "A", "type": "rating"}]}
        ...
    def test_entry_ref_source_form_must_exist(self) -> None:
        # structurally valid schema whose source_form UUID matches no Form -> 400
        ...
    def test_blank_document_number_is_a_422(self) -> None: ...


class TestList:
    def test_filters_by_category(self) -> None: ...
    def test_archived_hidden_by_default_and_reachable_by_status_filter(self) -> None: ...
    def test_q_matches_title_case_insensitively(self) -> None: ...
    def test_rows_carry_entry_count(self) -> None: ...


class TestPartialUpdate:
    def test_schema_edit_writes_a_schema_updated_event(self) -> None: ...
    def test_archive_via_status_writes_form_archived(self) -> None: ...
    def test_no_destroy_route_exists(self) -> None:
        # DELETE /api/process/forms/{id}/ -> 405
        ...
```

Write every test body in full (the elided bodies above each become 3–8 lines following the shown idioms — `client.post(URL, data={...}, content_type="application/json")`, status asserts, `Model.objects.get(...)` asserts).

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest apps/process/tests/test_forms_api.py -v`
Expected: FAIL (no `apps.process.api`)

- [ ] **Step 4: Implement the router**

`apps/process/api.py` — module docstring listing every path → operationId → auth (the contract-listing convention of `apps/accounts/api.py:1-30`), then:

```python
logger = logging.getLogger(__name__)

router = Router(tags=["process"])
auth = CookieJWTAuth()
office_auth = OfficeStaffCookieJWTAuth()
```

Categories:

```python
@router.get(
    "/categories/",
    auth=auth,
    operation_id="process_categories_retrieve",
    response=CategoriesOut,
    summary="Form and procedure category lists",
)
def process_categories_retrieve(request: HttpRequest) -> dict[str, object]:
    return {
        "forms": [{"key": key, "label": label} for key, label in Form.Category.choices],
        "procedures": [
            {"key": key, "label": label} for key, label in Procedure.Category.choices
        ],
    }
```

List (annotate `entry_count_annotated=Count("entries", filter=Q(entries__is_active=True))`; default `status` filter excludes archived unless the query names it). Create/patch delegate to a small `apps/process/services/forms_service.py`? No — keep the handlers in `api.py` (they are short) but the **cross-field rule** (entry_ref `source_form` must exist) and event writes go through module-level helpers in `api.py` only if under ~30 lines; otherwise create `apps/process/services/forms_service.py` with `create_form(*, staff, payload) -> Form` and `update_form(*, staff, form, payload) -> Form`. Prefer the service module — Task 8 needs the same shape for entries. Both wrap row write + event write in one `transaction.atomic()`:

```python
def create_form(*, staff: Staff, payload: FormCreateIn) -> Form:
    _require_source_forms_exist(payload.form_schema)
    with transaction.atomic():
        form = Form.objects.create(
            document_type=payload.document_type,
            category=payload.category,
            title=payload.title,
            document_number=payload.document_number,
            tags=list(payload.tags),
            form_schema=payload.form_schema.model_dump(mode="json", exclude_none=True),
            status="active",
        )
        record_form_event(
            form=form, staff=staff, event_type="form_created", changes=[]
        )
    return form


def _require_source_forms_exist(schema: FormSchemaSpec) -> None:
    wanted = {f.source_form for f in schema.fields if f.source_form is not None}
    found = set(Form.objects.filter(pk__in=wanted).values_list("pk", flat=True))
    missing = wanted - found
    if missing:
        raise HttpError(400, f"entry_ref source form(s) not found: {sorted(map(str, missing))}.")
```

`update_form` mirrors `accounts_staff_partial_update`: `supplied = payload.model_dump(exclude_unset=True)`, apply, `full_clean()` → `HttpError(400, "; ".join(exc.messages))`, build a `FieldChange` list from supplied keys (labels are the field names title-cased; old/new via `json_safe`), pick the event type (`form_archived` if status became archived, `schema_updated` if `form_schema` in supplied, else `form_updated`), one event per PATCH.

Mount in `config/api.py` (alphabetical): `from apps.process.api import router as process_router` and `api.add_router("/process/", process_router)`.

- [ ] **Step 5: Run tests until green**

Run: `uv run pytest apps/process -v && uv run mypy apps/process config`
Expected: PASS / clean.

- [ ] **Step 6: Commit**

```bash
git add apps/process/api.py apps/process/services/forms_service.py apps/process/tests/ config/api.py
git commit -m "Forms and categories API: office-staff writes, any-staff reads, archive-only"
```

The schema-export and status-table hooks will regenerate `frontend/schema.v2.yml`, the status table and possibly `docs/code-quality.md` — stage those regenerated files and include them in this commit (re-run `git commit` after `git add`).

---

### Task 8: Entries API — CRUD, history, links

**Files:**
- Create: `apps/process/services/entries_service.py`
- Modify: `apps/process/api.py` (entry operations)
- Create: `apps/process/tests/test_entries_api.py`

**Interfaces:**
- Operations:
  - `GET  /forms/{uuid:form_id}/entries/` → `process_forms_entries_list` → `PaginatedEntryList`; query `page`, `page_size` (auth: any). Active entries only, `select_related("staff", "entered_by")`, annotated `child_count`.
  - `POST /forms/{uuid:form_id}/entries/` → `process_forms_entries_create` → 201 `EntryOut` (auth: any; `entered_by` stamped from `request.user`; validates data per Task 6; writes `entry_created`).
  - `GET  /entries/` → `process_entries_list` → `PaginatedEntryList`; query `parent: UUID | None`, `staff: UUID | None`, `job: UUID | None`, `page`, `page_size` (auth: any). Cross-form — this is how a meeting entry lists its actions.
  - `PATCH /entries/{uuid:entry_id}/` → `process_entries_partial_update` → `EntryOut` (auth: any; validates merged data; writes `entry_updated` with per-field changes using schema labels and display-resolved values).
  - `DELETE /entries/{uuid:entry_id}/` → `process_entries_destroy` → 204 (auth: any; **soft** — sets `is_active=False`, writes `entry_archived`).
  - `GET  /entries/{uuid:entry_id}/history/` → `process_entries_history_list` → `list[EntryEventOut]` newest-first (auth: any).
- Consumes: `paginate` (Task 1), `validate_entry_data`/`display_data` (Task 6), `record_entry_event`/`json_safe` (Task 4), schemas (Task 5).
- Service functions: `create_entry(*, staff, form, payload) -> FormEntry`, `update_entry(*, staff, entry, payload) -> FormEntry`, `archive_entry(*, staff, entry) -> None`. `parent_entry`/`staff`/`job` UUIDs resolve via `get_object_or_404`-style lookups converted to `HttpError(400, ...)` naming the missing referent (a bad reference in a body is the caller's error, not a 404 of the route).

- [ ] **Step 1: Write the failing tests**

`apps/process/tests/test_entries_api.py`, classes and key behaviours (write all bodies in full):

```python
class TestAuth:
    def test_anonymous_cannot_list_or_create(self) -> None: ...   # 401 both
    def test_regular_staff_can_create_edit_and_archive(self) -> None:
        """The domain's point: regular staff sign forms; the audit trail is
        the control, not a permission gate."""
        ...

class TestCreate:
    def test_creates_entry_stamps_entered_by_and_writes_event(self) -> None: ...
    def test_invalid_data_is_a_transparent_400(self) -> None:
        # unknown key -> 400, message names the key
        ...
    def test_staff_defaults_are_not_invented(self) -> None:
        # omitted staff stays NULL — the API never guesses who an entry is about
        ...
    def test_parent_entry_links_across_forms(self) -> None: ...
    def test_unknown_parent_entry_is_a_400(self) -> None: ...

class TestList:
    def test_paginated_envelope_with_page_size_50_default(self) -> None: ...
    def test_only_active_entries_listed(self) -> None: ...
    def test_flat_list_filters_by_parent(self) -> None: ...
    def test_rows_resolve_display_data_for_staff_fields(self) -> None: ...

class TestUpdate:
    def test_edit_writes_entry_updated_with_field_labels(self) -> None:
        # PATCH data {"area": "Bay 2"}; event.description mentions "Area" and both values
        ...
    def test_merged_data_is_validated(self) -> None:
        # PATCH with a key not in schema -> 400, entry unchanged, no event
        ...

class TestArchive:
    def test_delete_is_soft_and_audited(self) -> None:
        # DELETE -> 204; row is_active=False; entry_archived event exists
        ...

class TestHistory:
    def test_history_lists_events_newest_first_with_staff_names(self) -> None: ...
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest apps/process/tests/test_entries_api.py -v`
Expected: FAIL (404s — routes missing)

- [ ] **Step 3: Implement the service**

`apps/process/services/entries_service.py`. The update path's change list — the part worth showing whole:

```python
def _entry_changes(
    form: Form, before: dict[str, object], after: dict[str, object]
) -> list[FieldChange]:
    """Per-field changes with the schema's labels and display-resolved values,
    so the history panel reads 'Injured staff member changed from Ben to Ryan',
    never a UUID."""
    spec = parse_schema(form)
    labels = {field.key: field.label for field in spec.fields}
    before_display = display_data(form, before)
    after_display = display_data(form, after)
    changes: list[FieldChange] = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        changes.append(
            {
                "field_name": labels.get(key, key),
                "old_value": str(before_display.get(key, json_safe(old))),
                "new_value": str(after_display.get(key, json_safe(new))),
            }
        )
    return changes
```

`update_entry` merges (`merged = {**entry.data, **supplied_data}` when `data` supplied — the PATCH body's `data` is the full new data dict, not a partial merge; document that in the schema docstring: "data, when sent, replaces the entry's data whole — the entry form always submits every field"), validates via `validate_entry_data(entry.form, new_data)`, computes changes for `entry_date`/`staff`/`job`/`parent_entry` (label-cased, display-resolved for staff) plus `_entry_changes` for data, writes row + `entry_updated` event in one `transaction.atomic()`. `create_entry` validates then writes row + `entry_created`. `archive_entry` flips `is_active`, writes `entry_archived`.

- [ ] **Step 4: Implement the endpoints**

In `apps/process/api.py`, using `paginate` and returning the five-key dict exactly as `apps/company/api.py:847-866` does; `EntryOut` rows get `display_data` attached by resolving per row (`display_data(entry.form, entry.data)` — the list endpoint prefetches `form`).

- [ ] **Step 5: Run until green**

Run: `uv run pytest apps/process -v && uv run mypy apps/process`
Expected: PASS / clean

- [ ] **Step 6: Commit**

```bash
git add apps/process/api.py apps/process/services/entries_service.py apps/process/tests/test_entries_api.py
git commit -m "Entries API: any-staff signing, audited edits, soft delete, parent links, history"
```

(Again include the hook-regenerated schema/status artifacts.)

---

### Task 9: e2e_cleanup sweeps process rows

**Files:**
- Modify: `apps/diagnostics/management/commands/e2e_cleanup.py`
- Modify: `apps/diagnostics/tests/test_e2e_cleanup.py`

**Interfaces:**
- Consumes `TEST_DATA_PREFIX` from `apps/core/test_data.py`. Sweeps: `FormEntry.objects.filter(form__title__startswith=TEST_DATA_PREFIX)` then `Form.objects.filter(title__startswith=TEST_DATA_PREFIX)` then `Procedure.objects.filter(title__startswith=TEST_DATA_PREFIX)`. ProcessEvent rows cascade with forms/entries.

- [ ] **Step 1: Write the failing test**

Add to `apps/diagnostics/tests/test_e2e_cleanup.py` (matching its existing test style — read the file first):

```python
def test_sweeps_test_prefixed_process_documents(self) -> None:
    """v1's scroll spec leaked one permanent form per run into the incident
    list; the sweep is what makes the ported spec residue-free."""
    form = Form.objects.create(
        document_type="form",
        category=Form.Category.INCIDENT,
        title="[TEST] Tall Incident Form",
        form_schema={"fields": []},
    )
    FormEntry.objects.create(form=form, entry_date="2026-08-25", data={})
    keeper = Form.objects.create(
        document_type="form",
        category=Form.Category.SAFETY,
        title="Real form",
        form_schema={"fields": []},
    )
    call_command("e2e_cleanup", "--confirm")
    assert not Form.objects.filter(pk=form.pk).exists()
    assert not FormEntry.objects.exists()
    assert Form.objects.filter(pk=keeper.pk).exists()
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest apps/diagnostics -v`, expected FAIL.

- [ ] **Step 3: Extend the command** — imports at top, querysets in `handle`, `_report_queryset("E2E process forms", test_forms, "title")` etc., counts added to `total`, `_delete_queryset` calls inside the atomic block in order: entries → forms → procedures.

- [ ] **Step 4: Run** — `uv run pytest apps/diagnostics -v`, expected PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/diagnostics/
git commit -m "e2e_cleanup sweeps [TEST] process forms, entries and procedures"
```

---

### Task 10: Operations bookkeeping + generated client + api boundary

**Files:**
- Modify: `scripts/v1-frontend-operations.yml`
- Modify: `frontend/src/api/index.ts`
- Regenerated by hooks: `frontend/schema.v2.yml`, `frontend/src/api/generated/*`, `docs/rewrite-status.md` status table (via `status_table.py`)

**Interfaces:** none new — this task makes the ledger and client current.

- [ ] **Step 1: Record renames and drops**

In `scripts/v1-frontend-operations.yml` (study `:571-630` for exact list formats):
- `renamed:` — `process_forms_update: process_forms_partial_update` and `process_forms_entries_update: process_entries_partial_update` (PUT became PATCH; entries detail moved to the flat `/entries/` path).
- `dropped:` with `>-` reasons:
  - `process_forms_destroy` — archive replaces delete; a form's audit trail cannot vanish with the form (owner ruling, design doc 2026-08-25).
  - `process_forms_fill_create` — fill is entry-create; one operation serves both the entries page and the Fill dialog.
- Leave the procedure operations untouched — they are slice 2/3 work and still count as unported.

- [ ] **Step 2: Regenerate and verify the derived counts**

Run: `uv run python -m scripts.checks.export_openapi && uv run python -m scripts.checks.status_table`
Expected: the status table's "Backend operations still to port" drops by 10 (8 shipped ids + 2 dropped); `status_table.py` exits clean. If it flags an inconsistency, fix the yml — never the script.

- [ ] **Step 3: Regenerate the client and add the api/index.ts block**

Run: `cd frontend && npm run gen:api`

Add to `frontend/src/api/index.ts` (alphabetical position, format per the Purchasing block at `:181-200`):

```ts
// Process documents (forms list/create/edit, entries with audit history,
// categories; procedures arrive with their slice)
export {
  processCategoriesRetrieveOptions,
  processFormsCreateMutation,
  processFormsListOptions,
  processFormsListQueryKey,
  processFormsPartialUpdateMutation,
  processFormsRetrieveOptions,
  processFormsEntriesCreateMutation,
  processFormsEntriesListOptions,
  processFormsEntriesListQueryKey,
  processEntriesListOptions,
  processEntriesListQueryKey,
  processEntriesPartialUpdateMutation,
  processEntriesDestroyMutation,
  processEntriesHistoryListOptions,
} from './generated/@tanstack/react-query.gen'
export type {
  CategoriesOut,
  EntryEventOut,
  EntryOut,
  FormOut,
  PaginatedEntryList,
} from './generated/types.gen'
```

(Exact export names come from the generated file — verify with grep after gen:api and correct any that differ.)

- [ ] **Step 4: Verify** — `cd frontend && npm run type-check && node ../scripts/check-api-boundary.mjs` (or however the boundary check is invoked in package.json — find and run its script entry). Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add scripts/v1-frontend-operations.yml frontend/schema.v2.yml frontend/src/api/ docs/
git commit -m "Process operations on the wire: ledger renames and drops recorded, client regenerated"
```

---

### Task 11: Frontend — forms list page, dialog, routes, navbar

**Files:**
- Create: `frontend/src/features/process/ProcessFormsPage.tsx`
- Create: `frontend/src/features/process/FormDialog.tsx`
- Create: `frontend/src/features/process/index.ts` (barrel)
- Create: `frontend/src/routes/_authed/process-documents/forms/$category/index.tsx`
- Create: `frontend/src/routes/_authed/process-documents/forms/$category/$formId.tsx` (route only; page arrives Task 12 — component stub renders the Task 12 page)
- Modify: `frontend/src/features/shell/AppNavbar.tsx` (+ its test)
- Create: `frontend/src/features/process/ProcessFormsPage.test.tsx`

**Interfaces:**
- `ProcessFormsPage({ category }: { category: string })` — list of forms in the category.
- `FormDialog({ open, onOpenChange, form }: { open: boolean; onOpenChange: (o: boolean) => void; form: FormOut | null })` — create (`form === null`) or edit.
- Automation ids: `ProcessFormsPage-root`, `-search`, `-new-form`, `-table`, `-row-${id}`, `-edit-${id}`; `FormDialog-title`, `-document-number`, `-category`, `-document-type`, `-tags`, `-schema`, `-schema-error`, `-preview`, `-validation`, `-cancel`, `-submit`.

- [ ] **Step 1: Write the failing component test**

`ProcessFormsPage.test.tsx` with the house idioms (`renderWithProviders`, `autoId`/`queryAutoId`, msw or the repo's query-mocking helper — read `StaffAdminPage.test.tsx` first and copy its mocking approach exactly): renders rows from a mocked forms list; archived rows absent by default; clicking a row navigates to the entries route; `New Form` opens the dialog.

- [ ] **Step 2: Run to verify failure** — `cd frontend && npx vitest run src/features/process` — FAIL (module missing).

- [ ] **Step 3: Build the page**

`ProcessFormsPage.tsx` follows `StockPage` + `StaffAdminPage` jointly:
- `useQuery(processFormsListOptions({ query: { category } }))`, client-side search filter over `title`/`document_number` via `useDebouncedValue` (forms are ~30 rows; no server search round-trip — comment the rejected alternative), status toggle (`Show archived` checkbox adds `status: 'archived'` query).
- `ListTable` with columns Title, Doc #, Tags, Entries, Updated; row click navigates to `/process-documents/forms/$category/$formId`; per-row **Fill** button (any staff — opens the Task 12 `EntryForm` in a dialog for that form, the same component the entries page uses; in THIS task render a disabled placeholder button wired up in Task 12) and per-row Edit button (office-only: hide for non-office users via the shell's user query like AppNavbar does, with the gate comment naming `OfficeStaffCookieJWTAuth`; the API rejects regardless).
- Errors already surface through `ListTable`'s error state; mutations toast via `apiErrorMessage`.

`FormDialog.tsx` follows `StaffFormDialog` (controlled `Drafts`, `snapshot()`, `localProblem()`, dirty-only PATCH via `buildPatch`, `textOrNull` for `document_number`, `requireCategory` closed-union helper). The schema editor:

```tsx
// Drafts.schemaText holds the JSON source; parsed live for the preview.
const parsedSchema = useMemo(() => {
  try {
    const value: unknown = JSON.parse(drafts.schemaText)
    return { ok: true as const, value }
  } catch (error) {
    return { ok: false as const, message: error instanceof Error ? error.message : 'Invalid JSON' }
  }
}, [drafts.schemaText])
```

- textarea per the augmented-textarea precedent (`SettingsFieldInput.tsx:82-124`): `aria-invalid={!parsedSchema.ok}`, sibling `<p className="text-xs text-red-700" data-automation-id="FormDialog-schema-error">` with the parse message.
- Live preview pane (`data-automation-id="FormDialog-preview"`) renders the Task 12 `EntryForm` component in a `readOnly`-ish mode — to avoid a forward dependency, in THIS task render a simple field list preview (label + type badges per parsed field); Task 12 swaps it for the real `EntryForm` once that exists. Edit mode seeds `schemaText` from `JSON.stringify(form.form_schema, null, 2)` — the v1 defect (schema never loaded, never sent) is the thing this dialog exists to fix; say so in a comment.
- `localProblem()` refuses submit while `!parsedSchema.ok`; the server's 422 remains the authority on structure.
- Tags: one text input, comma-separated, split/trimmed on save.

Routes: the two files per the idiom (7-line forms). Navbar: add before the Admin menu:

```tsx
        {/* Any-staff: the process read endpoints use CookieJWTAuth — regular
            staff sign forms, so the menu is not office-gated. */}
        <NavMenu label="Forms" automationId="AppNavbar-forms-menu">
          <NavMenuLink to="/process-documents/forms/$category" params={{ category: 'safety' }} automationId="AppNavbar-forms-safety">
            Safety
          </NavMenuLink>
          {/* ... training, incident, meeting, register ... */}
        </NavMenu>
```

(If `NavMenuLink` does not accept `params`, extend it the way `Link` composes — check its implementation at `AppNavbar.tsx:218-236` first.) Add an `AppNavbar.test.tsx` case: forms menu visible for non-office staff.

- [ ] **Step 4: Run until green** — `cd frontend && npx vitest run src/features/process src/features/shell && npm run type-check` — PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/process/ frontend/src/routes/_authed/process-documents/ frontend/src/features/shell/
git commit -m "Forms list page, create/edit dialog with a working schema editor, navbar Forms menu"
```

---

### Task 12: Frontend — entries page, schema-driven entry form, history, links

**Files:**
- Create: `frontend/src/features/process/FormEntriesPage.tsx`
- Create: `frontend/src/features/process/EntryForm.tsx`
- Create: `frontend/src/features/process/EntriesTable.tsx`
- Create: `frontend/src/features/process/EntryHistoryDialog.tsx`
- Create: `frontend/src/features/process/LinkedEntriesDialog.tsx`
- Modify: `frontend/src/features/process/FormDialog.tsx` (preview now renders `EntryForm` disabled)
- Modify: `frontend/src/features/process/index.ts`
- Create: `frontend/src/features/process/EntryForm.test.tsx`, `FormEntriesPage.test.tsx`

**Interfaces:**
- `FormEntriesPage({ category, formId }: { category: string; formId: string })`.
- `EntryForm({ schema, initial, staffOptions, onSubmit, submitting, automationIdPrefix, disabled? })` — the ONE schema-driven entry component (entries-page card, edit dialog, the forms-list Fill dialog, and FormDialog preview all render it). `schema` is the parsed field list from `FormOut.form_schema`; `staffOptions: { id: string; name: string }[]`. Above the schema fields it renders the two top-level pickers: the staff picker (defaults to the signed-in user — "sign for myself") and an optional job picker using the shared `JobPicker` from `features/shared/JobPicker.tsx` (one job-picker implementation exists in this repo by hard-won rule; source its options from whatever jobs query the timesheet entry page feeds JobPicker with — read that call site and reuse it). Wire up the Task 11 Fill button to open `EntryForm` in a dialog.
- Automation ids the E2E specs assert: `FormEntries-title`, `FormEntries-entries-count` (**exact ids — the ported spec uses them**), plus `FormEntries-add-entry`, `EntryForm-field-${key}`, `EntryForm-entry-date`, `EntryForm-staff`, `EntryForm-submit`, `EntriesTable-row-${id}`, `-edit-${id}`, `-history-${id}`, `-archive-${id}`, `-links-${id}`.

- [ ] **Step 1: Write the failing EntryForm test**

`EntryForm.test.tsx`: renders one input per schema field with the right control (`text`→input, `textarea`→textarea, `date`→`input[type=date]`, `boolean`→checkbox, `number`→`input[type=number]`, `select`→Select with options, `staff`→Select over staffOptions, `entry_ref`→Select whose options load from `processEntriesListOptions`-mocked source-form entries labelled by `display_key`); required fields block submit with a validation line; submit emits `{ entry_date, data, staff }` with numbers as numbers and booleans as booleans.

- [ ] **Step 2: Run to verify failure** — vitest, FAIL.

- [ ] **Step 3: Build the components**

`EntryForm.tsx` — controlled `Record<string, string | boolean>` drafts (strings for everything except booleans, converted at the boundary like `StaffFormDialog`); an exhaustive `switch` on field type so a new backend type breaks the build (the `INPUT_TYPE` Record trick from `SettingsFieldInput.tsx:37-45`); staff field defaults to the signed-in user when the top-level staff picker is rendered ("sign for myself" — the shell's user query provides the id); `entry_ref` options via `useQuery({ ...processFormsEntriesListOptions({ path: { form_id: field.source_form } }) })` mapping rows to `data[display_key]` labels.

`FormEntriesPage.tsx` — header (`FormEntries-title` = form title, badges for doc number/type/status), the add-entry card rendering `EntryForm` (hidden when the schema has no fields, with the "no form schema defined" message), then `EntriesTable` under a heading:

```tsx
<h2 data-automation-id="FormEntries-entries-count" className="text-lg font-semibold">
  Entries ({entriesQuery.data?.count ?? 0})
</h2>
```

Columns from schema fields (values via `entry.display_data[key] ?? String(entry.data[key] ?? '-')`), plus Date, Staff, Entered by, Links count; row actions Edit (dialog with `EntryForm` + `initial`), History (`EntryHistoryDialog` listing `processEntriesHistoryListOptions` rows: timestamp, staff_name, description), Links (`LinkedEntriesDialog`: children via `processEntriesListOptions({ query: { parent: id } })` grouped by child form title, plus "Add linked entry" — pick a form from `processFormsListOptions()`, then `EntryForm` for it with `parent_entry` preset), Archive (confirm then `processEntriesDestroyMutation`). All mutations invalidate `processFormsEntriesListQueryKey({ path: { form_id } })` and `processEntriesListQueryKey()` (prefix match) via a local `invalidate` closure; errors `toast.error(apiErrorMessage(...))`.

Update `FormDialog`'s preview to render `<EntryForm schema={parsed} disabled staffOptions={[]} ... />`.

Staff options: reuse whatever any-staff staff listing the timesheet page uses (`/api/timesheets/staff/` per `fixtures/api.ts:67-72`) — **verify its auth level in `apps/timesheet/api.py` first**; if it is office-gated, add `GET /api/process/staff-options/` (id + display name, any-auth) to Task 8's router instead and regenerate. Record whichever way it falls in a code comment naming the auth class.

- [ ] **Step 4: Run until green** — `npx vitest run src/features/process && npm run type-check`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/process/
git commit -m "Entries page: one schema-driven entry form, audit history panel, linked entries"
```

---

### Task 13: E2E — port `form-entries-page-scroll`

**Files:**
- Create: `frontend/tests/e2e/process-documents/form-entries-page-scroll.spec.ts`

**Interfaces:** consumes the v2 API shapes (Task 7/8) and the Task 12 automation ids. Source spec: `/home/corrin/src/docketworks/frontend/tests/process-documents/form-entries-page-scroll.spec.ts` (101 lines) — port its behaviour, not its wire calls.

- [ ] **Step 1: Write the spec**

```ts
/**
 * Regression: the form-entries page must scroll to the entries table on a
 * small viewport (v1 KAN-160 — "Partial fix on this bug. Still can't scroll").
 * Seeds over the API; e2e_cleanup sweeps the [TEST] form and its entries.
 */

import { z } from 'zod'

import { expect, test } from '../fixtures/auth'
import { autoId } from '../helpers'

const TALL_FORM_FIELDS = [
  { key: 'incident_date', label: 'Incident date', type: 'date', required: true },
  { key: 'reported_by', label: 'Reported by', type: 'text' },
  { key: 'location', label: 'Location', type: 'text' },
  { key: 'description', label: 'Description', type: 'textarea' },
  { key: 'immediate_action', label: 'Immediate action', type: 'textarea' },
  { key: 'root_cause', label: 'Root cause', type: 'textarea' },
  { key: 'corrective_action', label: 'Corrective action', type: 'textarea' },
  { key: 'witnesses', label: 'Witnesses', type: 'textarea' },
  { key: 'equipment_involved', label: 'Equipment involved', type: 'textarea' },
  { key: 'notes', label: 'Notes', type: 'textarea' },
]

function entryData(): Record<string, string> {
  return Object.fromEntries(
    TALL_FORM_FIELDS.map((field) => [
      field.key,
      field.type === 'date' ? '2026-06-27' : `${field.label} test value`,
    ]),
  )
}

const createdForm = z.object({ id: z.string() })

test('tall form entries page scrolls to saved entries', async ({ authenticatedPage: page }) => {
  await page.setViewportSize({ width: 390, height: 640 })

  const title = `[TEST] Tall Incident Form ${Date.now()}`
  let formId = ''

  await test.step('seed a tall form and one entry over the API', async () => {
    const formResponse = await page.request.post('/api/process/forms/', {
      data: {
        document_type: 'form',
        category: 'incident',
        title,
        document_number: `KAN-160-${Date.now()}`,
        tags: ['incident', 'test'],
        form_schema: { fields: TALL_FORM_FIELDS },
      },
    })
    if (!formResponse.ok()) {
      throw new Error(`Form seed failed: ${formResponse.status()} ${await formResponse.text()}`)
    }
    formId = createdForm.parse(await formResponse.json()).id

    const entryResponse = await page.request.post(`/api/process/forms/${formId}/entries/`, {
      data: { entry_date: '2026-06-27', data: entryData() },
    })
    if (!entryResponse.ok()) {
      throw new Error(`Entry seed failed: ${entryResponse.status()} ${await entryResponse.text()}`)
    }
  })

  await test.step('the page overflows and the entries heading scrolls into view', async () => {
    const entriesLoaded = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/process/forms/${formId}/entries/`) &&
        response.request().method() === 'GET' &&
        response.ok(),
    )
    await page.goto(`/process-documents/forms/incident/${formId}`)
    await entriesLoaded

    await expect(autoId(page, 'FormEntries-title')).toHaveText(title)

    const main = page.locator('main')
    const overflows = await main.evaluate((el) => el.scrollHeight > el.clientHeight)
    expect(overflows).toBe(true)

    await main.hover()
    await page.mouse.wheel(0, 1400)
    await expect(autoId(page, 'FormEntries-entries-count')).toBeInViewport()
    await expect(autoId(page, 'FormEntries-entries-count')).toHaveText('Entries (1)')
  })
})
```

(The v1 spec's `overflowY === 'auto'` assertion pinned a Vue-router meta flag that has no v2 equivalent; the behavioural assertions — overflow exists, wheel reaches the heading — are the regression guard. If the v2 `_authed` layout scrolls a different element than `main`, adjust the locator to the layout's scroll container and leave a comment naming it.)

- [ ] **Step 2: Run it**

Environment per the repo rule — the controller owns services. From the repo root: `./scripts/ops/run_e2e.sh --grep "tall form entries page"` (or, against an already-running stack you started: `cd frontend && npx playwright test tests/e2e/process-documents/form-entries-page-scroll.spec.ts`).
Expected: PASS. This green is the MUST milestone — report it as such.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/e2e/process-documents/
git commit -m "Port the form-entries-page-scroll E2E spec (MUST tier)"
```

---

### Task 14: E2E — authored lifecycle spec

**Files:**
- Create: `frontend/tests/e2e/process-documents/form-lifecycle.spec.ts`

**Interfaces:** consumes Task 11/12 automation ids.

- [ ] **Step 1: Write the spec**

One `test.describe.serial` walking the slice's business story through the UI (structure and idioms per `staff/create-staff.spec.ts` — `test.step`s, `waitForResponse` capture of created ids, `[data-slot="dialog-content"]` visibility, `[data-sonner-toast]`, `dismissToasts`):

1. **Office staff creates a form** via `/process-documents/forms/meeting` → New Form: title `[TEST] Meeting minutes ${timestamp}`, category meeting, a 3-field schema typed into the JSON editor (assert the preview shows the three labels before saving).
2. **Fill it** on the entries page as the logged-in user (the E2E user); assert the row appears and `Entries (1)`.
3. **Add a linked entry**: from the row's Links dialog, pick the same form, fill, save; assert the links count shows 1.
4. **Edit the entry** (change one field); open History; assert two events, newest first, and the description contains the field's label and both values.
5. **Archive the entry**; assert `Entries (1)` for the remaining linked child or the count the flow implies (compute exactly while writing; assert a literal).
6. **Archive the form** from the list page's edit dialog (status → archived); assert it leaves the default list and appears under Show archived.

Every seeded title carries `[TEST]`; no cleanup step needed (e2e_cleanup owns it — Task 9).

- [ ] **Step 2: Run** — same runner as Task 13, grep `"form lifecycle"`. Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/e2e/process-documents/form-lifecycle.spec.ts
git commit -m "Authored form-lifecycle E2E: create, fill, link, audit, archive"
```

---

### Task 15: Wrap-up — docs, ledger, full gates

**Files:**
- Modify: `docs/rewrite-status.md` (delete the process-forms MUST lines: the spec row in "Specs still to port" and the "Process forms" bullet; the status table's numbers regenerate)
- Modify: `docs/accepted-api-differences.yml` (behaviour entries)
- Modify: `docs/rewrite-history.md` (one line: stored exclusive categories replaced v1's overlapping tag filters, date + design-doc pointer)

- [ ] **Step 1: Behaviour ledger entries** in `docs/accepted-api-differences.yml` (match its entry format — read it first): archive-only deletion (no destroy endpoints); exclusive stored categories (a doc lists once — v1 listed JSAs and two incident forms twice); entry data validated against the schema (v1 accepted anything); entries list paginated.

- [ ] **Step 2: rewrite-status.md** — delete completed MUST lines only; do not add prose (the file only shrinks). Verify `uv run python -m scripts.checks.status_table` passes.

- [ ] **Step 3: Full verification**

```bash
uv run pytest apps/process apps/core apps/company apps/crm apps/diagnostics
pre-commit run --all-files
pre-commit run --all-files --hook-stage pre-push
```

Expected: all green. Report progress as **specs green** (scroll + lifecycle), per the repo rule.

- [ ] **Step 4: Commit and push**

```bash
git add docs/
git commit -m "Process forms slice complete: status shrunk, behaviour deviations recorded"
git push -u origin process-documents
```

Then open the PR (title: "Process forms: categories, audited entries, entry links, and the form-entries-page-scroll spec") and follow the slice-PR process (adversarial two-subagent review pre-PR, answer every CodeRabbit thread, check `gh pr checks` before reporting done — use `gh pr view --json comments,reviews`, not `--comments`).
