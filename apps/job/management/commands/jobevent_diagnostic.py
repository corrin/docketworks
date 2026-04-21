"""Diagnostic: audit the current state of JobEvent and HistoricalJob data."""

import logging

from django.core.management.base import BaseCommand
from django.db.models import Count, Max, Min, Q

from apps.job.models.job import Job
from apps.job.models.job_event import JobEvent

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Audit JobEvent and HistoricalJob data state"

    def add_arguments(self, parser):
        parser.add_argument(
            "--job-id",
            type=str,
            help="Restrict analysis to a single job UUID",
        )

    def handle(self, *args, **options):
        job_id = options.get("job_id")
        HistoricalJob = Job.history.model

        job_filter = Q(job_id=job_id) if job_id else Q()
        hist_filter = Q(id=job_id) if job_id else Q()

        self._section("JobEvent Summary")
        self._jobevent_stats(job_filter)

        self._section("HistoricalJob Summary")
        self._historical_stats(HistoricalJob, hist_filter)

        self._section("Coverage Analysis")
        self._coverage_analysis(HistoricalJob, job_id)

    def _section(self, title):
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO(f"═══ {title} ═══"))

    def _jobevent_stats(self, job_filter):
        total = JobEvent.objects.filter(job_filter).count()
        self.stdout.write(f"Total JobEvent records: {total}")

        if total == 0:
            self.stdout.write("  (no records)")
            return

        # By event_type
        by_type = (
            JobEvent.objects.filter(job_filter)
            .values("event_type")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        self.stdout.write("By event_type:")
        for row in by_type:
            self.stdout.write(f"  {row['event_type']:30s} {row['count']:>6d}")

        # Staff coverage
        with_staff = (
            JobEvent.objects.filter(job_filter).exclude(staff__isnull=True).count()
        )
        without_staff = total - with_staff
        self.stdout.write(
            f"With staff:    {with_staff:>6d} ({with_staff * 100 / total:.1f}%)"
        )
        self.stdout.write(
            f"Without staff: {without_staff:>6d} ({without_staff * 100 / total:.1f}%)"
        )

        # Detail field state
        has_detail_field = hasattr(JobEvent, "detail")
        if has_detail_field:
            try:
                empty_detail = JobEvent.objects.filter(job_filter, detail={}).count()
                legacy = JobEvent.objects.filter(
                    job_filter, detail__has_key="legacy_description"
                ).count()
                structured = JobEvent.objects.filter(
                    job_filter, detail__has_key="changes"
                ).count()
                other = total - empty_detail - legacy - structured
                self.stdout.write("Detail field state:")
                self.stdout.write(f"  Empty ({{}}):          {empty_detail:>6d}")
                self.stdout.write(f"  legacy_description:  {legacy:>6d}")
                self.stdout.write(f"  Structured (changes): {structured:>6d}")
                self.stdout.write(f"  Other:                {other:>6d}")
            except Exception:
                self.stdout.write(
                    "  detail field exists but query failed (column may not exist in DB)"
                )
        else:
            self.stdout.write("  detail field not present on model")

        # Date range
        date_range = JobEvent.objects.filter(job_filter).aggregate(
            earliest=Min("timestamp"), latest=Max("timestamp")
        )
        self.stdout.write(
            f"Date range: {date_range['earliest']} → {date_range['latest']}"
        )

    def _historical_stats(self, HistoricalJob, hist_filter):
        total = HistoricalJob.objects.filter(hist_filter).count()
        self.stdout.write(f"Total HistoricalJob records: {total}")

        if total == 0:
            self.stdout.write("  (no records)")
            return

        # By history_type
        by_type = (
            HistoricalJob.objects.filter(hist_filter)
            .values("history_type")
            .annotate(count=Count("history_id"))
            .order_by("-count")
        )
        type_labels = {"+": "Created", "~": "Changed", "-": "Deleted"}
        self.stdout.write("By history_type:")
        for row in by_type:
            label = type_labels.get(row["history_type"], row["history_type"])
            self.stdout.write(
                f"  {label:10s} ({row['history_type']}) {row['count']:>6d}"
            )

        # Staff coverage
        with_user = (
            HistoricalJob.objects.filter(hist_filter)
            .exclude(history_user__isnull=True)
            .count()
        )
        without_user = total - with_user
        self.stdout.write(
            f"With history_user:    {with_user:>6d} ({with_user * 100 / total:.1f}%)"
        )
        self.stdout.write(
            f"Without history_user: {without_user:>6d} ({without_user * 100 / total:.1f}%)"
        )

        # Date range
        date_range = HistoricalJob.objects.filter(hist_filter).aggregate(
            earliest=Min("history_date"), latest=Max("history_date")
        )
        self.stdout.write(
            f"Date range: {date_range['earliest']} → {date_range['latest']}"
        )

        # Distinct jobs
        distinct_jobs = (
            HistoricalJob.objects.filter(hist_filter).values("id").distinct().count()
        )
        self.stdout.write(f"Distinct jobs: {distinct_jobs}")

    def _coverage_analysis(self, HistoricalJob, job_id):
        hist_job_ids = set(
            HistoricalJob.objects.values_list("id", flat=True).distinct()
        )
        event_job_ids = set(
            JobEvent.objects.values_list("job_id", flat=True).distinct()
        )

        if job_id:
            self.stdout.write("(Coverage analysis not meaningful for single job)")
            return

        both = hist_job_ids & event_job_ids
        hist_only = hist_job_ids - event_job_ids
        event_only = event_job_ids - hist_job_ids

        self.stdout.write(f"Jobs in both tables:         {len(both):>6d}")
        self.stdout.write(f"Jobs in HistoricalJob only:  {len(hist_only):>6d}")
        self.stdout.write(f"Jobs in JobEvent only:       {len(event_only):>6d}")

        if both:
            # Sample overlap: find approximate boundary where JobEvents start
            overlap_earliest = JobEvent.objects.filter(job_id__in=both).aggregate(
                earliest=Min("timestamp")
            )
            self.stdout.write(
                f"Earliest JobEvent for overlapping jobs: {overlap_earliest['earliest']}"
            )
