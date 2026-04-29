"""
Service layer for Kanban functionality.
Handles all business logic related to job management in the Kanban board.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from django.db import transaction
from django.db.models import Max, Q, QuerySet
from django.http import HttpRequest

from apps.job.models import Job
from apps.job.services.kanban_categorization_service import KanbanCategorizationService
from apps.workflow.utils import is_valid_invoice_number, is_valid_uuid

logger = logging.getLogger(__name__)


class KanbanService:
    """Service class for Kanban business logic."""

    @staticmethod
    def get_jobs_by_status(
        status: str, search_terms: Optional[List[str]] = None, limit: int = 200
    ) -> QuerySet[Job]:
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
            query = Q()
            for term in search_terms:
                term_query = (
                    Q(name__icontains=term)
                    | Q(description__icontains=term)
                    | Q(client__name__icontains=term)
                    | Q(contact__name__icontains=term)
                    | Q(created_by__email__icontains=term)
                )
                query &= term_query
            jobs_query = jobs_query.filter(query)

        jobs = jobs_query.order_by("-priority", "-created_at")
        logger.info(
            f"Jobs fetched by status '{status}' (ordered by priority desc): {[f'#{job.job_number}(p:{job.priority})' for job in jobs[:10]]}"
        )

        # Apply different limits based on status
        match status:
            case "archived":
                return jobs[:100]
            case _:
                return jobs[:limit]

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
        over_budget = quote_revenue > 0 and time_and_materials_revenue > quote_revenue

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
    def perform_advanced_search(filters: Dict[str, Any]) -> QuerySet[Job]:
        """
        Perform advanced search with multiple filters.

        Args:
            filters: Dictionary of search filters

        Returns:
            QuerySet of filtered jobs
        """
        jobs_query = Job.objects.all()
        logger.info(f"Performing advanced search with filters: {filters}")

        # Universal search - searches across multiple fields with OR logic
        if q := filters.get("universal_search", "").strip():
            jobs_query = jobs_query.filter(
                Q(name__icontains=q)
                | Q(job_number__icontains=q)
                | Q(description__icontains=q)
                | Q(client__name__icontains=q)
                | Q(invoices__number__icontains=q)
                | Q(quote__number__icontains=q)
            )

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

        return jobs_query.distinct().order_by("-created_at")

    @staticmethod
    def get_jobs_by_kanban_column(
        column_id: str, max_jobs: int = 50, search_term: str = ""
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
                search_query = (
                    Q(name__icontains=search_term)
                    | Q(job_number__icontains=search_term)
                    | Q(description__icontains=search_term)
                    | Q(client__name__icontains=search_term)
                )
                jobs_query = jobs_query.filter(search_query)

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
