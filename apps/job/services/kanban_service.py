"""Kanban board service, ported from v1 ``apps/job/services/kanban_service.py``.

All business logic for the kanban board: column fetches, weighted trigram
search, advanced search, drag reordering (priority floats + rebalancing),
status updates, and the incremental changes feed
(``apps/job/kanban_version.py``).

v1 sibling check (ADR 0039): the v1 frontend's ``useOptimizedKanban`` was a
shadow client-side implementation (not ported); backend-side there is exactly
one kanban service — ``kanban_categorization_service`` is its column taxonomy,
not a sibling, and the workshop kanban view is a separate surface (later
sub-slice).

v1 also wrote a SearchTelemetryEvent row via ``apps.search``; domain apps may
not import the search integration (layer contract), so that write returns
with the search-app port. The structured ``kanban_search`` log line below is
the behaviour that ports now (same treatment as company search).
"""

import json
import logging
import operator
import uuid as uuid_module
from collections import defaultdict
from dataclasses import dataclass
from functools import reduce
from typing import Protocol, TypedDict, cast
from uuid import UUID, uuid4

from django.contrib.postgres.search import TrigramSimilarity, TrigramWordSimilarity
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import (
    Case,
    Count,
    Exists,
    Expression,
    ExpressionWrapper,
    F,
    FloatField,
    Max,
    OuterRef,
    Q,
    QuerySet,
    TextField,
    Value,
    When,
)
from django.db.models.functions import Cast, Coalesce, Greatest
from django.http import HttpRequest

from apps.accounting.models import Invoice
from apps.accounts.models import Staff
from apps.company.models import Company, Person
from apps.core.models import CompanyDefaults
from apps.job.kanban_version import KanbanDatasetVersion
from apps.job.models import CostSet, Job
from apps.job.services.kanban_categorization_service import KanbanCategorizationService

logger = logging.getLogger(__name__)
search_logger = logging.getLogger("kanban_search")


class KanbanStaffData(TypedDict):
    """One assigned staff member on a kanban card."""

    id: str
    display_name: str
    icon_url: str | None


class KanbanJobData(TypedDict):
    """One serialized kanban card (v1 serialize_job_for_api shape)."""

    id: str
    name: str
    description: str
    job_number: int
    company_name: str
    person_name: str
    people: list[KanbanStaffData]
    status: str
    status_key: str
    rejected_flag: bool
    paid: bool
    fully_invoiced: bool
    speed_quality_tradeoff: str
    created_by_id: str | None
    created_at: str | None
    updated_at: str | None
    delivery_date: str | None
    priority: float
    shop_job: bool
    over_budget: bool
    quote_revenue: float
    time_and_materials_revenue: float
    min_people: int
    max_people: int
    is_urgent: bool
    badge_label: str
    badge_color: str


class KanbanColumnJobsData(TypedDict, total=False):
    """Result of a by-column fetch (v1 get_jobs_by_kanban_column shape)."""

    success: bool
    error: str
    jobs: list[KanbanJobData]
    total: int
    filtered_count: int
    has_more: bool


class StatusChoicesData(TypedDict):
    """Kanban status choices + tooltips (v1 get_status_choices shape)."""

    statuses: dict[str, str]
    tooltips: dict[str, str]


class AdvancedSearchFilters(TypedDict, total=False):
    """Advanced search filters (all optional; empty string = not filtered)."""

    universal_search: str
    job_number: str
    name: str
    description: str
    company_name: str
    person_name: str
    order_number: str
    created_by: str
    created_after: str
    created_before: str
    status: list[str]
    paid: str
    rejected_flag: str
    xero_invoice_params: str


class _TextSearchFieldSpec(TypedDict):
    """One weighted searchable text field."""

    db_path: str
    expression: Expression
    score: float
    reason: str


class _TokenReason(TypedDict):
    """The winning score/reason for one search token on one job."""

    token: str
    reason: str
    score: float


class _RankableJob(Protocol):
    """A Job carrying the transient ranking attrs the search attaches in-memory.

    v1 monkeypatched search_score/search_reasons straight onto Job instances for
    the ranked kanban search; this Protocol is the typed seam that keeps those
    dynamic attributes honest (assign via cast, read via getattr) without a
    persisted model field.
    """

    search_score: float
    search_reasons: dict[str, list[_TokenReason]]


@dataclass(frozen=True)
class KanbanSerializationContext:
    """Batched related data for kanban job serialization.

    Built once per response so serialize_job_for_api never touches a relation
    descriptor (v1: the dev/E2E n+1 guard made per-card descriptor access
    pathologically slow).
    """

    shop_company_id: UUID | None
    summaries: dict[UUID, dict[str, float]]
    company_names: dict[UUID, str]
    person_names: dict[UUID, str]
    people_by_job: dict[UUID, list[Staff]]


