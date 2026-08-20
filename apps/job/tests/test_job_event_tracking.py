"""Automatic JobEvent tracking via Job.save().

The save path was blocked behind the Phase-3 tasks stub until 3b-1; these
tests assert the audit behaviour every other domain relies on: field changes
become events, untracked fields stay silent, enrichment kwargs flow through,
and the .update() guard forces attributable writes.
"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Staff
from apps.job.models import Job, JobEvent

pytestmark = pytest.mark.django_db


class TestJobEventTracking:
    def test_status_change_creates_event(self, job: Job, office_staff: Staff) -> None:
        job.status = "in_progress"
        job.save(staff=office_staff)

        event = JobEvent.objects.filter(job=job, event_type="status_changed").first()
        assert event is not None
        assert event.staff == office_staff
        assert event.delta_before is not None
        assert event.delta_before["status"] == "draft"
        assert event.delta_after is not None
        assert event.delta_after["status"] == "in_progress"

    def test_status_change_to_archived_clears_assigned_staff(
        self, job: Job, office_staff: Staff, workshop_staff: Staff
    ) -> None:
        job.people.add(workshop_staff)

        job.status = "archived"
        job.save(staff=office_staff, update_fields=["status"])

        assert not job.people.exists()

    def test_no_change_creates_no_event(self, job: Job, office_staff: Staff) -> None:
        count_before = JobEvent.objects.filter(job=job).count()
        job.save(staff=office_staff)
        assert JobEvent.objects.filter(job=job).count() == count_before

    def test_multiple_field_changes_create_single_event(
        self, job: Job, office_staff: Staff
    ) -> None:
        count_before = JobEvent.objects.filter(job=job).count()
        job.name = "New Name"
        job.order_number = "PO-999"
        job.save(staff=office_staff)

        assert JobEvent.objects.filter(job=job).count() == count_before + 1
        event = JobEvent.objects.filter(job=job).order_by("-timestamp").first()
        assert event is not None
        assert event.delta_before is not None
        assert "name" in event.delta_before
        assert "order_number" in event.delta_before

    def test_untracked_field_change_creates_no_event(self, job: Job, office_staff: Staff) -> None:
        count_before = JobEvent.objects.filter(job=job).count()
        job.fully_invoiced = True
        job.save(staff=office_staff)
        assert JobEvent.objects.filter(job=job).count() == count_before

    def test_enrichment_kwargs_passed_to_event(self, job: Job, office_staff: Staff) -> None:
        cid = uuid.uuid4()
        job.name = "Enriched"
        job.save(
            staff=office_staff,
            schema_version=1,
            change_id=cid,
            delta_meta={"fields": ["name"]},
            delta_checksum="abc123",
        )

        event = JobEvent.objects.filter(job=job).order_by("-timestamp").first()
        assert event is not None
        assert event.schema_version == 1
        assert event.change_id == cid
        assert event.delta_meta == {"fields": ["name"]}
        assert event.delta_checksum == "abc123"

    def test_event_type_override(self, job: Job, office_staff: Staff) -> None:
        job.status = "approved"
        job.save(staff=office_staff, event_type_override="quote_accepted")

        event = JobEvent.objects.filter(job=job).order_by("-timestamp").first()
        assert event is not None
        assert event.event_type == "quote_accepted"

    def test_status_transition_to_completed_persists_completed_at(
        self, job: Job, office_staff: Staff
    ) -> None:
        assert job.completed_at is None

        job.status = "recently_completed"
        job.save(staff=office_staff)

        job.refresh_from_db()
        assert job.status == "recently_completed"
        assert job.completed_at is not None

    def test_status_revert_clears_completed_at(self, job: Job, office_staff: Staff) -> None:
        job.status = "recently_completed"
        job.save(staff=office_staff)
        job.refresh_from_db()
        assert job.completed_at is not None

        job.status = "in_progress"
        job.save(staff=office_staff)

        job.refresh_from_db()
        assert job.completed_at is None

    def test_status_change_with_update_fields_persists_completed_at(
        self, job: Job, office_staff: Staff
    ) -> None:
        job.status = "recently_completed"
        job.save(staff=office_staff, update_fields=["status", "updated_at"])

        job.refresh_from_db()
        assert job.status == "recently_completed"
        assert job.completed_at is not None


class TestAcceptedForWorkAt:
    def test_returns_first_approved_event(self, job: Job, office_staff: Staff) -> None:
        first = timezone.now() - timedelta(days=3)
        second = timezone.now() - timedelta(days=1)
        for timestamp in (first, second):
            JobEvent.objects.create(
                job=job,
                staff=office_staff,
                event_type="status_changed",
                timestamp=timestamp,
                delta_after={"status": "approved"},
            )

        assert job.accepted_for_work_at == first

    def test_uses_in_progress_if_approved_was_skipped(self, job: Job, office_staff: Staff) -> None:
        accepted = timezone.now() - timedelta(days=2)
        JobEvent.objects.create(
            job=job,
            staff=office_staff,
            event_type="status_changed",
            timestamp=accepted,
            delta_after={"status": "in_progress"},
        )

        assert job.accepted_for_work_at == accepted

    def test_prefers_approved_over_later_in_progress(self, job: Job, office_staff: Staff) -> None:
        approved = timezone.now() - timedelta(days=4)
        in_progress = timezone.now() - timedelta(days=1)
        JobEvent.objects.create(
            job=job,
            staff=office_staff,
            event_type="status_changed",
            timestamp=approved,
            delta_after={"status": "approved"},
        )
        JobEvent.objects.create(
            job=job,
            staff=office_staff,
            event_type="status_changed",
            timestamp=in_progress,
            delta_after={"status": "in_progress"},
        )

        assert job.accepted_for_work_at == approved

    def test_ignores_quote_acceptance_date_without_status_event(self, job: Job) -> None:
        job.quote_acceptance_date = timezone.now() - timedelta(days=5)

        assert job.accepted_for_work_at is None


class TestQuerySetGuard:
    """.update() on tracked fields is blocked so audit events cannot be skipped."""

    def test_update_on_tracked_field_raises(self) -> None:
        with pytest.raises(RuntimeError, match="tracked fields"):
            Job.objects.filter(pk="00000000-0000-0000-0000-000000000000").update(status="draft")

    def test_update_on_untracked_field_allowed(self) -> None:
        assert (
            Job.objects.filter(pk="00000000-0000-0000-0000-000000000000").update(
                fully_invoiced=True
            )
            == 0
        )

    def test_untracked_update_bypasses_guard(self) -> None:
        assert (
            Job.objects.filter(pk="00000000-0000-0000-0000-000000000000").untracked_update(
                status="draft"
            )
            == 0
        )

    def test_mixed_tracked_and_untracked_raises(self) -> None:
        with pytest.raises(RuntimeError):
            Job.objects.filter(pk="00000000-0000-0000-0000-000000000000").update(
                status="draft", fully_invoiced=True
            )


class TestStaffRequired:
    """Job.save() refuses to run without an attributable staff member."""

    def test_save_without_staff_raises(self, job: Job) -> None:
        job.status = "in_progress"
        with pytest.raises(ValueError, match="requires staff"):
            job.save()

    def test_save_without_staff_does_not_persist_change(self, job: Job) -> None:
        job.status = "in_progress"
        with pytest.raises(ValueError):
            job.save()

        # The in-memory mutation was rejected before any DB write.
        job.refresh_from_db()
        assert job.status == "draft"


class TestEventDuplicateSuppression:
    """Duplicate suppression only suppresses while every worker consults one record.

    Opus: Both guards on the add-event endpoint — the per-user debounce and the
    identical-description check — exist to stop a double submit becoming two
    job events. On the per-process default cache the second request is caught
    when it happens to land on the same gunicorn worker and sails through when
    it does not, which is a coin toss rather than a guard.

    Structural, because the suite runs in one process: both aliases are LocMem
    there, so the wiring is all that can be checked.
    """

    def test_the_dedup_cache_is_the_shared_one(self) -> None:
        """Asserted on the alias, not the object.

        Opus: Django's cache handler hands out an instance per thread and discards it
        on teardown, so comparing identities is a coin flip under xdist.
        """
        from django.core.cache import caches  # noqa: PLC0415

        from apps.job import api  # noqa: PLC0415

        assert api._dedup_cache() is caches["shared"]
        assert caches["shared"] is not caches["default"]

    def test_the_duplicate_key_is_stable_across_processes(self) -> None:
        """`hash()` was not, which broke the check even on a shared cache.

        Opus: Python salts str hashing per interpreter, so two workers derived
        different keys for identical text and neither ever saw the other's
        entry. The value below is therefore hardcoded: a key that changes
        between runs cannot be a duplicate key, and only a fixed expectation
        can catch a silent return to a salted one.
        """
        from apps.job.api import _stable_key  # noqa: PLC0415

        assert _stable_key("Delivered to site") == _stable_key("Delivered to site")
        assert _stable_key("Delivered to site") != _stable_key("Delivered to site ")
        assert _stable_key("Delivered to site") == "b07ceac408a1821f1bcf6a13cfc9c43e"
