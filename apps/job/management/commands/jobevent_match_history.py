"""Match HistoricalJob changes to existing JobEvent records and report gaps."""

import logging
from collections import Counter

from django.core.management.base import BaseCommand

from apps.job.management.commands._history_enrichment_utils import (
    FIELD_EVENT_TYPE,
    find_matching_event,
    get_first_history_record,
    walk_history_pairs,
)
from apps.job.models.job import Job
from apps.job.models.job_event import JobEvent

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Match HistoricalJob changes to JobEvent records, report gaps"

    def add_arguments(self, parser):
        parser.add_argument(
            "--job-id",
            type=str,
            help="Restrict to a single job UUID",
        )
        parser.add_argument(
            "--window",
            type=int,
            default=2,
            help="Match window in seconds (default: 2)",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show per-change match details",
        )

    def handle(self, *args, **options):
        job_id = options.get("job_id")
        window = options["window"]
        verbose = options["verbose"]

        HistoricalJob = Job.history.model

        if job_id:
            job_ids = [job_id]
        else:
            job_ids = list(
                HistoricalJob.objects.order_by().values_list("id", flat=True).distinct()
            )

        self.stdout.write(
            f"Matching history for {len(job_ids)} jobs (window={window}s)"
        )

        match_counts = Counter()  # EXACT, CLOSE, UNMATCHED
        unmatched_changes = []
        enrichable_events = []  # matched but missing staff or detail
        jobs_processed = 0
        total_historical_changes = 0

        for jid in job_ids:
            if not Job.objects.filter(id=jid).exists():
                continue

            # Check for job_created event
            first_rec = get_first_history_record(jid, HistoricalJob)
            if first_rec:
                created_match = find_matching_event(
                    jid, "job_created", first_rec.history_date, window, JobEvent
                )
                if created_match:
                    match_counts["EXACT"] += 1
                    if not created_match.staff_id and first_rec.history_user_id:
                        enrichable_events.append(
                            {
                                "event_id": str(created_match.id),
                                "job_id": str(jid),
                                "event_type": "job_created",
                                "reason": "missing staff",
                            }
                        )
                else:
                    match_counts["UNMATCHED"] += 1
                    unmatched_changes.append(
                        {
                            "job_id": str(jid),
                            "timestamp": str(first_rec.history_date),
                            "event_type": "job_created",
                            "fields": ["(initial creation)"],
                        }
                    )
                total_historical_changes += 1

            # Walk field changes
            for prev, rec, changed_fields in walk_history_pairs(jid, HistoricalJob):
                total_historical_changes += 1

                # Determine event types for each field change, applying
                # boolean transition overrides
                field_event_types = {}
                for field, (old_val, new_val) in changed_fields.items():
                    event_type = FIELD_EVENT_TYPE[field]
                    if field == "rejected_flag" and not new_val:
                        event_type = "job_updated"
                    if field == "paid" and not new_val:
                        event_type = "payment_updated"
                    if field == "collected" and not new_val:
                        event_type = "collection_updated"
                    field_event_types[field] = event_type

                # Try to match by the distinct event types produced
                distinct_types = set(field_event_types.values())
                matched_any = False

                for et in distinct_types:
                    match = find_matching_event(
                        jid, et, rec.history_date, window, JobEvent
                    )
                    if match:
                        matched_any = True
                        # Check delta completeness
                        existing_before = match.delta_before or {}
                        fields_for_type = [
                            f for f, t in field_event_types.items() if t == et
                        ]
                        all_present = all(f in existing_before for f in fields_for_type)

                        if all_present:
                            match_counts["EXACT"] += 1
                        else:
                            match_counts["CLOSE"] += 1

                        # Check enrichability
                        reasons = []
                        if not match.staff_id and rec.history_user_id:
                            reasons.append("missing staff")
                        if not all_present:
                            reasons.append("incomplete deltas")
                        if reasons:
                            enrichable_events.append(
                                {
                                    "event_id": str(match.id),
                                    "job_id": str(jid),
                                    "event_type": et,
                                    "reason": ", ".join(reasons),
                                }
                            )

                        if verbose:
                            fields_str = ", ".join(fields_for_type)
                            quality = "EXACT" if all_present else "CLOSE"
                            self.stdout.write(
                                f"  [{quality}] job={jid} type={et} "
                                f"fields=[{fields_str}] "
                                f"hist_date={rec.history_date}"
                            )
                    else:
                        match_counts["UNMATCHED"] += 1
                        fields_for_type = [
                            f for f, t in field_event_types.items() if t == et
                        ]
                        unmatched_changes.append(
                            {
                                "job_id": str(jid),
                                "timestamp": str(rec.history_date),
                                "event_type": et,
                                "fields": fields_for_type,
                            }
                        )
                        if verbose:
                            fields_str = ", ".join(fields_for_type)
                            self.stdout.write(
                                f"  [UNMATCHED] job={jid} type={et} "
                                f"fields=[{fields_str}] "
                                f"hist_date={rec.history_date}"
                            )

                if not matched_any and not distinct_types:
                    # No tracked fields changed (shouldn't happen, walk_history_pairs filters)
                    pass

            jobs_processed += 1
            if jobs_processed % 100 == 0:
                logger.info("Processed %d/%d jobs", jobs_processed, len(job_ids))

        # ── Summary ──────────────────────────────────────────────────
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("═══ Match Summary ═══"))
        self.stdout.write(f"Jobs processed:           {jobs_processed}")
        self.stdout.write(f"Total historical changes: {total_historical_changes}")
        self.stdout.write(f"  EXACT matches:  {match_counts['EXACT']:>6d}")
        self.stdout.write(f"  CLOSE matches:  {match_counts['CLOSE']:>6d}")
        self.stdout.write(f"  UNMATCHED:      {match_counts['UNMATCHED']:>6d}")

        if enrichable_events:
            self.stdout.write("")
            self.stdout.write(self.style.HTTP_INFO("═══ Enrichable Events ═══"))
            reason_counts = Counter(e["reason"] for e in enrichable_events)
            for reason, count in reason_counts.most_common():
                self.stdout.write(f"  {reason}: {count}")

        if unmatched_changes:
            self.stdout.write("")
            self.stdout.write(self.style.HTTP_INFO("═══ Unmatched Changes (Gaps) ═══"))
            type_counts = Counter(u["event_type"] for u in unmatched_changes)
            for et, count in type_counts.most_common():
                self.stdout.write(f"  {et}: {count}")

            # Approximate boundary: find where matches start appearing
            if unmatched_changes and match_counts["EXACT"] + match_counts["CLOSE"] > 0:
                timestamps = sorted(u["timestamp"] for u in unmatched_changes)
                self.stdout.write(f"  Earliest unmatched: {timestamps[0]}")
                self.stdout.write(f"  Latest unmatched:   {timestamps[-1]}")