@dataclass(frozen=True)
class KanbanChanges:
    """Typed domain result for incremental Kanban reconciliation."""

    jobs: list[Job]
    removed_job_ids: list[UUID]
    full_refresh_required: bool


def _is_valid_uuid(value: str) -> bool:
    """Report whether the given string is a valid UUID."""
    try:
        uuid_module.UUID(value)
    except (ValueError, TypeError):
        return False
    return True


def _is_valid_invoice_number(value: str) -> bool:
    """Report whether the given string looks like an INV-<digits> number."""
    if "INV-" in value:
        parts = value.split("-")
        if len(parts) == 2 and parts[1].isdigit():
            return True
    return False


class KanbanService:
    """Service class for Kanban business logic."""

    KANBAN_TRIGRAM_THRESHOLD = 0.3
    SEARCH_SCORE_EXACT_JOB_NUMBER = 100.0
    SEARCH_SCORE_JOB_NUMBER_SUFFIX = 85.0
    SEARCH_SCORE_JOB_NUMBER_CONTAINS = 45.0
    SEARCH_SCORE_QUOTE_CONTAINS = 75.0
    SEARCH_SCORE_NAME_CONTAINS = 65.0
    SEARCH_SCORE_COMPANY_CONTAINS = 55.0
    SEARCH_SCORE_PERSON_CONTAINS = 55.0
    SEARCH_SCORE_DESCRIPTION_CONTAINS = 35.0
    SEARCH_SCORE_TRIGRAM_MULTIPLIER = 30.0
    SEARCH_SCORE_FALLBACK_RATIO = 0.5
    SEARCH_SCORE_MIN_DISPLAY = 15.0
    SEARCH_SCORE_ORDER_NUMBER_MATCH = 75.0

    TEXT_SEARCH_FIELDS: list[_TextSearchFieldSpec] = [  # noqa: RUF012 -- Expression values, deliberately shared
        {
            "db_path": "name",
            "expression": Coalesce("name", Value(""), output_field=TextField()),
            "score": SEARCH_SCORE_NAME_CONTAINS,
            "reason": "name_contains",
        },
        {
            "db_path": "company__name",
            "expression": Coalesce("company__name", Value(""), output_field=TextField()),
            "score": SEARCH_SCORE_COMPANY_CONTAINS,
            "reason": "company_contains",
        },
        {
            "db_path": "person__name",
            "expression": Coalesce("person__name", Value(""), output_field=TextField()),
            "score": SEARCH_SCORE_PERSON_CONTAINS,
            "reason": "person_contains",
        },
        {
            "db_path": "description",
            "expression": Coalesce("description", Value(""), output_field=TextField()),
            "score": SEARCH_SCORE_DESCRIPTION_CONTAINS,
            "reason": "description_contains",
        },
        {
            "db_path": "job_number",
            "expression": Coalesce(
                Cast("job_number", output_field=TextField()),
                Value(""),
                output_field=TextField(),
            ),
            "score": SEARCH_SCORE_JOB_NUMBER_CONTAINS,
            "reason": "job_number_contains",
        },
        {
            "db_path": "quote__number",
            "expression": Coalesce("quote__number", Value(""), output_field=TextField()),
            "score": SEARCH_SCORE_QUOTE_CONTAINS,
            "reason": "quote_contains",
        },
        {
            "db_path": "order_number",
            "expression": Coalesce("order_number", Value(""), output_field=TextField()),
            "score": SEARCH_SCORE_ORDER_NUMBER_MATCH,
            "reason": "order_number_contains",
        },
        {
            "db_path": "invoices__number",
            "expression": Coalesce("invoices__number", Value(""), output_field=TextField()),
            "score": SEARCH_SCORE_QUOTE_CONTAINS,
            "reason": "invoice_contains",
        },
    ]

    @staticmethod
    def get_kanban_changes(after: str) -> KanbanChanges:
        """Return changed cards since an opaque Job dataset version."""
        previous = KanbanDatasetVersion.decode(after)

        current = Job.objects.aggregate(
            count=Count("id"),
            latest_created=Max("created_at"),
        )
        current_topology = KanbanDatasetVersion.from_values(
            updated_at=None,
            created_at=current["latest_created"],
            count=current["count"],
        )
        if (
            current_topology.count != previous.count
            or current_topology.created_at != previous.created_at
        ):
            return KanbanChanges(
                jobs=[],
                removed_job_ids=[],
                full_refresh_required=True,
            )

        changed_jobs = Job.objects.filter(updated_at__gt=previous.updated_at)
        visible_jobs = KanbanService.filter_kanban_jobs(changed_jobs)
        visible_ids = set(visible_jobs.values_list("id", flat=True))
        removed_job_ids = list(
            changed_jobs.exclude(id__in=visible_ids).values_list("id", flat=True)
        )

        return KanbanChanges(
            jobs=list(visible_jobs),
            removed_job_ids=removed_job_ids,
            full_refresh_required=False,
        )

    @staticmethod
    def get_jobs_by_status(
        status: str,
        search_terms: list[str] | None = None,
        limit: int = 200,
        request: HttpRequest | None = None,
    ) -> QuerySet[Job] | list[Job]:
        """Get jobs filtered by status and optional search terms."""
        jobs_query = Job.objects.filter(status=status)

        jobs: QuerySet[Job] | list[Job]
        if search_terms:
            search_query = " ".join(search_terms)
            jobs = KanbanService._apply_kanban_search(jobs_query, search_query)
            KanbanService.log_kanban_search_results(
                request=request,
                source="status",
                query=search_query,
                jobs=list(jobs),
                filters={"status": status},
            )
            ordering_description = "ordered by search relevance desc"
        else:
            jobs = jobs_query.order_by("-priority", "-created_at")
            ordering_description = "ordered by priority desc"
        logger.info(
            "Jobs fetched by status '%s' (%s): %s",
            status,
            ordering_description,
            [f"#{job.job_number}(p:{job.priority})" for job in jobs[:10]],
        )

        # Apply different limits based on status
        match status:
            case "archived":
                return jobs[:100]
            case _:
                return jobs[:limit]

    @staticmethod
    def _apply_kanban_search(jobs_query: QuerySet[Job], query: str) -> list[Job]:
        normalized_query = query.strip()
        if not normalized_query:
            return list(jobs_query)

        tokens = normalized_query.split()

        annotations: dict[str, Expression] = {}
        token_aliases: list[str] = []
        for index, token in enumerate(tokens):
            alias = f"search_token_score_{index}"
            substring_whens = [
                When(**{f"{spec['db_path']}__icontains": token}, then=Value(1.0))
                for spec in KanbanService.TEXT_SEARCH_FIELDS
                if spec["db_path"] not in {"job_number", "invoices__number"}
            ]
            invoice_match = Exists(
                Invoice.objects.filter(job=OuterRef("pk"), number__icontains=token)
            )
            field_scores = [
                TrigramSimilarity(spec["expression"], token)
                for spec in KanbanService.TEXT_SEARCH_FIELDS
                if spec["db_path"] != "invoices__number"
            ] + [
                TrigramWordSimilarity(token, spec["expression"])
                for spec in KanbanService.TEXT_SEARCH_FIELDS
                if spec["db_path"] != "invoices__number"
            ]
            annotations[alias] = Greatest(
                Case(
                    *substring_whens,
                    When(invoice_match, then=Value(1.0)),
                    default=Value(0.0),
                    output_field=FloatField(),
                ),
                *field_scores,
            )
            token_aliases.append(alias)

        annotated_query = jobs_query.annotate(**annotations)

        token_filter = Q()
        for alias in token_aliases:
            token_filter &= Q(**{f"{alias}__gte": KanbanService.KANBAN_TRIGRAM_THRESHOLD})

        combined_score = reduce(operator.add, (F(alias) for alias in token_aliases))
        scored_query = annotated_query.annotate(
            trigram_score=ExpressionWrapper(
                combined_score / Value(len(token_aliases)),
                output_field=FloatField(),
            )
        )

        # Comprehension, not list(): the annotate() return type is a Job
        # subtype and list is invariant — the comprehension lets the declared
        # list[Job] type context apply (mypy strict).
        candidates: list[Job] = [  # noqa: C416
            job
            for job in scored_query.filter(token_filter)
            .select_related("company", "person", "quote")
            .prefetch_related("invoices")
            .order_by("-trigram_score", "-created_at")
        ]
        return KanbanService._rank_kanban_search_candidates(candidates, normalized_query)

    @staticmethod
    def _rank_kanban_search_candidates(candidates: list[Job], query: str) -> list[Job]:
        scored_jobs = []
        for job in candidates:
            score, reasons = KanbanService._score_kanban_search_candidate(job, query)
            rankable = cast("_RankableJob", job)
            rankable.search_score = score
            rankable.search_reasons = reasons
            scored_jobs.append(job)

        scored_jobs.sort(
            key=lambda job: (
                getattr(job, "search_score", 0.0),
                getattr(job, "trigram_score", 0.0),
                job.created_at,
            ),
            reverse=True,
        )
        if not scored_jobs:
            return scored_jobs

        best_score = getattr(scored_jobs[0], "search_score", 0.0)
        if best_score < KanbanService.SEARCH_SCORE_MIN_DISPLAY:
            return []

        if best_score >= KanbanService.SEARCH_SCORE_EXACT_JOB_NUMBER:
            score_floor = KanbanService.SEARCH_SCORE_EXACT_JOB_NUMBER
        elif best_score >= KanbanService.SEARCH_SCORE_JOB_NUMBER_SUFFIX:
            score_floor = KanbanService.SEARCH_SCORE_DESCRIPTION_CONTAINS
        else:
            score_floor = max(
                best_score * KanbanService.SEARCH_SCORE_FALLBACK_RATIO,
                KanbanService.SEARCH_SCORE_TRIGRAM_MULTIPLIER
                * KanbanService.KANBAN_TRIGRAM_THRESHOLD,
            )

        return [job for job in scored_jobs if getattr(job, "search_score", 0.0) >= score_floor]

    @staticmethod
    def _score_kanban_search_candidate(
        job: Job, query: str
    ) -> tuple[float, dict[str, list[_TokenReason]]]:
        tokens = query.lower().split()
        token_scores = []
        token_reasons = []

        for token in tokens:
            token_score, reason = KanbanService._score_kanban_search_token(job, token)
            token_scores.append(token_score)
            token_reasons.append(reason)

        score = sum(token_scores) / len(token_scores) if token_scores else 0.0
        return score, {"tokens": token_reasons}

    @staticmethod
    def _score_kanban_search_token(job: Job, token: str) -> tuple[float, _TokenReason]:
        job_number = str(job.job_number)
        trigram_score = float(getattr(job, "trigram_score", 0.0) or 0.0)

        scored_reasons: list[tuple[float, str]] = [
            (
                (KanbanService.SEARCH_SCORE_EXACT_JOB_NUMBER if job_number == token else 0.0),
                "exact_job_number",
            ),
            (
                (
                    KanbanService.SEARCH_SCORE_JOB_NUMBER_SUFFIX
                    if job_number.endswith(token)
                    else 0.0
                ),
                "job_number_suffix",
            ),
        ]

        for spec in KanbanService.TEXT_SEARCH_FIELDS:
            value = KanbanService._get_search_field_value(job, spec["db_path"])
            if value and token in value:
                scored_reasons.append((spec["score"], spec["reason"]))
            else:
                scored_reasons.append((0.0, spec["reason"]))

        scored_reasons.append(
            (
                trigram_score * KanbanService.SEARCH_SCORE_TRIGRAM_MULTIPLIER,
                "misspelling",
            )
        )

        score, reason = max(scored_reasons, key=lambda scored: scored[0])
        return score, {"token": token, "reason": reason, "score": score}

    @staticmethod
    def _job_quote_number(job: Job) -> str:
        try:
            quote = job.quote
        except ObjectDoesNotExist:
            return ""
        return quote.number or ""

    @staticmethod
    def _get_search_field_value(job: Job, db_path: str) -> str:  # noqa: PLR0911 -- one return per searchable field
        match db_path:
            case "name":
                return (job.name or "").lower()
            case "company__name":
                return (job.company.name if job.company_id and job.company else "").lower()
            case "person__name":
                return (job.person.name if job.person_id and job.person else "").lower()
            case "description":
                return (job.description or "").lower()
            case "job_number":
                return str(job.job_number)
            case "quote__number":
                return KanbanService._job_quote_number(job).lower()
            case "order_number":
                return (job.order_number or "").lower()
            case "invoices__number":
                return " ".join(inv.number for inv in job.invoices.all()).lower()
            case _:
                return ""

    @staticmethod
    def log_kanban_search_results(  # noqa: PLR0913 -- v1 signature (all keyword-only)
        *,
        request: HttpRequest | None,
        source: str,
        query: str,
        jobs: list[Job],
        filters: dict[str, object] | None = None,
        column_id: str | None = None,
    ) -> None:
        """Emit the structured kanban_search log line (v1 behaviour)."""
        active_filters = {
            key: value for key, value in (filters or {}).items() if value not in ("", None, [], {})
        }
        if not query.strip() and not active_filters:
            return

        user = getattr(request, "user", None) if request else None
        payload = {
            "event": "kanban_search_results",
            "search_id": str(uuid4()),
            "source": source,
            "query": query,
            "filters": filters or {},
            "column_id": column_id,
            "path": getattr(request, "path", None),
            "query_string": (request.META.get("QUERY_STRING", "") if request is not None else ""),
            "user_id": str(getattr(user, "id", "")) if user else None,
            "user_email": getattr(user, "email", None) if user else None,
            "result_count": len(jobs),
            "results": [
                {
                    "rank": index + 1,
                    "job_id": str(job.id),
                    "job_number": job.job_number,
                    "status": job.status,
                    "name": job.name,
                    "company": (job.company.name if job.company_id and job.company else None),
                    "trigram_score": getattr(job, "trigram_score", None),
                    "search_score": getattr(job, "search_score", None),
                    "search_reasons": getattr(job, "search_reasons", None),
                }
                for index, job in enumerate(jobs)
            ],
        }
        search_logger.info(json.dumps(payload, sort_keys=True, default=str))

    @staticmethod
    def get_all_active_jobs() -> QuerySet[Job]:
        """All active (non-archived) kanban jobs, ordered by priority only."""
        # No eager loading needed: serialization reads related data from the
        # batched KanbanSerializationContext, not from the instances.
        active_jobs = Job.objects.exclude(status="archived").order_by("-priority")
        filtered_jobs = KanbanService.filter_kanban_jobs(active_jobs)
        logger.info(
            "Active jobs fetched (ordered by priority desc): %s",
            [f"#{job.job_number}(p:{job.priority})" for job in filtered_jobs[:10]],
        )
        return filtered_jobs

    @staticmethod
    def get_archived_jobs(limit: int = 50) -> QuerySet[Job]:
        """Return archived jobs, newest first, with limit."""
        return Job.objects.filter(status="archived").order_by("-created_at")[:limit]

    @staticmethod
    def get_status_choices() -> StatusChoicesData:
        """Get available status choices and tooltips using the column taxonomy."""
        columns = KanbanCategorizationService.get_all_columns()

        # Create status choices based on columns (simplified kanban structure)
        status_choices = {}
        status_tooltips = {}

        for column in columns:
            # Use column as the main "status" for the kanban view
            status_choices[column.column_id] = column.column_title

            # Create tooltip based on column's status key
            status_tooltips[column.column_id] = (
                f"Status: {column.status_key.replace('_', ' ').title()}"
            )

        return {"statuses": status_choices, "tooltips": status_tooltips}

    @staticmethod
    def build_serialization_context(jobs: list[Job]) -> KanbanSerializationContext:
        """Batch-load everything serialize_job_for_api needs, in O(1) queries."""
        defaults = CompanyDefaults.get_solo()

        costset_ids = {job.latest_quote_id for job in jobs} | {job.latest_actual_id for job in jobs}
        costset_ids.discard(None)
        summaries = dict(CostSet.objects.filter(id__in=costset_ids).values_list("id", "summary"))

        company_ids = {job.company_id for job in jobs if job.company_id is not None}
        company_names = dict(Company.objects.filter(id__in=company_ids).values_list("id", "name"))

        person_ids = {job.person_id for job in jobs if job.person_id is not None}
        person_names = dict(Person.objects.filter(id__in=person_ids).values_list("id", "name"))

        people_links = list(
            Job.people.through.objects.filter(job_id__in=[job.id for job in jobs]).values_list(
                "job_id", "staff_id"
            )
        )
        staff_by_id = {
            staff.id: staff
            for staff in Staff.objects.filter(id__in={staff_id for _, staff_id in people_links})
        }
        people_by_job: dict[UUID, list[Staff]] = defaultdict(list)
        for job_id, staff_id in people_links:
            people_by_job[job_id].append(staff_by_id[staff_id])
        for people in people_by_job.values():
            # Match the old prefetch's Staff.Meta ordering
            people.sort(key=lambda staff: (staff.last_name, staff.first_name))

        return KanbanSerializationContext(
            shop_company_id=defaults.shop_company_id,
            summaries=summaries,
            company_names=company_names,
            person_names=person_names,
            people_by_job=dict(people_by_job),
        )

    @staticmethod
    def serialize_jobs_for_api(
        jobs: QuerySet[Job] | list[Job] | tuple[Job, ...],
    ) -> list[KanbanJobData]:
        """Serialize a Kanban job list with batched per-response context."""
        jobs_list = list(jobs)
        context = KanbanService.build_serialization_context(jobs_list)
        return [KanbanService.serialize_job_for_api(job, context=context) for job in jobs_list]

    @staticmethod
    def _job_revenues(job: Job, context: KanbanSerializationContext) -> tuple[float, float]:
        """Resolve (quote, actual) revenue from the batched CostSet summaries."""
        if not job.latest_quote_id:
            raise ValueError(f"Job #{job.job_number} has no quote CostSet")
        if not job.latest_actual_id:
            raise ValueError(f"Job #{job.job_number} has no actual CostSet")
        if job.latest_quote_id not in context.summaries:
            raise ValueError(
                f"Job #{job.job_number}: quote CostSet {job.latest_quote_id} "
                "missing from serialization context"
            )
        if job.latest_actual_id not in context.summaries:
            raise ValueError(
                f"Job #{job.job_number}: actual CostSet {job.latest_actual_id} "
                "missing from serialization context"
            )
        return (
            context.summaries[job.latest_quote_id]["rev"],
            context.summaries[job.latest_actual_id]["rev"],
        )

    @staticmethod
    def serialize_job_for_api(
        job: Job,
        *,
        context: KanbanSerializationContext,
    ) -> KanbanJobData:
        """Serialize a job for the kanban API response.

        Reads only local columns plus the batched context — no relation
        descriptor access (see KanbanSerializationContext).
        """
        badge_info = KanbanCategorizationService.get_badge_info(job.status)
        quote_revenue, time_and_materials_revenue = KanbanService._job_revenues(job, context)

        if job.pricing_methodology == "time_materials" and job.price_cap is not None:
            over_budget = float(job.price_cap) > 0 and time_and_materials_revenue > float(
                job.price_cap
            )
        else:
            over_budget = quote_revenue > 0 and time_and_materials_revenue > quote_revenue

        return {
            "id": str(job.id),
            "name": job.name,
            "description": job.description or "",
            "job_number": job.job_number,
            "company_name": (
                context.company_names.get(job.company_id, "") if job.company_id else ""
            ),
            "person_name": (context.person_names.get(job.person_id, "") if job.person_id else ""),
            "people": [
                {
                    "id": str(staff.id),
                    "display_name": staff.get_display_full_name(),
                    "icon_url": staff.icon.url if staff.icon else None,
                }
                for staff in context.people_by_job.get(job.id, [])
            ],
            "status": job.get_status_display(),
            "status_key": job.status,
            "rejected_flag": job.rejected_flag,
            "paid": job.paid,
            "fully_invoiced": job.fully_invoiced,
            "speed_quality_tradeoff": job.speed_quality_tradeoff,
            "created_by_id": str(job.created_by_id) if job.created_by_id else None,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "delivery_date": (job.delivery_date.isoformat() if job.delivery_date else None),
            "priority": job.priority,
            "shop_job": job.company_id == context.shop_company_id,
            "over_budget": over_budget,
            "quote_revenue": quote_revenue,
            "time_and_materials_revenue": time_and_materials_revenue,
            "min_people": job.min_people,
            "max_people": job.max_people,
            "is_urgent": job.is_urgent,
            "badge_label": badge_info["label"],
            "badge_color": badge_info["color_class"],
        }

    @staticmethod
    def update_job_status(job_id: UUID, new_status: str, staff: Staff | None = None) -> bool:
        """Update a job's status, assigning the next priority for the column.

        Raises Job.DoesNotExist when the job is unknown.
        """
        try:
            job = Job.objects.get(pk=job_id)
        except Job.DoesNotExist:
            logger.error("Job %s not found for status update", job_id)
            raise
        job.status = new_status
        job.priority = Job._calculate_next_priority_for_status(new_status)
        job.save(staff=staff, update_fields=["status", "priority", "updated_at"])
        return True

    @staticmethod
    def get_reorder_anchor(anchor_job_id: str | None, target_status: str) -> Job | None:
        """Fetch and validate the visible anchor for a reorder request.

        Returns None when the request targets an empty visible list. Raises
        Job.DoesNotExist for an unknown anchor and ValueError when the anchor
        is not in the target status.
        """
        if not anchor_job_id:
            return None

        anchor = Job.objects.get(pk=anchor_job_id)
        if anchor.status != target_status:
            raise ValueError("Reorder anchor must be in the target status")

        return anchor

    @staticmethod
    def rebalance_column(status: str, staff: Staff | None) -> None:
        """Re-number priorities so the top card keeps the highest value.

        Values step down by Job.PRIORITY_INCREMENT.
        """
        increment = Job.PRIORITY_INCREMENT
        jobs = list(Job.objects.filter(status=status).order_by("-priority"))
        logger.info("Rebalancing column '%s' with %s jobs", status, len(jobs))

        with transaction.atomic():
            total = len(jobs)
            for index, job in enumerate(jobs, start=1):
                old_priority = job.priority
                # highest card gets total*increment, next gets (total-1)*increment, …
                job.priority = (total - index + 1) * increment
                job.save(staff=staff, update_fields=["priority", "updated_at"])
                logger.info(
                    "Job #%s priority updated: %s -> %s",
                    job.job_number,
                    old_priority,
                    job.priority,
                )

    @staticmethod
    def calculate_priority(
        status: str,
        staff: Staff | None,  # noqa: ARG004 -- v1 signature parity
        job_id: UUID,
        anchor: Job | None = None,
        placement: str | None = None,
    ) -> float:
        """Calculate the internal priority for a single-anchor reorder request."""
        increment = Job.PRIORITY_INCREMENT

        if anchor is None:
            max_prio = (
                Job.objects.filter(status=status)
                .exclude(pk=job_id)
                .aggregate(Max("priority"))["priority__max"]
                or 0
            )
            return float(max_prio + increment)

        if placement == "above":
            higher_job = (
                Job.objects.filter(status=status, priority__gt=anchor.priority)
                .exclude(pk=job_id)
                .order_by("priority")
                .first()
            )
            if higher_job:
                return (higher_job.priority + anchor.priority) / 2

            return anchor.priority + increment

        if placement == "below":
            lower_job = (
                Job.objects.filter(status=status, priority__lt=anchor.priority)
                .exclude(pk=job_id)
                .order_by("-priority")
                .first()
            )
            if lower_job:
                return (anchor.priority + lower_job.priority) / 2

            return anchor.priority - increment

        raise ValueError("placement must be 'above' or 'below'")

    @staticmethod
    def reorder_job(
        job_id: UUID,
        anchor_job_id: str | None = None,
        placement: str | None = None,
        new_status: str | None = None,
        staff: Staff | None = None,
    ) -> bool:
        """Reorder a job within or between columns.

        ``anchor_job_id`` is the visible job used as the destination anchor;
        ``placement`` places the moved job above or below it. Raises
        Job.DoesNotExist when the job or anchor is unknown, ValueError on an
        invalid anchor/placement combination.
        """
        try:
            job = Job.objects.get(pk=job_id)
        except Job.DoesNotExist:
            logger.error("Job %s not found for reordering", job_id)
            raise
        logger.info("Reordering job %s (current priority: %s)", job.job_number, job.priority)

        if anchor_job_id and str(anchor_job_id) == str(job_id):
            raise ValueError("Reorder anchor cannot be the moved job")
        if anchor_job_id and placement not in {"above", "below"}:
            raise ValueError("placement must be 'above' or 'below'")
        if placement and not anchor_job_id:
            raise ValueError("anchor_job_id is required when placement is supplied")

        # Determine target status for priority calculation
        target_status = new_status if new_status else job.status
        old_status = job.status
        old_priority = job.priority

        try:
            anchor = KanbanService.get_reorder_anchor(anchor_job_id, target_status)
        except Job.DoesNotExist:
            logger.error("Anchor job not found for reordering job %s", job_id)
            raise
        logger.info("Reorder anchor - job: %s, placement: %s", anchor_job_id, placement)

        # Calculate new priority
        new_priority = KanbanService.calculate_priority(
            target_status,
            staff,
            job_id,
            anchor=anchor,
            placement=placement,
        )
        logger.info(
            "Calculated new priority for job %s: %s (was %s)",
            job.job_number,
            new_priority,
            old_priority,
        )

        # Capture rank/total info for the priority_changed JobEvent. Computed
        # here (pre-save) where the column context and intent are already in
        # hand — the model layer just attaches whatever we hand it.
        priority_position = KanbanService._build_priority_position(
            job, old_status, old_priority, target_status, new_priority
        )

        job.priority = new_priority
        update_fields = ["priority"]

        if new_status and new_status != old_status:
            job.status = new_status
            update_fields.insert(0, "status")
            logger.info(
                "Job %s status changed from %s to %s", job.job_number, old_status, new_status
            )

        update_fields.append("updated_at")
        job.save(
            staff=staff,
            update_fields=update_fields,
            priority_position=priority_position,
        )
        logger.info("Job %s reordering completed successfully", job.job_number)
        return True

    @staticmethod
    def _build_priority_position(
        job: Job,
        old_status: str,
        old_priority: float,
        new_status: str,
        new_priority: float,
    ) -> dict[str, object]:
        """Snapshot rank/total in the affected column(s) for the JobEvent.

        Called pre-save: ``job`` is still at (old_status, old_priority) in the
        DB. Ranks are 1-based with 1 = highest priority float.
        """
        if old_status == new_status:
            total = Job.objects.filter(status=new_status).count()
            old_position = (
                Job.objects.filter(status=new_status, priority__gt=old_priority)
                .exclude(pk=job.pk)
                .count()
                + 1
            )
            new_position = (
                Job.objects.filter(status=new_status, priority__gt=new_priority)
                .exclude(pk=job.pk)
                .count()
                + 1
            )
            return {
                "old_status": old_status,
                "new_status": new_status,
                "old_position": old_position,
                "new_position": new_position,
                "old_total": total,
                "new_total": total,
            }

        # Cross-column: self counts in old column (pre-save) and will count in
        # new column (post-save).
        old_total = Job.objects.filter(status=old_status).count()
        old_position = (
            Job.objects.filter(status=old_status, priority__gt=old_priority)
            .exclude(pk=job.pk)
            .count()
            + 1
        )
        new_position = Job.objects.filter(status=new_status, priority__gt=new_priority).count() + 1
        new_total = Job.objects.filter(status=new_status).count() + 1
        return {
            "old_status": old_status,
            "new_status": new_status,
            "old_position": old_position,
            "new_position": new_position,
            "old_total": old_total,
            "new_total": new_total,
        }

    @staticmethod
    def _apply_advanced_text_filters(
        jobs_query: QuerySet[Job], filters: AdvancedSearchFilters
    ) -> QuerySet[Job]:
        """Apply the simple text/date filters of the advanced search."""
        if number := filters.get("job_number", "").strip():
            jobs_query = jobs_query.filter(job_number=number)

        if name := filters.get("name", "").strip():
            jobs_query = jobs_query.filter(name__icontains=name)

        if description := filters.get("description", "").strip():
            jobs_query = jobs_query.filter(description__icontains=description)

        if company_name := filters.get("company_name", "").strip():
            jobs_query = jobs_query.filter(company__name__icontains=company_name)

        if person_name := filters.get("person_name", "").strip():
            jobs_query = jobs_query.filter(person__name__icontains=person_name)

        if order_number := filters.get("order_number", "").strip():
            jobs_query = jobs_query.filter(order_number__icontains=order_number)

        if created_by := filters.get("created_by", "").strip():
            jobs_query = jobs_query.filter(events__staff__id=created_by)

        if created_after := filters.get("created_after", "").strip():
            jobs_query = jobs_query.filter(created_at__gte=created_after)

        if created_before := filters.get("created_before", "").strip():
            jobs_query = jobs_query.filter(created_at__lte=created_before)

        return jobs_query

    @staticmethod
    def _apply_advanced_flag_filters(
        jobs_query: QuerySet[Job], filters: AdvancedSearchFilters
    ) -> QuerySet[Job]:
        """Apply status/paid/rejected/invoice filters of the advanced search."""
        if statuses := filters.get("status", []):
            jobs_query = jobs_query.filter(status__in=statuses)

        if xero_invoice_params := filters.get("xero_invoice_params", "").strip():
            if xero_invoice_params.isdigit():
                xero_invoice_params = f"INV-{xero_invoice_params}"
            match xero_invoice_params:
                case param if _is_valid_uuid(param):
                    jobs_query = jobs_query.filter(invoices__xero_id=param)
                case param if _is_valid_invoice_number(param):
                    jobs_query = jobs_query.filter(invoices__number=param)
                case _:
                    jobs_query = Job.objects.none()

        match filters.get("paid", ""):
            case "true":
                jobs_query = jobs_query.filter(paid=True)
            case "false":
                jobs_query = jobs_query.filter(paid=False)

        match filters.get("rejected_flag", ""):
            case "true":
                jobs_query = jobs_query.filter(rejected_flag=True)
            case "false":
                jobs_query = jobs_query.filter(rejected_flag=False)

        return jobs_query

    @staticmethod
    def perform_advanced_search(filters: AdvancedSearchFilters) -> QuerySet[Job] | list[Job]:
        """Perform advanced search with multiple filters."""
        jobs_query: QuerySet[Job] = Job.objects.all()
        jobs_query = KanbanService._apply_advanced_text_filters(jobs_query, filters)
        jobs_query = KanbanService._apply_advanced_flag_filters(jobs_query, filters)

        if q := filters.get("universal_search", "").strip():
            return KanbanService._apply_kanban_search(jobs_query.distinct(), q)
        return jobs_query.distinct().order_by("-created_at")

    @staticmethod
    def get_jobs_by_kanban_column(
        column_id: str,
        max_jobs: int = 50,
        search_term: str = "",
        request: HttpRequest | None = None,
    ) -> KanbanColumnJobsData:
        """Get jobs by kanban column using the column taxonomy."""
        column = KanbanCategorizationService.get_column_by_id(column_id)
        if column is None:
            return {
                "success": False,
                "error": f"Invalid column: {column_id}",
                "jobs": [],
                "total": 0,
                "filtered_count": 0,
            }

        # Get valid statuses for this column (simplified approach - column = status)
        valid_statuses = [column.status_key]  # Only the column's main status
        jobs_query: QuerySet[Job] = Job.objects.filter(status__in=valid_statuses)
        jobs_query = KanbanService.filter_kanban_jobs(jobs_query)

        # Apply search filter if provided
        jobs: list[Job]
        if search_term:
            ranked_jobs = KanbanService._apply_kanban_search(jobs_query.distinct(), search_term)
            total_count = len(ranked_jobs)
            jobs = ranked_jobs[:max_jobs]
            KanbanService.log_kanban_search_results(
                request=request,
                source="column",
                query=search_term,
                jobs=list(jobs),
                filters={"status": valid_statuses},
                column_id=column_id,
            )
        else:
            total_count = jobs_query.count()
            jobs = list(jobs_query.order_by("-priority")[:max_jobs])
        logger.debug(
            "Jobs fetched for column %s (ordered by priority): %s",
            column_id,
            [job.job_number for job in jobs],
        )

        # Format jobs using the unified serializer
        formatted_jobs = KanbanService.serialize_jobs_for_api(jobs)

        return {
            "success": True,
            "jobs": formatted_jobs,
            "total": total_count,
            "filtered_count": len(formatted_jobs),
            "has_more": total_count > len(formatted_jobs),
        }

    @staticmethod
    def filter_kanban_jobs(jobs_query: QuerySet[Job]) -> QuerySet[Job]:
        """Filter jobs for kanban display — excludes 'special' status."""
        return jobs_query.exclude(status="special")
