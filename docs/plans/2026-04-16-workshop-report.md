# Workshop Report — Backend (v1)

## Context

Office staff need to manage customer delivery expectations. Currently there is no way to see
when jobs are likely to finish based on remaining workshop hours and available workers. This
backend provides a scheduling simulation: given jobs in progress (and approved), remaining
hours per job, and staff daily capacity, it calculates expected delivery dates and daily
utilisation so the frontend can render a calendar and job table.

This is an operations concern, not an accounting concern. The implementation should therefore
live in a dedicated `apps/operations` app, with workshop scheduling as the first feature in
that domain.

V1 deliberately uses a simple, explicit algorithm. Future versions may replace it with a more
advanced algorithm, and there may be a temporary period where two versions are run side by side
for comparison. The design should support versioned replacement, not speculative runtime
pluggability.

---

## Scope

Backend only. The frontend calendar window is a display concern. The API should return enough
data for the frontend to render:

- a bounded sequence of daily capacity/allocation rows for the calendar
- per-job expected completion data
- explicit unschedulable/problem jobs that require office attention

V1 should not silently omit jobs with missing estimate data or invalid staffing constraints.
Those jobs must be surfaced in the report.

---

## New Job Model Fields

File: `apps/job/models/job.py`

Add two fields to `Job`:

```python
min_people = models.PositiveSmallIntegerField(
    default=1,
    help_text="Minimum workers required to begin this job",
)
max_people = models.PositiveSmallIntegerField(
    default=1,
    help_text="Maximum workers that can work on this job simultaneously",
)
```

These defaults are intentional. Most jobs can only be worked on by one person. Jobs that need
two or more workers are exceptions and must be configured explicitly.

Add model validation so the following are enforced:

- `min_people >= 1`
- `max_people >= 1`
- `max_people >= min_people`

When adding the fields, review all downstream `Job` checklist locations in
`apps/job/models/job.py` and make deliberate decisions about whether these fields should be:

- editable through existing job APIs/forms
- exposed in serializers
- included in change-event tracking
- included in any list/report payloads that mirror direct Job fields

Add a migration. Run `python scripts/update_init.py` after any new Python files are added.

---

## New Django App: `apps/operations`

Workshop scheduling belongs in operations. Create a new app for operational planning concerns,
with scheduling as the first capability.

```
apps/operations/
├── apps.py
├── __init__.py
├── urls.py
├── serializers/
│   ├── __init__.py
│   └── workshop_schedule_serializers.py
├── views/
│   ├── __init__.py
│   └── workshop_schedule_view.py
├── services/
│   ├── __init__.py
│   ├── workshop_schedule_service.py
│   ├── workshop_schedule_algorithm_v1.py
│   └── workshop_schedule_types.py
└── tests/
    └── __init__.py
```

Register in the Django settings module:

```python
"apps.operations.apps.OperationsConfig",
```

If later we need a materially different algorithm, add:

- `workshop_schedule_algorithm_v2.py`

Do not add a strategy-pattern abstraction yet. Versioned implementations are a better fit than
an ABC with injected sort policies.

---

## Scheduler Service

### Data structures

**File:** `apps/operations/services/workshop_schedule_types.py`

Use dataclasses or typed dictionaries for internal service inputs/results. Keep them small and
focused on scheduling, not PDF/report formatting.

Recommended internal shapes:

```python
@dataclass
class JobScheduleInput:
    id: UUID
    job_number: int
    name: str
    client_name: str | None
    remaining_hours: float
    delivery_date: date | None
    priority: float
    min_people: int
    max_people: int


@dataclass
class SchedulableJob:
    job: JobScheduleInput
    expected_delivery_date: date | None = None
    is_late: bool = False


@dataclass
class UnscheduledJob:
    id: UUID
    job_number: int
    name: str
    client_name: str | None
    delivery_date: date | None
    remaining_hours: float | None
    reason: str


@dataclass
class DayResult:
    date: date
    total_capacity_hours: float
    allocated_hours: float
    utilisation_pct: float
    completing_job_ids: list[UUID]


@dataclass
class SimulationResult:
    days: list[DayResult]
    jobs: list[SchedulableJob]
    unscheduled_jobs: list[UnscheduledJob]
```

`unscheduled_jobs` is required. V1 must highlight jobs that could not be simulated.

### Operations service

**File:** `apps/operations/services/workshop_schedule_service.py`

