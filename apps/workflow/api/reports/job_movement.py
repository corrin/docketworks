"""
Job Movement Metrics API

Provides metrics for management meetings focused on job lifecycle and conversion:
- Draft jobs created (leads converted from Excel)
- Quotes submitted (moved to Awaiting Approval)
- Quote acceptance rates
- Jobs won (draft → working/completed)
- Workflow path analysis
"""

from datetime import datetime, timedelta

from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.models import Job, JobEvent


class JobMovementMetricsView(APIView):
    """
    API endpoint for job movement and conversion metrics.

    Query Parameters:
        start_date (required): ISO date string (YYYY-MM-DD)
        end_date (required): ISO date string (YYYY-MM-DD)
        compare_start_date (optional): Comparison period start
        compare_end_date (optional): Comparison period end
        baseline_days (optional): Number of days to calculate baseline averages over
                                  (e.g., 365 for yearly baseline). Returns weekly averages.
        include_details (optional, default=false): Include job listings with IDs

    Returns:
        JSON response with metrics and optional job details
    """

    def get_draft_jobs_created(self, start_date, end_date):
        """
        Get draft jobs created in the period.
        These represent leads that were converted from Excel into the system.

        Returns:
            QuerySet of Job objects
        """
        return Job.objects.filter(
            created_at__gte=start_date, created_at__lte=end_date
        ).select_related("client", "created_by")

    def get_quotes_submitted(self, start_date, end_date):
        """
        Get quotes submitted in the period.
        A quote is submitted when a job moves to 'awaiting_approval' status.

        Returns:
            QuerySet of JobEvent objects
        """
        return JobEvent.objects.filter(
            event_type="status_changed",
            timestamp__gte=start_date,
            timestamp__lte=end_date,
            delta_after__status="awaiting_approval",
        ).select_related("job", "staff")

    def get_quotes_accepted(self, start_date, end_date):
        """
        Get quotes accepted in the period.
        A quote is accepted when job moves from awaiting_approval to approved.

        Returns:
            QuerySet of JobEvent objects
        """
        return JobEvent.objects.filter(
            event_type="status_changed",
            timestamp__gte=start_date,
            timestamp__lte=end_date,
            delta_after__status="approved",
        ).select_related("job", "staff")

    def get_jobs_won(self, start_date, end_date):
        """
        Get jobs won in the period.
        A job is "won" if it was created in this period and moved beyond draft
        to any working/completed status (not rejected).

        Returns:
            dict with won jobs data
        """
        # All jobs created in period
        all_jobs = self.get_draft_jobs_created(start_date, end_date)

        # Jobs still in draft
        still_draft = all_jobs.filter(status="draft")

        # Jobs that progressed beyond draft (won)
        won_jobs = all_jobs.exclude(status="draft").exclude(rejected_flag=True)

        # Jobs that were rejected
        rejected_jobs = all_jobs.filter(rejected_flag=True)

        return {
            "total_created": all_jobs.count(),
            "still_draft": still_draft,
            "still_draft_count": still_draft.count(),
            "won_jobs": won_jobs,
            "won_count": won_jobs.count(),
            "rejected_jobs": rejected_jobs,
            "rejected_count": rejected_jobs.count(),
        }

    def get_jobs_by_status_path(self, start_date, end_date):
        """
        Categorize jobs by their path through the system.

        Returns:
            dict with jobs categorized by path
        """
        all_jobs = Job.objects.filter(
            created_at__gte=start_date, created_at__lte=end_date
        )

        # Check which jobs went through quote process
        jobs_through_quotes = set()
        quote_events = JobEvent.objects.filter(
            event_type="status_changed",
            timestamp__gte=start_date,
            timestamp__lte=end_date,
            delta_after__status="awaiting_approval",
        ).values_list("job_id", flat=True)
        jobs_through_quotes.update(quote_events)

        # Jobs that skipped quotes (went straight to approved/in progress)
        jobs_skip_quotes = all_jobs.exclude(id__in=jobs_through_quotes).exclude(
            status="draft"
        )

        return {
            "through_quotes": Job.objects.filter(id__in=jobs_through_quotes),
            "through_quotes_count": len(jobs_through_quotes),
            "skip_quotes": jobs_skip_quotes,
            "skip_quotes_count": jobs_skip_quotes.count(),
        }

    def calculate_quote_acceptance_rate(self, quotes_submitted, quotes_accepted):
        """Calculate quote acceptance rate as a percentage."""
        if quotes_submitted == 0:
            return 0.0
        return (quotes_accepted / quotes_submitted) * 100

    def calculate_draft_conversion_rate(self, total_created, won_count):
        """Calculate draft to won conversion rate."""
        if total_created == 0:
            return 0.0
        return (won_count / total_created) * 100

    def calculate_comparison_metrics(self, current_value, comparison_value):
        """
        Calculate comparison metrics between current and baseline values.

        Returns:
            dict with comparison data
        """
        if comparison_value is None:
            return None

        if comparison_value == 0:
            # Avoid division by zero
            if current_value == 0:
                change_percent = 0.0
            else:
                # 100% increase from zero
                change_percent = 100.0 if current_value > 0 else -100.0
        else:
            change_percent = (
                (current_value - comparison_value) / comparison_value
            ) * 100

        return {
            "comparison_value": comparison_value,
            "change": current_value - comparison_value,
            "change_percent": change_percent,
        }

    def serialize_job_list(self, jobs):
        """
        Serialize a queryset of jobs to basic info.

        Returns:
            list of dicts with job details
        """
        return [
            {
                "id": str(job.id),
                "job_number": job.job_number,
                "name": job.name,
                "client_name": job.client.name if job.client else None,
                "status": job.status,
                "status_display": job.get_status_display(),
                "created_at": job.created_at.isoformat(),
            }
            for job in jobs
        ]

    def serialize_event_list(self, events):
        """
        Serialize a queryset of JobEvents with associated job info.

        Returns:
            list of dicts with event and job details
        """
        return [
            {
                "id": str(event.id),
                "job_id": str(event.job.id),
                "job_number": event.job.job_number,
                "job_name": event.job.name,
                "client_name": event.job.client.name if event.job.client else None,
                "timestamp": event.timestamp.isoformat(),
                "current_status": event.job.status,
                "current_status_display": event.job.get_status_display(),
            }
            for event in events
            if event.job  # Safety check
        ]

    def calculate_baseline_metrics(self, baseline_days: int) -> dict:
        """
        Calculate baseline metrics over a longer period with weekly averages.

        Args:
            baseline_days: Number of days to analyze for baseline

        Returns:
            dict: Baseline metrics with weekly averages and rates
        """
        end_date = timezone.now()
        start_date = end_date - timedelta(days=baseline_days)

        # Calculate total metrics
        draft_jobs = self.get_draft_jobs_created(start_date, end_date)
        quotes_submitted = self.get_quotes_submitted(start_date, end_date)
        quotes_accepted = self.get_quotes_accepted(start_date, end_date)
        jobs_data = self.get_jobs_won(start_date, end_date)
        path_data = self.get_jobs_by_status_path(start_date, end_date)

        # Calculate weeks for averaging
        weeks = baseline_days / 7.0

        # Calculate totals
        draft_count = draft_jobs.count()
        quotes_submitted_count = quotes_submitted.count()
        quotes_accepted_count = quotes_accepted.count()
        won_count = jobs_data["won_count"]
        rejected_count = jobs_data["rejected_count"]
        through_quotes_count = path_data["through_quotes_count"]
        skip_quotes_count = path_data["skip_quotes_count"]

        # Calculate rates
        quote_acceptance_rate = self.calculate_quote_acceptance_rate(
            quotes_submitted_count, quotes_accepted_count
        )
        conversion_rate = self.calculate_draft_conversion_rate(draft_count, won_count)

        total_progressed = through_quotes_count + skip_quotes_count
        quote_usage_rate = (
            (through_quotes_count / total_progressed * 100)
            if total_progressed > 0
            else 0.0
        )

        return {
            "period_days": baseline_days,
            "weeks": round(weeks, 2),
            "totals": {
                "draft_jobs_created": draft_count,
                "quotes_submitted": quotes_submitted_count,
                "quotes_accepted": quotes_accepted_count,
                "jobs_won": won_count,
                "rejected": rejected_count,
                "through_quotes": through_quotes_count,
                "skip_quotes": skip_quotes_count,
            },
            "weekly_averages": {
                "draft_jobs_created": round(draft_count / weeks, 2) if weeks > 0 else 0,
                "quotes_submitted": (
                    round(quotes_submitted_count / weeks, 2) if weeks > 0 else 0
                ),
                "quotes_accepted": (
                    round(quotes_accepted_count / weeks, 2) if weeks > 0 else 0
                ),
                "jobs_won": round(won_count / weeks, 2) if weeks > 0 else 0,
                "rejected": round(rejected_count / weeks, 2) if weeks > 0 else 0,
            },
            "rates": {
                "quote_acceptance_rate": round(quote_acceptance_rate, 1),
                "draft_conversion_rate": round(conversion_rate, 1),
                "quote_usage_rate": round(quote_usage_rate, 1),
            },
        }

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="start_date",
                type=str,
                required=True,
                description="Start date (YYYY-MM-DD)",
            ),
            OpenApiParameter(
                name="end_date",
                type=str,
                required=True,
                description="End date (YYYY-MM-DD)",
            ),
            OpenApiParameter(
                name="compare_start_date",
                type=str,
                required=False,
                description="Comparison period start date (YYYY-MM-DD)",
            ),
            OpenApiParameter(
                name="compare_end_date",
                type=str,
                required=False,
                description="Comparison period end date (YYYY-MM-DD)",
            ),
            OpenApiParameter(
                name="baseline_days",
                type=int,
                required=False,
                description="Number of days to calculate baseline averages over",
            ),
            OpenApiParameter(
                name="include_details",
                type=bool,
                required=False,
                description="Include job listings with IDs. Defaults to false.",
            ),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        """
        Handle GET request for job movement metrics.
        """
        # Parse required parameters
        try:
            start_date = timezone.make_aware(
                datetime.strptime(request.query_params.get("start_date"), "%Y-%m-%d")
            )
            end_date = timezone.make_aware(
                datetime.strptime(request.query_params.get("end_date"), "%Y-%m-%d")
            )
        except (ValueError, TypeError):
            return Response(
                {"error": "start_date and end_date are required in YYYY-MM-DD format"},
                status=400,
            )

        # Parse optional comparison parameters
        compare_start_date = request.query_params.get("compare_start_date")
        compare_end_date = request.query_params.get("compare_end_date")
        has_comparison = compare_start_date and compare_end_date

        if has_comparison:
            try:
                compare_start_date = timezone.make_aware(
                    datetime.strptime(compare_start_date, "%Y-%m-%d")
                )
                compare_end_date = timezone.make_aware(
                    datetime.strptime(compare_end_date, "%Y-%m-%d")
                )
            except ValueError:
                return Response(
                    {
                        "error": "compare_start_date and compare_end_date must be in YYYY-MM-DD format"
                    },
                    status=400,
                )

        # Parse include_details flag
        include_details = request.query_params.get(
            "include_details", "false"
        ).lower() in [
            "true",
            "1",
            "yes",
        ]

        # Parse baseline_days parameter
        baseline_days_param = request.query_params.get("baseline_days")
        baseline_days = None
        if baseline_days_param:
            try:
                baseline_days = int(baseline_days_param)
                if baseline_days <= 0:
                    return Response(
                        {"error": "baseline_days must be a positive integer"},
                        status=400,
                    )
            except ValueError:
                return Response(
                    {"error": "baseline_days must be an integer"},
                    status=400,
                )

        # Calculate current period metrics
        draft_jobs = self.get_draft_jobs_created(start_date, end_date)
        quotes_submitted_events = self.get_quotes_submitted(start_date, end_date)
        quotes_accepted_events = self.get_quotes_accepted(start_date, end_date)
        jobs_data = self.get_jobs_won(start_date, end_date)
        path_data = self.get_jobs_by_status_path(start_date, end_date)

        draft_count = draft_jobs.count()
        quotes_submitted_count = quotes_submitted_events.count()
        quotes_accepted_count = quotes_accepted_events.count()

        acceptance_rate = self.calculate_quote_acceptance_rate(
            quotes_submitted_count, quotes_accepted_count
        )
        conversion_rate = self.calculate_draft_conversion_rate(
            jobs_data["total_created"], jobs_data["won_count"]
        )

        # Calculate workflow percentages
        total_progressed = (
            path_data["through_quotes_count"] + path_data["skip_quotes_count"]
        )
        quote_usage_percent = (
            (path_data["through_quotes_count"] / total_progressed * 100)
            if total_progressed > 0
            else 0.0
        )

        # Calculate comparison period metrics if requested
        comparison_metrics = None
        if has_comparison:
            comp_draft_jobs = self.get_draft_jobs_created(
                compare_start_date, compare_end_date
            )
            comp_quotes_submitted = self.get_quotes_submitted(
                compare_start_date, compare_end_date
            )
            comp_quotes_accepted = self.get_quotes_accepted(
                compare_start_date, compare_end_date
            )
            comp_jobs_data = self.get_jobs_won(compare_start_date, compare_end_date)
            comp_path_data = self.get_jobs_by_status_path(
                compare_start_date, compare_end_date
            )

            comp_draft_count = comp_draft_jobs.count()
            comp_quotes_submitted_count = comp_quotes_submitted.count()
            comp_quotes_accepted_count = comp_quotes_accepted.count()
            comp_acceptance_rate = self.calculate_quote_acceptance_rate(
                comp_quotes_submitted_count, comp_quotes_accepted_count
            )
            comp_conversion_rate = self.calculate_draft_conversion_rate(
                comp_jobs_data["total_created"], comp_jobs_data["won_count"]
            )

            comp_total_progressed = (
                comp_path_data["through_quotes_count"]
                + comp_path_data["skip_quotes_count"]
            )
            comp_quote_usage_percent = (
                (comp_path_data["through_quotes_count"] / comp_total_progressed * 100)
                if comp_total_progressed > 0
                else 0.0
            )

            comparison_metrics = {
                "draft_jobs_created": comp_draft_count,
                "quotes_submitted": comp_quotes_submitted_count,
                "quotes_accepted": comp_quotes_accepted_count,
                "quote_acceptance_rate": comp_acceptance_rate,
                "jobs_won": comp_jobs_data["won_count"],
                "draft_conversion_rate": comp_conversion_rate,
                "through_quotes": comp_path_data["through_quotes_count"],
                "skip_quotes": comp_path_data["skip_quotes_count"],
                "quote_usage_percent": comp_quote_usage_percent,
            }

        # Build response
        response_data = {
            "period": {
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "days": (end_date - start_date).days + 1,
            },
            "metrics": {
                "draft_jobs_created": {
                    "count": draft_count,
                    **(
                        self.calculate_comparison_metrics(
                            draft_count,
                            comparison_metrics["draft_jobs_created"],
                        )
                        if comparison_metrics
                        else {}
                    ),
                },
                "quotes_submitted": {
                    "count": quotes_submitted_count,
                    **(
                        self.calculate_comparison_metrics(
                            quotes_submitted_count,
                            comparison_metrics["quotes_submitted"],
                        )
                        if comparison_metrics
                        else {}
                    ),
                },
                "quotes_accepted": {
                    "count": quotes_accepted_count,
                    **(
                        self.calculate_comparison_metrics(
                            quotes_accepted_count,
                            comparison_metrics["quotes_accepted"],
                        )
                        if comparison_metrics
                        else {}
                    ),
                },
                "quote_acceptance_rate": {
                    "rate": acceptance_rate,
                    "numerator": quotes_accepted_count,
                    "denominator": quotes_submitted_count,
                    **(
                        self.calculate_comparison_metrics(
                            acceptance_rate,
                            comparison_metrics["quote_acceptance_rate"],
                        )
                        if comparison_metrics
                        else {}
                    ),
                },
                "jobs_won": {
                    "count": jobs_data["won_count"],
                    "still_draft": jobs_data["still_draft_count"],
                    "rejected": jobs_data["rejected_count"],
                    "total_created": jobs_data["total_created"],
                    **(
                        self.calculate_comparison_metrics(
                            jobs_data["won_count"],
                            comparison_metrics["jobs_won"],
                        )
                        if comparison_metrics
                        else {}
                    ),
                },
                "draft_conversion_rate": {
                    "rate": conversion_rate,
                    "numerator": jobs_data["won_count"],
                    "denominator": jobs_data["total_created"],
                    **(
                        self.calculate_comparison_metrics(
                            conversion_rate,
                            comparison_metrics["draft_conversion_rate"],
                        )
                        if comparison_metrics
                        else {}
                    ),
                },
                "workflow_paths": {
                    "through_quotes": path_data["through_quotes_count"],
                    "skip_quotes": path_data["skip_quotes_count"],
                    "still_draft": jobs_data["still_draft_count"],
                    "quote_usage_percent": quote_usage_percent,
                    **(
                        self.calculate_comparison_metrics(
                            path_data["through_quotes_count"],
                            comparison_metrics["through_quotes"],
                        )
                        if comparison_metrics
                        else {}
                    ),
                },
            },
        }

        # Add comparison period info if present
        if has_comparison:
            response_data["comparison_period"] = {
                "start_date": compare_start_date.strftime("%Y-%m-%d"),
                "end_date": compare_end_date.strftime("%Y-%m-%d"),
                "days": (compare_end_date - compare_start_date).days + 1,
            }

        # Add baseline metrics if requested
        if baseline_days:
            response_data["baseline"] = self.calculate_baseline_metrics(baseline_days)

        # Add detailed job listings if requested
        if include_details:
            response_data["details"] = {
                "draft_jobs": self.serialize_job_list(draft_jobs),
                "quotes_submitted": self.serialize_event_list(quotes_submitted_events),
                "quotes_accepted": self.serialize_event_list(quotes_accepted_events),
                "jobs_won": self.serialize_job_list(jobs_data["won_jobs"]),
                "jobs_still_draft": self.serialize_job_list(jobs_data["still_draft"]),
                "jobs_rejected": self.serialize_job_list(jobs_data["rejected_jobs"]),
                "jobs_through_quotes": self.serialize_job_list(
                    path_data["through_quotes"]
                ),
                "jobs_skip_quotes": self.serialize_job_list(path_data["skip_quotes"]),
            }

        return Response(response_data)
