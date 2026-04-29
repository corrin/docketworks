"""Construct candidate JobEvents from HistoricalJob data.

Dry-run by default: shows proposed events without writing.
Use --commit to actually create/update records.
"""

import logging
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.job.management.commands._history_enrichment_utils import (
    build_candidate_event,
    find_matching_event,
    get_first_history_record,
    walk_history_pairs,
)
from apps.job.models.job import Job
from apps.job.models.job_event import JobEvent

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Construct enriched JobEvents from HistoricalJob (dry-run by default)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually write changes (default is dry-run)",
        )
        parser.add_argument(
            "--job-id",
            type=str,
            help="Restrict to a single job UUID",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Batch size for bulk operations (default: 500)",
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
            help="Show details for every proposed change",
        )

    def handle(self, *args, **options):
        commit = options["commit"]
        job_id = options.get("job_id")
        batch_size = options["batch_size"]
        window = options["window"]
        verbose = options["verbose"]

        HistoricalJob = Job.history.model

        if commit:
            self.stdout.write(
                self.style.WARNING("COMMIT mode: changes will be written")
            )
        else:
            self.stdout.write(
                self.style.WARNING("DRY-RUN mode: no changes will be made")
            )

        if job_id:
            job_ids = [job_id]
        else:
            job_ids = list(
                HistoricalJob.objects.order_by().values_list("id", flat=True).distinct()
            )

        self.stdout.write(f"Processing {len(job_ids)} jobs")

        counts = Counter()
        events_to_create = []
        events_to_update = []

        for jid in job_ids:
            if not Job.objects.filter(id=jid).exists():
                counts["skipped_deleted_job"] += 1
                continue

            self._process_job(
                jid,
                HistoricalJob,
                window,
                verbose,
                events_to_create,
                events_to_update,
                counts,
            )

            # Flush batches
            if commit and len(events_to_create) >= batch_size:
                self._flush_creates(events_to_create)
            if commit and len(events_to_update) >= batch_size:
                self._flush_updates(events_to_update)

            if (counts["jobs_processed"] % 100) == 0 and counts["jobs_processed"] > 0:
                logger.info(
                    "Processed %d/%d jobs", counts["jobs_processed"], len(job_ids)
                )

        # Final flush
        if commit:
            self._flush_creates(events_to_create)
            self._flush_updates(events_to_update)

        # ── Summary ──────────────────────────────────────────────────
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("═══ Summary ═══"))
        prefix = "Would" if not commit else "Did"
        self.stdout.write(f"Jobs processed:        {counts['jobs_processed']}")
        self.stdout.write(f"Skipped (deleted job): {counts['skipped_deleted_job']}")
        self.stdout.write(f"{prefix} create:        {counts['to_create']}")
        self.stdout.write(f"{prefix} update staff:  {counts['update_staff']}")
        self.stdout.write(f"{prefix} update detail: {counts['update_detail']}")
        self.stdout.write(f"Already complete:      {counts['already_complete']}")

    def _process_job(
        self,
        job_id,
        HistoricalJob,
        window,
        verbose,
        events_to_create,
        events_to_update,
        counts,
    ):
        counts["jobs_processed"] += 1

        # Handle job_created event
        first_rec = get_first_history_record(job_id, HistoricalJob)
        if first_rec:
            self._process_creation(
                job_id,
                first_rec,
                window,
                verbose,
                events_to_create,
                events_to_update,
                counts,
            )

        # Handle field changes
        for prev, rec, changed_fields in walk_history_pairs(job_id, HistoricalJob):
            candidate = build_candidate_event(job_id, rec, changed_fields)

            # Try to find existing event
            existing = find_matching_event(
                job_id,
                candidate["event_type"],
                candidate["timestamp"],
                window,
                JobEvent,
            )

            if existing:
                self._process_existing_match(
                    existing,
                    candidate,
                    rec,
                    verbose,
                    events_to_update,
                    counts,
                )
            else:
                # New event needed
                counts["to_create"] += 1
                events_to_create.append(candidate)
                if verbose:
                    self._log_proposed_create(candidate)

    def _process_creation(
        self,
        job_id,
        first_rec,
        window,
        verbose,
        events_to_create,
        events_to_update,
        counts,
    ):
        """Handle the job_created event from the first history record."""
        existing = find_matching_event(
            job_id,
            "job_created",
            first_rec.history_date,
            window,
            JobEvent,
        )

        if existing:
            updates_needed = {}

            if not existing.staff_id and first_rec.history_user_id:
                updates_needed["staff_id"] = first_rec.history_user_id
                counts["update_staff"] += 1

            if not existing.delta_after:
                updates_needed["delta_after"] = {"status": first_rec.status}
                counts["update_detail"] += 1

            if updates_needed:
                events_to_update.append((existing, updates_needed))
                if verbose:
                    self.stdout.write(
                        f"  UPDATE job_created job={job_id} "
                        f"updates={updates_needed}"
                    )
            else:
                counts["already_complete"] += 1
        else:
            candidate = {
                "job_id": job_id,
                "event_type": "job_created",
                "timestamp": first_rec.history_date,
                "staff_id": first_rec.history_user_id,
                "delta_after": {"status": first_rec.status},
                "detail": {
                    "initial_status": str(
                        dict(Job.JOB_STATUS_CHOICES).get(
                            first_rec.status, first_rec.status
                        )
                    ),
                },
                "schema_version": 0,
            }
            # Add client/contact names if available
            if first_rec.client_id:
                from apps.job.management.commands._history_enrichment_utils import (
                    get_client_names,
                )

                names = get_client_names()
                candidate["detail"]["client_name"] = names.get(
                    first_rec.client_id,
                    f"Unknown Client (id={first_rec.client_id})",
                )
            if hasattr(first_rec, "contact_id") and first_rec.contact_id:
                from apps.job.management.commands._history_enrichment_utils import (
                    get_contact_names,
                )

                names = get_contact_names()
                candidate["detail"]["contact_name"] = names.get(
                    first_rec.contact_id,
                    f"Unknown Contact (id={first_rec.contact_id})",
                )
            candidate["detail"]["job_name"] = first_rec.name

            counts["to_create"] += 1
            events_to_create.append(candidate)
            if verbose:
                self._log_proposed_create(candidate)

    def _process_existing_match(
        self,
        existing,
        candidate,
        history_record,
        verbose,
        events_to_update,
        counts,
    ):
        """Check if an existing matched event needs enrichment."""
        updates_needed = {}

        # Enrich staff
        if not existing.staff_id and history_record.history_user_id:
            updates_needed["staff_id"] = history_record.history_user_id
            counts["update_staff"] += 1

        # Enrich detail — only if current detail is empty, legacy, or missing changes
        current_detail = existing.detail if hasattr(existing, "detail") else None
        needs_detail = False
        if current_detail is None:
            needs_detail = True
        elif current_detail == {}:
            needs_detail = True
        elif (
            isinstance(current_detail, dict) and "legacy_description" in current_detail
        ):
            needs_detail = True

        if needs_detail and candidate.get("detail"):
            updates_needed["detail"] = candidate["detail"]
            counts["update_detail"] += 1

        # Enrich deltas
        if not existing.delta_before and candidate.get("delta_before"):
            updates_needed["delta_before"] = candidate["delta_before"]
        if not existing.delta_after and candidate.get("delta_after"):
            updates_needed["delta_after"] = candidate["delta_after"]

        if updates_needed:
            events_to_update.append((existing, updates_needed))
            if verbose:
                self.stdout.write(
                    f"  UPDATE {existing.event_type} job={existing.job_id} "
                    f"event={existing.id} updates={list(updates_needed.keys())}"
                )
        else:
            counts["already_complete"] += 1

    def _log_proposed_create(self, candidate):
        detail_summary = ""
        detail = candidate.get("detail", {})
        if "changes" in detail:
            changes = detail["changes"]
            parts = [
                f"{c['field_name']}: {c['old_value']} → {c['new_value']}"
                for c in changes[:3]
            ]
            detail_summary = "; ".join(parts)
            if len(changes) > 3:
                detail_summary += f" (+{len(changes) - 3} more)"
        self.stdout.write(
            f"  CREATE {candidate['event_type']} "
            f"job={candidate['job_id']} "
            f"ts={candidate['timestamp']} "
            f"staff={candidate.get('staff_id', 'None')} "
            f"[{detail_summary}]"
        )

    def _flush_creates(self, events_to_create):
        if not events_to_create:
            return
        with transaction.atomic():
            objs = [JobEvent(**data) for data in events_to_create]
            JobEvent.objects.bulk_create(objs, batch_size=500)
            logger.info("Created %d JobEvent records", len(objs))
        events_to_create.clear()

    def _flush_updates(self, events_to_update):
        if not events_to_update:
            return
        with transaction.atomic():
            update_fields_set = set()
            for event, updates in events_to_update:
                for field, value in updates.items():
                    setattr(event, field, value)
                    update_fields_set.add(field)
            objs = [event for event, _ in events_to_update]
            JobEvent.objects.bulk_update(objs, list(update_fields_set), batch_size=500)
            logger.info("Updated %d JobEvent records", len(objs))
        events_to_update.clear()
