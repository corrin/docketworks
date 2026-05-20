"""
Service layer for Kanban functionality.
Handles all business logic related to job management in the Kanban board.
"""

import json
import logging
import operator
from functools import reduce
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID, uuid4

from django.contrib.postgres.search import TrigramSimilarity, TrigramWordSimilarity
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import (
    Case,
    ExpressionWrapper,
    F,
    FloatField,
    Max,
    Q,
    QuerySet,
    TextField,
    Value,
    When,
)
from django.db.models.functions import Cast, Coalesce, Greatest
from django.http import HttpRequest

from apps.job.models import Job
from apps.job.services.kanban_categorization_service import KanbanCategorizationService
from apps.workflow.utils import is_valid_invoice_number, is_valid_uuid

logger = logging.getLogger(__name__)
search_logger = logging.getLogger("kanban_search")


class KanbanService:
    """Service class for Kanban business logic."""

    KANBAN_TRIGRAM_THRESHOLD = 0.3
    SEARCH_SCORE_EXACT_JOB_NUMBER = 100.0
    SEARCH_SCORE_JOB_NUMBER_SUFFIX = 85.0
    SEARCH_SCORE_JOB_NUMBER_CONTAINS = 45.0
    SEARCH_SCORE_QUOTE_CONTAINS = 75.0
    SEARCH_SCORE_NAME_CONTAINS = 65.0
    SEARCH_SCORE_CLIENT_CONTAINS = 55.0
    SEARCH_SCORE_CONTACT_CONTAINS = 55.0
    SEARCH_SCORE_DESCRIPTION_CONTAINS = 35.0
    SEARCH_SCORE_TRIGRAM_MULTIPLIER = 30.0
    SEARCH_SCORE_FALLBACK_RATIO = 0.5
    SEARCH_SCORE_MIN_DISPLAY = 15.0

    @staticmethod
    def get_jobs_by_status(
        status: str,
        search_terms: Optional[List[str]] = None,
        limit: int = 200,
        request: Optional[HttpRequest] = None,
    ) -> Union[QuerySet[Job], List[Job]]:
        """
        Get jobs filtered by status and optional search terms.

        Args:
            status: Job status to filter by
            search_terms: List of search terms to filter jobs
            limit: Maximum number of jobs to return

        Returns:
            QuerySet of filtered jobs
        """
        jobs_query = Job.objects.filter(status=status)

        if search_terms:
            search_query = " ".join(search_terms)
            jobs_query = KanbanService._apply_kanban_search(jobs_query, search_query)
            jobs = jobs_query
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
            f"Jobs fetched by status '{status}' ({ordering_description}): {[f'#{job.job_number}(p:{job.priority})' for job in jobs[:10]]}"
        )

        # Apply different limits based on status
        match status:
            case "archived":
                return jobs[:100]
            case _:
                return jobs[:limit]

    @staticmethod
    def _apply_kanban_search(jobs_query: QuerySet[Job], query: str) -> List[Job]:
        normalized_query = query.strip()
        if not normalized_query:
            return list(jobs_query)

        tokens = normalized_query.split()
        searchable_fields = [
            (
                "name",
                Coalesce("name", Value(""), output_field=TextField()),
            ),
            (
                "client__name",
                Coalesce("client__name", Value(""), output_field=TextField()),
            ),
            (
                "contact__name",
                Coalesce("contact__name", Value(""), output_field=TextField()),
            ),
            (
                "description",
                Coalesce("description", Value(""), output_field=TextField()),
            ),
            (
                "job_number",
                Coalesce(
                    Cast("job_number", output_field=TextField()),
                    Value(""),
                    output_field=TextField(),
                ),
            ),
            (
                "quote__number",
                Coalesce("quote__number", Value(""), output_field=TextField()),
            ),
        ]

        annotations: Dict[str, Any] = {}
        token_aliases: List[str] = []
        for index, token in enumerate(tokens):
            alias = f"search_token_score_{index}"
            substring_whens = [
                When(**{f"{lookup}__icontains": token}, then=Value(1.0))
                for lookup, _ in searchable_fields
                if lookup != "job_number"
            ]
            field_scores = [
                TrigramSimilarity(expression, token)
                for _, expression in searchable_fields
            ] + [
                TrigramWordSimilarity(token, expression)
                for _, expression in searchable_fields
            ]
            annotations[alias] = Greatest(
                Case(
                    *substring_whens,
                    default=Value(0.0),
                    output_field=FloatField(),
                ),
                *field_scores,
            )
            token_aliases.append(alias)

        jobs_query = jobs_query.annotate(**annotations)

        token_filter = Q()
        for alias in token_aliases:
            token_filter &= Q(
                **{f"{alias}__gte": KanbanService.KANBAN_TRIGRAM_THRESHOLD}
            )

        combined_score = reduce(operator.add, (F(alias) for alias in token_aliases))
        jobs_query = jobs_query.annotate(
            trigram_score=ExpressionWrapper(
                combined_score / Value(len(token_aliases)),
                output_field=FloatField(),
            )
        )

        candidates = list(
            jobs_query.filter(token_filter)
            .select_related("client", "contact", "quote")
            .order_by("-trigram_score", "-created_at")
        )
        return KanbanService._rank_kanban_search_candidates(
            candidates, normalized_query
        )

    @staticmethod
    def _rank_kanban_search_candidates(candidates: List[Job], query: str) -> List[Job]:
        scored_jobs = []
        for job in candidates:
            score, reasons = KanbanService._score_kanban_search_candidate(job, query)
            setattr(job, "search_score", score)
            setattr(job, "search_reasons", reasons)
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

        return [
            job
            for job in scored_jobs
            if getattr(job, "search_score", 0.0) >= score_floor
        ]

    @staticmethod
    def _score_kanban_search_candidate(
        job: Job, query: str
    ) -> Tuple[float, Dict[str, Any]]:
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
    def _score_kanban_search_token(
        job: Job, token: str
    ) -> Tuple[float, Dict[str, Any]]:
        job_number = str(job.job_number)
        name = (job.name or "").lower()
        client_name = (job.client.name if job.client_id and job.client else "").lower()
        contact_name = (
            job.contact.name if job.contact_id and job.contact else ""
        ).lower()
        description = (job.description or "").lower()
        quote_number = KanbanService._job_quote_number(job).lower()
        trigram_score = float(getattr(job, "trigram_score", 0.0) or 0.0)

        scored_reasons = [
            (
                (
                    KanbanService.SEARCH_SCORE_EXACT_JOB_NUMBER
                    if job_number == token
                    else 0.0
                ),
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
            (
                (
                    KanbanService.SEARCH_SCORE_JOB_NUMBER_CONTAINS
                    if token in job_number
                    else 0.0
                ),
                "job_number_contains",
            ),
            (
                (
                    KanbanService.SEARCH_SCORE_QUOTE_CONTAINS
                    if token in quote_number
                    else 0.0
                ),
                "quote_contains",
            ),
            (
                KanbanService.SEARCH_SCORE_NAME_CONTAINS if token in name else 0.0,
                "name_contains",
            ),
            (
                (
                    KanbanService.SEARCH_SCORE_CLIENT_CONTAINS
                    if token in client_name
                    else 0.0
                ),
                "client_contains",
            ),
            (
                (
                    KanbanService.SEARCH_SCORE_CONTACT_CONTAINS
                    if token in contact_name
                    else 0.0
                ),
                "contact_contains",
            ),
            (
                (
                    KanbanService.SEARCH_SCORE_DESCRIPTION_CONTAINS
                    if token in description
                    else 0.0
                ),
                "description_contains",
            ),
            (
                trigram_score * KanbanService.SEARCH_SCORE_TRIGRAM_MULTIPLIER,
                "trigram",
            ),
        ]
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
    def explain_kanban_search(query: str, limit: int = 20) -> List[Dict[str, Any]]:
        jobs = KanbanService._apply_kanban_search(Job.objects.all(), query)
        return [
            {
                "job_number": job.job_number,
                "name": job.name,
                "client": job.client.name if job.client_id else None,
                "status": job.status,
                "trigram_score": getattr(job, "trigram_score", None),
                "search_score": getattr(job, "search_score", None),
                "search_reasons": getattr(job, "search_reasons", None),
            }
            for job in jobs[:limit]
        ]

    @staticmethod
    def log_kanban_search_results(
        *,
        request: Optional[HttpRequest],
        source: str,
        query: str,
        jobs: List[Job],
        filters: Optional[Dict[str, Any]] = None,
        column_id: Optional[str] = None,
    ) -> None:
        if not query.strip():
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
            "query_string": (
                request.META.get("QUERY_STRING", "") if request is not None else ""
            ),
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
                    "client": job.client.name if job.client_id else None,
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
        """
        Get all active (non-archived) jobs, filtered for kanban display,
        ordered by priority only.
        """
        # Get non-archived jobs and filter out special jobs for kanban
        active_jobs = Job.objects.exclude(status="archived").order_by("-priority")
        filtered_jobs = KanbanService.filter_kanban_jobs(active_jobs)
        logger.info(
            f"Active jobs fetched (ordered by priority desc): {[f'#{job.job_number}(p:{job.priority})' for job in filtered_jobs[:10]]}"
        )
        return filtered_jobs

    @staticmethod
    def get_archived_jobs(limit: int = 50) -> QuerySet[Job]:
        """Get archived jobs with limit."""
        return Job.objects.filter(status="archived").order_by("-created_at")[:limit]

    @staticmethod
    def get_status_choices() -> Dict[str, Any]:
        """Get available status choices and tooltips using new categorization."""
        categorization_service = KanbanCategorizationService

        # Get all kanban columns instead of individual statuses
        columns = categorization_service.get_all_columns()

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
    def serialize_job_for_api(job: Job, request: HttpRequest = None) -> Dict[str, Any]:
        """
        Serialize a job object for API response.

        Args:
            job: Job instance to serialize
            request: HTTP request for building absolute URIs (optional, not used)

        Returns:
            Dictionary representation of the job
        """
        # Get badge info
        badge_info = KanbanCategorizationService.get_badge_info(job.status)

        # Precomputed revenue totals from CostSet summaries
        if not job.latest_quote_id:
            raise ValueError(f"Job #{job.job_number} has no quote CostSet")
        if not job.latest_actual_id:
            raise ValueError(f"Job #{job.job_number} has no actual CostSet")
        quote_revenue = job.latest_quote.summary["rev"]
        time_and_materials_revenue = job.latest_actual.summary["rev"]

        if job.pricing_methodology == "time_materials" and job.price_cap is not None:
            over_budget = float(
                job.price_cap
            ) > 0 and time_and_materials_revenue > float(job.price_cap)
        else:
            over_budget = (
                quote_revenue > 0 and time_and_materials_revenue > quote_revenue
            )

        return {
            "id": str(job.id),
            "name": job.name,
            "description": job.description or "",
            "job_number": job.job_number,
            "client_name": job.client.name if job.client else "",
            "contact_person": job.contact.name if job.contact else "",
            "people": [
                {
                    "id": str(staff.id),
                    "display_name": staff.get_display_full_name(),
                    "icon_url": staff.icon.url if staff.icon else None,
                }
                for staff in job.people.all()
            ],
            "status": job.get_status_display(),
            "status_key": job.status,
            "rejected_flag": job.rejected_flag,
            "paid": job.paid,
            "fully_invoiced": job.fully_invoiced,
            "speed_quality_tradeoff": job.speed_quality_tradeoff,
            "created_by_id": str(job.created_by.id) if job.created_by else None,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "delivery_date": (
                job.delivery_date.isoformat() if job.delivery_date else None
            ),
            "priority": job.priority,
            "shop_job": job.shop_job,
            "over_budget": over_budget,
            "quote_revenue": quote_revenue,
            "time_and_materials_revenue": time_and_materials_revenue,
            "min_people": job.min_people,
            "max_people": job.max_people,
            "badge_label": badge_info["label"],
            "badge_color": badge_info["color_class"],
        }

    @staticmethod
    def update_job_status(job_id: UUID, new_status: str, staff=None) -> bool:
        """
        Update job status.

        Args:
            job_id: UUID of the job to update
            new_status: New status value
            staff: Staff member making the change

        Returns:
            True if successful, False otherwise

        Raises:
            Job.DoesNotExist: If job not found
        """
        try:
            job = Job.objects.get(pk=job_id)
            job.status = new_status
            job.priority = Job._calculate_next_priority_for_status(new_status)
            job.save(staff=staff, update_fields=["status", "priority", "updated_at"])
            return True
        except Job.DoesNotExist:
            logger.error(f"Job {job_id} not found for status update")
            raise

    @staticmethod
    def get_adjacent_priorities(
        before_id: Optional[str], after_id: Optional[str]
    ) -> Tuple[Optional[int], Optional[int]]:
        """
        Get priorities of adjacent jobs.

        Args:
            before_id: ID of job before the target position
            after_id: ID of job after the target position

        Returns:
            Tuple of (before_priority, after_priority)

        Raises:
            Job.DoesNotExist: If referenced job not found
        """
        before_prio = None
        after_prio = None

        if before_id:
            before_prio = Job.objects.get(pk=before_id).priority
        if after_id:
            after_prio = Job.objects.get(pk=after_id).priority

        return before_prio, after_prio

    @staticmethod
    def rebalance_column(status: str, staff) -> None:
        """
        Re-number priorities so that the top card keeps the highest value
        and values step down by Job.PRIORITY_INCREMENT.
        """
        increment = Job.PRIORITY_INCREMENT
        jobs = list(Job.objects.filter(status=status).order_by("-priority"))
        logger.info(f"Rebalancing column '{status}' with {len(jobs)} jobs")

        with transaction.atomic():
            total = len(jobs)
            for index, job in enumerate(jobs, start=1):
                old_priority = job.priority
                # highest card gets total*increment, next gets (total-1)*increment, …
                job.priority = (total - index + 1) * increment
                job.save(staff=staff, update_fields=["priority", "updated_at"])
                logger.info(
                    f"Job #{job.job_number} priority updated: {old_priority} -> {job.priority}"
                )

    @staticmethod
    def calculate_priority(
        before_prio: Optional[int],
        after_prio: Optional[int],
        status: str,
        staff,
        before_id: Optional[str] = None,
        after_id: Optional[str] = None,
    ) -> int:
        increment = Job.PRIORITY_INCREMENT
        match (before_prio, after_prio):
            case (None, None):
                max_prio = (
                    Job.objects.filter(status=status).aggregate(Max("priority"))[
                        "priority__max"
                    ]
                    or 0
                )
                return max_prio + increment

            case (None, after) if after is not None:
                # Insert at top: place above the current highest-priority job
                new_prio = after + increment
                return new_prio

            case (before, None) if before is not None:
                # Insert at bottom: place just below the 'before' job
                return before + increment

            case (before, after) if before is not None and after is not None:
                gap = after - before
                if gap > 1:
                    return (before + after) // 2

                # Gap too small → rebalance first, then recompute
                KanbanService.rebalance_column(status, staff)

                new_before_prio = Job.objects.get(pk=before_id).priority
                new_after_prio = Job.objects.get(pk=after_id).priority
                return (new_before_prio + new_after_prio) // 2

            case _:
                max_prio = (
                    Job.objects.filter(status=status).aggregate(Max("priority"))[
                        "priority__max"
                    ]
                    or 0
                )
                return max_prio + increment

    @staticmethod
    def reorder_job(
        job_id: UUID,
        before_id: Optional[str] = None,
        after_id: Optional[str] = None,
        new_status: Optional[str] = None,
        staff=None,
    ) -> bool:
        """
        Reorder a job within or between columns.

        Args:
            job_id: UUID of job to reorder
            before_id: ID of job before target position
            after_id: ID of job after target position
            new_status: New status if moving between columns

        Returns:
            True if successful

        Raises:
            Job.DoesNotExist: If job not found
        """
        try:
            job = Job.objects.get(pk=job_id)
            logger.info(
                f"Reordering job {job.job_number} (current priority: {job.priority})"
            )
        except Job.DoesNotExist:
            logger.error(f"Job {job_id} not found for reordering")
            raise

        try:
            before_prio, after_prio = KanbanService.get_adjacent_priorities(
                before_id, after_id
            )
            logger.info(
                f"Adjacent priorities - before: {before_prio}, after: {after_prio}"
            )
        except Job.DoesNotExist:
            logger.error(f"Adjacent job not found for reordering job {job_id}")
            raise

        # Determine target status for priority calculation
        target_status = new_status if new_status else job.status
        old_status = job.status
        old_priority = job.priority

        # Calculate new priority
        new_priority = KanbanService.calculate_priority(
            before_prio, after_prio, target_status, staff, before_id, after_id
        )
        logger.info(
            f"Calculated new priority for job {job.job_number}: {new_priority} (was {old_priority})"
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
                f"Job {job.job_number} status changed from {old_status} to {new_status}"
            )

        update_fields.append("updated_at")
        job.save(
            staff=staff,
            update_fields=update_fields,
            priority_position=priority_position,
        )
        logger.info(f"Job {job.job_number} reordering completed successfully")
        return True

    @staticmethod
    def _build_priority_position(
        job, old_status: str, old_priority, new_status: str, new_priority
    ) -> Dict[str, Any]:
        """Snapshot rank/total in the affected column(s) for the JobEvent.

        Called pre-save: `job` is still at (old_status, old_priority) in DB.
        Ranks are 1-based with 1 = highest priority float.
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
        new_position = (
            Job.objects.filter(status=new_status, priority__gt=new_priority).count() + 1
        )
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
    def perform_advanced_search(
        filters: Dict[str, Any],
    ) -> Union[QuerySet[Job], List[Job]]:
        """
        Perform advanced search with multiple filters.

        Args:
            filters: Dictionary of search filters

        Returns:
            QuerySet of filtered jobs
        """
        jobs_query = Job.objects.all()
        logger.info(f"Performing advanced search with filters: {filters}")

        # Apply filters with early returns for invalid data
        if number := filters.get("job_number", "").strip():
            jobs_query = jobs_query.filter(job_number=number)

        if name := filters.get("name", "").strip():
            jobs_query = jobs_query.filter(name__icontains=name)

        if description := filters.get("description", "").strip():
            jobs_query = jobs_query.filter(description__icontains=description)

        if client_name := filters.get("client_name", "").strip():
            jobs_query = jobs_query.filter(client__name__icontains=client_name)

        if contact_person := filters.get("contact_person", "").strip():
            jobs_query = jobs_query.filter(contact__name__icontains=contact_person)

        if created_by := filters.get("created_by", "").strip():
            jobs_query = jobs_query.filter(events__staff=created_by)

        if created_after := filters.get("created_after", "").strip():
            jobs_query = jobs_query.filter(created_at__gte=created_after)

        if created_before := filters.get("created_before", "").strip():
            jobs_query = jobs_query.filter(created_at__lte=created_before)

        if statuses := filters.get("status", []):
            jobs_query = jobs_query.filter(status__in=statuses)

        if xero_invoice_params := filters.get("xero_invoice_params", "").strip():
            match xero_invoice_params:
                case param if is_valid_uuid(param):
                    jobs_query = jobs_query.filter(invoices__xero_id=param)
                case param if is_valid_invoice_number(param):
                    jobs_query = jobs_query.filter(invoices__number=param)

        # Handle paid filter with match-case
        paid_filter = filters.get("paid", "")
        match paid_filter:
            case "true":
                jobs_query = jobs_query.filter(paid=True)
            case "false":
                jobs_query = jobs_query.filter(paid=False)

        # Handle rejected_flag filter with match-case
        rejected_flag_filter = filters.get("rejected_flag", "")
        match rejected_flag_filter:
            case "true":
                jobs_query = jobs_query.filter(rejected_flag=True)
            case "false":
                jobs_query = jobs_query.filter(rejected_flag=False)

        if q := filters.get("universal_search", "").strip():
            return KanbanService._apply_kanban_search(jobs_query.distinct(), q)
        return jobs_query.distinct().order_by("-created_at")

    @staticmethod
    def get_jobs_by_kanban_column(
        column_id: str,
        max_jobs: int = 50,
        search_term: str = "",
        request: Optional[HttpRequest] = None,
    ) -> Dict[str, Any]:
        """Get jobs by kanban column using new categorization system."""
        categorization_service = KanbanCategorizationService

        # Early return for invalid column
        if column_id not in [
            col.column_id for col in categorization_service.get_all_columns()
        ]:
            return {
                "success": False,
                "error": f"Invalid column: {column_id}",
                "jobs": [],
                "total": 0,
                "filtered_count": 0,
            }

        try:
            # Get column information
            column = categorization_service.get_column_by_id(column_id)
            if not column:
                return {
                    "success": False,
                    "error": "Column not found",
                    "jobs": [],
                    "total": 0,
                    "filtered_count": 0,
                }

            # Get valid statuses for this column (simplified approach - column = status)
            valid_statuses = [column.status_key]  # Only the column's main status
            jobs_query = (
                Job.objects.filter(status__in=valid_statuses)
                .select_related("client", "latest_quote", "latest_actual")
                .prefetch_related("people")
            )
            jobs_query = KanbanService.filter_kanban_jobs(jobs_query)

            # Apply search filter if provided
            if search_term:
                ranked_jobs = KanbanService._apply_kanban_search(
                    jobs_query.distinct(), search_term
                )
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
                # Get total count
                total_count = jobs_query.count()

                # Apply limit and ordering
                jobs = jobs_query.order_by("-priority")[:max_jobs]
            logger.debug(
                f"Jobs fetched for column {column_id} (ordered by priority): {[job.job_number for job in jobs]}"
            )

            # Format jobs using the unified serializer
            formatted_jobs = [KanbanService.serialize_job_for_api(job) for job in jobs]
            logger.debug(
                f"Formatted jobs for column {column_id}: {[job['job_number'] for job in formatted_jobs]}"
            )

            return {
                "success": True,
                "jobs": formatted_jobs,
                "total": total_count,
                "filtered_count": len(formatted_jobs),
                "has_more": total_count > len(formatted_jobs),
            }

        except Exception as e:
            logger.error(f"Error getting jobs for column {column_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "jobs": [],
                "total": 0,
                "filtered_count": 0,
            }

    @staticmethod
    def filter_kanban_jobs(jobs_query):
        """
        Filter jobs for kanban display - excludes 'special' status

        Args:
            jobs_query: QuerySet of jobs to filter

        Returns:
            Filtered QuerySet excluding special jobs
        """
        return jobs_query.exclude(status="special")