```python
class WorkshopScheduleService:
    def simulate(
        self,
        *,
        start_date: date,
        algorithm_version: str = "v1",
        day_horizon: int = 28,
    ) -> SimulationResult:
        ...
```

Responsibilities:

1. Load jobs and staff.
2. Compute scheduling inputs.
3. Separate schedulable jobs from unschedulable/problem jobs.
4. Dispatch to the selected algorithm implementation.
5. Return a serializer-friendly result structure.

### Algorithm implementation

**File:** `apps/operations/services/workshop_schedule_algorithm_v1.py`

Implement one plain algorithm module for v1. No `SchedulingStrategy`, no ABC, no dependency
injection for sort policies.

Recommended entry point:

```python
def run_workshop_schedule_v1(
    *,
    jobs: list[JobScheduleInput],
    staff: list[Staff],
    start_date: date,
    day_horizon: int,
) -> tuple[list[DayResult], list[SchedulableJob]]:
    ...
```

If a new algorithm is introduced later, add `run_workshop_schedule_v2(...)` in a separate
module and let the service select the version explicitly.

### Remaining-hours helper

Do not use `get_time_breakdown(job)` directly inside the scheduling loop. That helper is aimed
at workshop PDF output and does more work than this report needs.

Instead, create a lean helper within operations scheduling code that computes:

- budgeted workshop hours from estimate
- fallback to quote if estimate has no workshop hours
- used workshop hours from `job.latest_actual.summary["hours"]`
- remaining workshop hours

The fallback rule is:

- estimate is primary
- quote is fallback if no estimate workshop hours are entered

If neither estimate nor quote yields usable workshop hours, the job must appear in
`unscheduled_jobs` with a reason such as `"missing_estimate_or_quote_hours"`.

### Algorithm

1. **Load jobs** with `status__in=["in_progress", "approved"]`.
2. **Build job inputs**:
   - compute remaining workshop hours using the estimate-first, quote-fallback rule
   - if remaining hours is `<= 0`, exclude from the schedulable set
   - if input data is invalid or incomplete, add the job to `unscheduled_jobs`
3. **Load active workshop staff**:
   - active means `date_left is null` or `date_left > today`
   - include only `is_office_staff=False`
4. **Sort jobs** by priority descending for v1.
5. **Day loop** starting from `start_date`:
   - for each staff member, call `staff.get_scheduled_hours(current_date)`
   - skip zero-hour staff for that day
   - if total capacity is zero, record a zero-capacity day and continue
   - allocate workers to jobs in priority order
   - for each job:
     - skip when remaining hours `<= 0`
     - assign up to `job.max_people` workers
     - if assigned worker count is less than `job.min_people`, do not allocate that job on that day
     - reduce remaining hours by the allocated productive hours
     - when remaining reaches zero, record `expected_delivery_date`
   - record `DayResult`
6. **Termination**:
   - continue simulation until all schedulable jobs are complete, or a hard safety cap is reached
   - only return `days` for the requested `day_horizon`
   - expected delivery dates may fall beyond the returned day rows
7. Return:
   - bounded `days`
   - all scheduled job results
   - all unscheduled/problem jobs

### Efficiency factor

Do not hard-code `0.8` in v1 unless the business has agreed that this is a real planning rule.
If an efficiency factor is required, source it from configuration or add it in a later change.
The initial implementation should prefer transparent arithmetic over hidden optimism/pessimism.

### Calendar realism

V1 uses `staff.get_scheduled_hours(date)` as the staff-capacity source. This means the first
version is based on standard weekday hours only. Public holidays, leave, shutdown periods, and
other capacity adjustments are out of scope unless already represented elsewhere in the system.

Document this limitation clearly in the endpoint description and frontend expectations.

---

## Serializers

**File:** `apps/operations/serializers/workshop_schedule_serializers.py`

```python
class WorkshopScheduleDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    total_capacity_hours = serializers.FloatField()
    allocated_hours = serializers.FloatField()
    utilisation_pct = serializers.FloatField()
    completing_job_ids = serializers.ListField(child=serializers.UUIDField())


class WorkshopScheduleJobSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    job_number = serializers.IntegerField()
    name = serializers.CharField()
    client_name = serializers.CharField(allow_null=True)
    remaining_hours = serializers.FloatField()
    delivery_date = serializers.DateField(allow_null=True)
    expected_delivery_date = serializers.DateField(allow_null=True)
    is_late = serializers.BooleanField()


class WorkshopScheduleUnscheduledJobSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    job_number = serializers.IntegerField()
    name = serializers.CharField()
    client_name = serializers.CharField(allow_null=True)
    delivery_date = serializers.DateField(allow_null=True)
    remaining_hours = serializers.FloatField(allow_null=True)
    reason = serializers.CharField()


class WorkshopScheduleResponseSerializer(serializers.Serializer):
    days = WorkshopScheduleDaySerializer(many=True)
    jobs = WorkshopScheduleJobSerializer(many=True)
    unscheduled_jobs = WorkshopScheduleUnscheduledJobSerializer(many=True)
```

