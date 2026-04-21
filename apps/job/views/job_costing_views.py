"""
Job Costing REST Views

REST views for the Job costing system to expose CostSet data
"""

import logging
from datetime import datetime

from django.db import transaction
from django.db.models import Case, IntegerField, Prefetch, Value, When
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.models import Job
from apps.job.models.costing import CostLine, CostSet
from apps.job.permissions import IsOfficeStaff
from apps.job.serializers import CostSetSerializer
from apps.job.serializers.costing_serializer import (
    QuoteRevisionResponseSerializer,
    QuoteRevisionSerializer,
    QuoteRevisionsListSerializer,
)

logger = logging.getLogger(__name__)


KIND_ORDER = Case(
    When(kind="material", then=Value(1)),
    When(kind="adjust", then=Value(2)),
    When(kind="time", then=Value(3)),
    default=Value(999),
    output_field=IntegerField(),
)


class JobCostSetView(APIView):
    """
    Retrieve the latest CostSet for a specific job and kind.

    GET /jobs/<pk>/cost_sets/<kind>/

    Returns the latest CostSet of the specified kind (estimate|quote|actual)
    for the given job, or 404 if not found.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CostSetSerializer

    def get(self, request, pk, kind):
        """
        Get the latest CostSet for a job by kind.

        Args:
            pk: Job primary key (UUID)
            kind: CostSet kind ('estimate', 'quote', or 'actual')

        Returns:
            Response: Serialized CostSet data or 404
        """
        # Validate kind parameter
        valid_kinds = ["estimate", "quote", "actual"]
        if kind not in valid_kinds:
            return Response(
                {"error": f"Invalid kind. Must be one of: {', '.join(valid_kinds)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get the job
        job = get_object_or_404(Job, id=pk)

        # Get the latest CostSet using the job's helper method
        cost_set = (
            CostSet.objects.filter(job=job, kind=kind)
            .prefetch_related(
                Prefetch(
                    "cost_lines",
                    queryset=CostLine.objects.order_by(
                        KIND_ORDER, "-created_at", "-id"
                    ),
                )
            )
            .first()
        )

        if cost_set is None:
            return Response(
                {"error": f"No {kind} cost set found for this job"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Serialize and return the cost set
        serializer = CostSetSerializer(cost_set)
        return Response(serializer.data, status=status.HTTP_200_OK)


class JobQuoteRevisionView(APIView):
    """
    Manage quote revisions for jobs.

    GET /jobs/<job_id>/cost_sets/quote/revise/
    Returns the list of archived quote revisions from the CostSet summary.

    POST /jobs/<job_id>/cost_sets/quote/revise/
    Create a new quote revision by archiving current quote data and clearing cost lines.

    This endpoint:
    1. Archives current quote cost lines and summary in the existing CostSet summary
    2. Clears all current cost lines from the quote CostSet
    3. Uses quote_revision numbering for tracking
    4. Allows starting fresh quote while preserving historical data

    Only works with kind='quote' CostSets.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = QuoteRevisionSerializer

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsOfficeStaff()]

    @extend_schema(
        summary="List archived quote revisions",
        description="Returns a list of archived quote revisions for the specified job. Each revision contains summary and cost line data as archived at the time of revision.",
        responses={200: QuoteRevisionsListSerializer},
    )
    def get(self, request, job_id):
        """
        Get the list of archived quote revisions for the specified job.

        Args:
            job_id: Job primary key (UUID)

        Returns:
            Response: List of archived quote revisions or empty list
        """
        job = get_object_or_404(Job, id=job_id)

        # Get the current quote CostSet
        current_quote = job.get_latest("quote")
        if current_quote is None:
            return Response(
                {"error": "No quote found for this job."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Get revisions from summary
        summary = current_quote.summary or {}
        revisions = summary.get("revisions", [])

        # Prepare response data
        response_data = {
            "job_id": str(job.id),
            "job_number": job.job_number,
            "current_cost_set_rev": current_quote.rev,
            "total_revisions": len(revisions),
            "revisions": revisions,
        }

        serializer = QuoteRevisionsListSerializer(response_data)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Create a new quote revision",
        description=(
            "Archives the current quote cost lines and summary for the specified job, "
            "clears all current cost lines from the quote CostSet, and starts a new quote revision. "
            "Returns details of the archived revision and status."
        ),
        request=QuoteRevisionSerializer,
        responses={200: QuoteRevisionResponseSerializer},
    )
    def post(self, request, job_id):
        """
        Create a new quote revision for the specified job.

        Args:
            job_id: Job primary key (UUID)

        Request Body:
            reason (optional): String reason for the revision

        Returns:
            Response: Success/error details and revision information
        """
        # Validate request data
        request_serializer = QuoteRevisionSerializer(data=request.data)
        if not request_serializer.is_valid():
            return Response(
                {"error": "Invalid request data", "details": request_serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get the job
        job = get_object_or_404(Job, id=job_id)

        # Get the current quote CostSet
        current_quote = job.get_latest("quote")
        if current_quote is None:
            return Response(
                {"error": "No quote found for this job. Cannot create revision."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check if there are any cost lines to archive
        cost_lines = list(current_quote.cost_lines.all())
        if not cost_lines:
            return Response(
                {"error": "No cost lines found in current quote. Nothing to revise."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                # Archive current quote data in summary
                archived_data = self._archive_quote_data(
                    current_quote,
                    cost_lines,
                    request_serializer.validated_data.get("reason"),
                )

                # Clear current cost lines
                current_quote.cost_lines.all().delete()[0]

                # Reset quote acceptance date to allow accepting the new quote revision
                job.quote_acceptance_date = None
                job.save(staff=request.user)

                # Save the CostSet (summary was updated in _archive_quote_data)
                current_quote.save()

                logger.info(
                    f"Quote revision created for job {job.job_number}: "
                    f"Quote revision {archived_data['quote_revision']}, "
                    f"archived {len(cost_lines)} cost lines, "
                    f"reset quote acceptance date"
                )

                # Prepare response
                response_data = {
                    "success": True,
                    "message": "Quote revision created successfully. Ready for new quote.",
                    "quote_revision": archived_data["quote_revision"],
                    "archived_cost_lines_count": len(cost_lines),
                    "job_id": str(job.id),
                }

                serializer = QuoteRevisionResponseSerializer(response_data)
                return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(
                f"Error creating quote revision for job {job.job_number}: {str(e)}"
            )
            return Response(
                {
                    "success": False,
                    "error": f"Failed to create quote revision: {str(e)}",
                    "job_id": str(job.id),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _archive_quote_data(self, cost_set, cost_lines, reason=None):
        """
        Archive current quote data in the CostSet summary.

        Args:
            cost_set: Current CostSet instance
            cost_lines: List of CostLine instances to archive
            reason: Optional reason for the revision

        Returns:
            dict: The archived data structure
        """
        # Get current summary or initialize
        current_summary = cost_set.summary or {}

        # Initialize revisions list if not exists
        if "revisions" not in current_summary:
            current_summary["revisions"] = []

        # Calculate next quote revision number
        next_quote_revision = len(current_summary["revisions"]) + 1

        # Calculate totals from cost lines
        total_cost = sum(line.total_cost for line in cost_lines)
        total_rev = sum(line.total_rev for line in cost_lines)
        total_hours = sum(line.quantity for line in cost_lines if line.kind == "time")

        # Create archived revision data
        archived_revision = {
            "quote_revision": next_quote_revision,
            "archived_at": datetime.now().isoformat(),
            "reason": reason,
            "summary": {
                "cost": float(total_cost),
                "rev": float(total_rev),
                "hours": float(total_hours),
            },
            "cost_lines": [
                {
                    "id": str(line.id),
                    "kind": line.kind,
                    "desc": line.desc,
                    "quantity": float(line.quantity),
                    "unit_cost": float(line.unit_cost),
                    "unit_rev": float(line.unit_rev),
                    "total_cost": float(line.total_cost),
                    "total_rev": float(line.total_rev),
                    "ext_refs": line.ext_refs,
                    "meta": line.meta,
                }
                for line in cost_lines
            ],
        }

        # Add to revisions list
        current_summary["revisions"].append(archived_revision)

        # Clear current summary totals (start fresh for new quote)
        current_summary.update(
            {
                "cost": 0.0,
                "rev": 0.0,
                "hours": 0.0,
            }
        )

        # Save updated summary
        cost_set.summary = current_summary
        cost_set.save()

        return archived_revision