`unscheduled_jobs` is part of the main response contract.

---

## View

**File:** `apps/operations/views/workshop_schedule_view.py`

Implement the endpoint using the same error-handling shape used by existing reporting endpoints:

- validate query params
- return structured serializer responses
- handle `AlreadyLoggedException`
- persist unexpected exceptions with request context and return an error payload

Use `timezone.localdate()` rather than `date.today()`.

Recommended v1 query parameters:

- `algorithm_version` default `"v1"`
- `day_horizon` default `28`

Example:

```python
class WorkshopScheduleAPIView(APIView):
    @extend_schema(...)
    def get(self, request):
        ...
```

Do not use a bare `persist_app_error(exc); raise` pattern here. Match the established API error
contract used elsewhere in reporting endpoints.

---

## URL Registration

**File:** `apps/operations/urls.py`

```python
app_name = "operations"

urlpatterns = [
    path(
        "reports/workshop-schedule/",
        WorkshopScheduleAPIView.as_view(),
        name="api_workshop_schedule",
    ),
]
```

Wire the operations URLs into the project-level URL config in the same style as other apps.

---

## Key files to modify / create

| Action | File |
|--------|------|
| Modify | `apps/job/models/job.py` — add `min_people`, `max_people`, and validation |
| Create | `apps/job/migrations/NNNN_add_job_people_constraints.py` |
| Create | `apps/operations/apps.py` |
| Create | `apps/operations/__init__.py` |
| Create | `apps/operations/urls.py` |
| Create | `apps/operations/serializers/__init__.py` |
| Create | `apps/operations/serializers/workshop_schedule_serializers.py` |
| Create | `apps/operations/views/__init__.py` |
| Create | `apps/operations/views/workshop_schedule_view.py` |
| Create | `apps/operations/services/__init__.py` |
| Create | `apps/operations/services/workshop_schedule_service.py` |
| Create | `apps/operations/services/workshop_schedule_algorithm_v1.py` |
| Create | `apps/operations/services/workshop_schedule_types.py` |
| Create | `apps/operations/tests/__init__.py` |
| Modify | settings module — add `"apps.operations.apps.OperationsConfig"` |
| Modify | project URL registration — include operations URLs |
| Run | `python scripts/update_init.py` |

### Existing functions/patterns to reuse

- `staff.get_scheduled_hours(date)` — `apps/accounts/models.py`
- reporting endpoint error-handling shape — `apps/accounting/views/job_aging_view.py`
- `persist_app_error(exc)` / `extract_request_context(request)` — `apps/workflow/services/error_persistence.py`

Do not treat `get_time_breakdown(job)` as the core scheduling helper. Reuse its underlying
business idea, but implement a lighter scheduling-specific hours calculation.

---

## Verification

1. `python manage.py makemigrations && python manage.py migrate`
   - migration applies cleanly
   - existing jobs receive `min_people=1`, `max_people=1`

2. Validate model rules manually or with tests
   - `min_people=0` is rejected
   - `max_people=0` is rejected
   - `max_people < min_people` is rejected

3. `curl http://localhost:8000/api/operations/reports/workshop-schedule/`
   - returns `200`
   - response includes `days`, `jobs`, and `unscheduled_jobs`
   - zero-capacity days are represented explicitly

4. Create a job with estimate workshop hours and known staff capacity
   - verify `expected_delivery_date` is correct

5. Create a job with no estimate workshop hours but valid quote workshop hours
   - verify quote fallback is used
   - verify the job still appears in scheduled results

6. Create a job with neither estimate nor quote workshop hours
   - verify it appears in `unscheduled_jobs`
   - verify the reason is explicit and visible to office staff

7. Create a job with impossible staffing constraints relative to available workers
   - verify it appears in `unscheduled_jobs` or another explicit problem state
   - verify it is not silently omitted

8. If/when `algorithm_version` is exposed
   - invalid version returns `400`
   - valid version is logged or otherwise traceable in server diagnostics
