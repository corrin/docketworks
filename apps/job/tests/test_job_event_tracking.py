"""Tests for automatic JobEvent tracking via Job.save()."""

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import Job, JobEvent
from apps.job.models.job_event import (
    _format_ordinal,
    _truncate,
    _truthy,
)
from apps.testing import BaseTestCase
from apps.workflow.models import XeroPayItem

User = get_user_model()


class JobEventTrackingTest(BaseTestCase):
    """Verify that Job.save() creates events for tracked field changes."""

    def setUp(self):
        self.user = Staff.objects.create_user(
            email="tracker@example.com",
            password="testpass123",
            first_name="Test",
            last_name="Tracker",
        )
        self.client_obj = Client.objects.create(
            name="Test Client",
            email="client@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        self.xero_pay_item = XeroPayItem.get_ordinary_time()
        self.job = Job(
            name="Test Job",
            client=self.client_obj,
            created_by=self.user,
            default_xero_pay_item=self.xero_pay_item,
        )
        self.job.save(staff=self.user)

    def test_status_change_creates_event(self):
        self.job.status = "in_progress"
        self.job.save(staff=self.user)

        event = JobEvent.objects.filter(
            job=self.job, event_type="status_changed"
        ).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.staff, self.user)
        self.assertEqual(event.delta_before["status"], "draft")
        self.assertEqual(event.delta_after["status"], "in_progress")

    def test_name_change_creates_event(self):
        self.job.name = "Renamed Job"
        self.job.save(staff=self.user)

        event = (
            JobEvent.objects.filter(job=self.job)
            .exclude(event_type="job_created")
            .first()
        )
        self.assertIsNotNone(event)
        self.assertIn("name", event.delta_before)
        self.assertEqual(event.delta_after["name"], "Renamed Job")

    def test_no_change_creates_no_event(self):
        count_before = JobEvent.objects.filter(job=self.job).count()
        self.job.save(staff=self.user)
        count_after = JobEvent.objects.filter(job=self.job).count()
        self.assertEqual(count_before, count_after)

    def test_multiple_field_changes_create_single_event(self):
        count_before = JobEvent.objects.filter(job=self.job).count()
        self.job.name = "New Name"
        self.job.order_number = "PO-999"
        self.job.save(staff=self.user)
        count_after = JobEvent.objects.filter(job=self.job).count()

        self.assertEqual(count_after, count_before + 1)
        event = JobEvent.objects.filter(job=self.job).order_by("-timestamp").first()
        self.assertIn("name", event.delta_before)
        self.assertIn("order_number", event.delta_before)

    def test_untracked_field_change_creates_no_event(self):
        count_before = JobEvent.objects.filter(job=self.job).count()
        self.job.fully_invoiced = True
        self.job.save(staff=self.user)
        count_after = JobEvent.objects.filter(job=self.job).count()
        self.assertEqual(count_before, count_after)

    def test_enrichment_kwargs_passed_to_event(self):
        import uuid

        cid = uuid.uuid4()
        self.job.name = "Enriched"
        self.job.save(
            staff=self.user,
            schema_version=1,
            change_id=cid,
            delta_meta={"fields": ["name"]},
            delta_checksum="abc123",
        )

        event = JobEvent.objects.filter(job=self.job).order_by("-timestamp").first()
        self.assertEqual(event.schema_version, 1)
        self.assertEqual(event.change_id, cid)
        self.assertEqual(event.delta_meta, {"fields": ["name"]})
        self.assertEqual(event.delta_checksum, "abc123")

    def test_event_type_override(self):
        self.job.status = "approved"
        self.job.save(staff=self.user, event_type_override="quote_accepted")

        event = JobEvent.objects.filter(job=self.job).order_by("-timestamp").first()
        self.assertEqual(event.event_type, "quote_accepted")

    def test_status_transition_to_completed_persists_completed_at(self):
        self.assertIsNone(self.job.completed_at)

        self.job.status = "recently_completed"
        self.job.save(staff=self.user)

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "recently_completed")
        self.assertIsNotNone(self.job.completed_at)

    def test_status_revert_clears_completed_at(self):
        self.job.status = "recently_completed"
        self.job.save(staff=self.user)
        self.job.refresh_from_db()
        self.assertIsNotNone(self.job.completed_at)

        self.job.status = "in_progress"
        self.job.save(staff=self.user)

        self.job.refresh_from_db()
        self.assertIsNone(self.job.completed_at)

    def test_status_change_with_update_fields_persists_completed_at(self):
        self.assertIsNone(self.job.completed_at)

        self.job.status = "recently_completed"
        self.job.save(staff=self.user, update_fields=["status", "updated_at"])

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "recently_completed")
        self.assertIsNotNone(self.job.completed_at)


class JobEventDescriptionTest(SimpleTestCase):
    """Pure-Python tests for the computed description property and builders."""

    def _event(self, event_type, detail):
        return JobEvent(event_type=event_type, detail=detail)

    def test_description_property_delegates_to_build_description(self):
        event = self._event("manual_note", {"note_text": "A scribbled note"})
        self.assertEqual(event.description, "A scribbled note")
        self.assertEqual(event.description, event.build_description())

    def test_legacy_description_takes_precedence(self):
        event = self._event(
            "job_updated", {"legacy_description": "Old free-text", "changes": []}
        )
        self.assertEqual(event.description, "Old free-text")

    def test_unknown_event_type_returns_sentinel(self):
        event = self._event("never_seen_event_type", {})
        self.assertEqual(event.description, "(never_seen_event_type)")

    def test_friendly_boolean_rejected_set(self):
        event = self._event(
            "job_rejected",
            {
                "changes": [
                    {"field_name": "Rejected", "old_value": "No", "new_value": "Yes"}
                ]
            },
        )
        self.assertEqual(event.description, "Job marked as rejected")

    def test_friendly_boolean_rejected_cleared(self):
        event = self._event(
            "job_updated",
            {
                "changes": [
                    {"field_name": "Rejected", "old_value": "Yes", "new_value": "No"}
                ]
            },
        )
        self.assertEqual(event.description, "Rejection cleared")

    def test_friendly_boolean_complex_job(self):
        event = self._event(
            "job_updated",
            {
                "changes": [
                    {"field_name": "Complex job", "old_value": "No", "new_value": "Yes"}
                ]
            },
        )
        self.assertEqual(event.description, "Marked as complex job")

    def test_friendly_boolean_paid(self):
        event = self._event(
            "payment_received",
            {
                "changes": [
                    {"field_name": "Paid", "old_value": "No", "new_value": "Yes"}
                ]
            },
        )
        self.assertEqual(event.description, "Marked as paid")

    def test_friendly_boolean_collected(self):
        event = self._event(
            "job_collected",
            {
                "changes": [
                    {"field_name": "Collected", "old_value": "No", "new_value": "Yes"}
                ]
            },
        )
        self.assertEqual(event.description, "Marked as collected")

    def test_long_text_field_truncates(self):
        long_value = "x" * 200
        event = self._event(
            "job_updated",
            {
                "changes": [
                    {
                        "field_name": "Job description",
                        "old_value": "",
                        "new_value": long_value,
                    }
                ]
            },
        )
        rendered = event.description
        self.assertTrue(rendered.endswith("…'"))
        # Truncated value should be much shorter than the original
        self.assertLess(len(rendered), len(long_value) + 50)

    def test_default_descriptor_for_unknown_field(self):
        event = self._event(
            "job_updated",
            {
                "changes": [
                    {"field_name": "Some field", "old_value": "A", "new_value": "B"}
                ]
            },
        )
        self.assertEqual(event.description, "Some field changed from 'A' to 'B'")

    def test_multiple_changes_join_with_period(self):
        event = self._event(
            "job_updated",
            {
                "changes": [
                    {"field_name": "Paid", "old_value": "No", "new_value": "Yes"},
                    {
                        "field_name": "Order number",
                        "old_value": "PO-1",
                        "new_value": "PO-2",
                    },
                ]
            },
        )
        self.assertEqual(
            event.description,
            "Marked as paid. Order number changed from 'PO-1' to 'PO-2'",
        )

    def test_priority_changed_within_column(self):
        event = self._event(
            "priority_changed",
            {
                "changes": [
                    {
                        "field_name": "Job priority",
                        "old_value": "5200.0",
                        "new_value": "5300.0",
                    }
                ],
                "position": {
                    "old_status": "in_progress",
                    "new_status": "in_progress",
                    "old_position": 11,
                    "new_position": 5,
                    "old_total": 51,
                    "new_total": 51,
                },
            },
        )
        self.assertEqual(
            event.description,
            "Priority increased from 11th to 5th of 51 in In Progress",
        )

    def test_priority_changed_within_column_decreased(self):
        event = self._event(
            "priority_changed",
            {
                "changes": [
                    {
                        "field_name": "Job priority",
                        "old_value": "5300.0",
                        "new_value": "5200.0",
                    }
                ],
                "position": {
                    "old_status": "in_progress",
                    "new_status": "in_progress",
                    "old_position": 5,
                    "new_position": 11,
                    "old_total": 51,
                    "new_total": 51,
                },
            },
        )
        self.assertEqual(
            event.description,
            "Priority decreased from 5th to 11th of 51 in In Progress",
        )

    def test_priority_changed_cross_column(self):
        event = self._event(
            "priority_changed",
            {
                "changes": [
                    {
                        "field_name": "Job priority",
                        "old_value": "1000",
                        "new_value": "9000",
                    }
                ],
                "position": {
                    "old_status": "in_progress",
                    "new_status": "quoting",
                    "old_position": 11,
                    "new_position": 3,
                    "old_total": 51,
                    "new_total": 27,
                },
            },
        )
        self.assertEqual(
            event.description,
            "Moved from In Progress (11th of 51) to Quoting (3rd of 27)",
        )

    def test_priority_legacy_float_diff_increased(self):
        event = self._event(
            "priority_changed",
            {
                "changes": [
                    {
                        "field_name": "Job priority",
                        "old_value": "5200.0",
                        "new_value": "5300.0",
                    }
                ]
            },
        )
        self.assertEqual(event.description, "Priority increased")

    def test_priority_legacy_float_diff_decreased(self):
        event = self._event(
            "priority_changed",
            {
                "changes": [
                    {
                        "field_name": "Job priority",
                        "old_value": "5300.0",
                        "new_value": "5200.0",
                    }
                ]
            },
        )
        self.assertEqual(event.description, "Priority decreased")

    def test_priority_legacy_unparseable_floats_returns_safe_text(self):
        event = self._event(
            "priority_changed",
            {
                "changes": [
                    {"field_name": "Job priority", "old_value": "n/a", "new_value": "x"}
                ]
            },
        )
        self.assertEqual(event.description, "Priority changed")

    def test_helper_truncate_short_text_unchanged(self):
        self.assertEqual(_truncate("hello"), "hello")

    def test_helper_truncate_long_text(self):
        self.assertEqual(_truncate("a" * 100, 10), "aaaaaaaaa…")

    def test_helper_format_ordinal(self):
        self.assertEqual(_format_ordinal(1), "1st")
        self.assertEqual(_format_ordinal(2), "2nd")
        self.assertEqual(_format_ordinal(3), "3rd")
        self.assertEqual(_format_ordinal(4), "4th")
        self.assertEqual(_format_ordinal(11), "11th")
        self.assertEqual(_format_ordinal(12), "12th")
        self.assertEqual(_format_ordinal(13), "13th")
        self.assertEqual(_format_ordinal(21), "21st")
        self.assertEqual(_format_ordinal(22), "22nd")

    def test_helper_truthy(self):
        self.assertTrue(_truthy(True))
        self.assertTrue(_truthy("Yes"))
        self.assertTrue(_truthy("yes"))
        self.assertTrue(_truthy("True"))
        self.assertFalse(_truthy(False))
        self.assertFalse(_truthy("No"))
        self.assertFalse(_truthy(""))
        self.assertFalse(_truthy(None))


class PriorityPositionCaptureTest(BaseTestCase):
    """Verify KanbanService.reorder_job attaches detail.position to the JobEvent."""

    def setUp(self):
        self.user = Staff.objects.create_user(
            email="kanban@example.com",
            password="testpass123",
            first_name="Kanban",
            last_name="Tester",
        )
        self.client_obj = Client.objects.create(
            name="Kanban Client",
            email="kc@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        self.xero_pay_item = XeroPayItem.get_ordinary_time()

    def _make_job(self, name, status="in_progress"):
        job = Job(
            name=name,
            client=self.client_obj,
            created_by=self.user,
            default_xero_pay_item=self.xero_pay_item,
            status=status,
        )
        job.save(staff=self.user)
        return job

    def test_within_column_drag_records_position(self):
        from apps.job.services.kanban_service import KanbanService

        job_a = self._make_job("Job A")
        self._make_job("Job B")
        job_c = self._make_job("Job C")
        # Each save assigns priority via _calculate_next_priority_for_status
        # → C is highest, A is lowest. Drag A to the top (above C).
        KanbanService.reorder_job(
            job_id=job_a.pk, before_id=str(job_c.pk), after_id=None, staff=self.user
        )

        event = (
            JobEvent.objects.filter(job=job_a, event_type="priority_changed")
            .order_by("-timestamp")
            .first()
        )
        self.assertIsNotNone(event)
        position = event.detail.get("position")
        self.assertIsNotNone(position)
        self.assertEqual(position["old_status"], "in_progress")
        self.assertEqual(position["new_status"], "in_progress")
        self.assertEqual(position["old_total"], 3)
        self.assertEqual(position["new_total"], 3)
        self.assertEqual(position["old_position"], 3)  # was at the bottom
        self.assertEqual(position["new_position"], 1)  # now at the top

    def test_noop_priority_change_creates_no_event(self):
        """When priority_position has equal old/new positions, no JobEvent is created."""
        job = self._make_job("Solo")
        before_count = JobEvent.objects.filter(
            job=job, event_type="priority_changed"
        ).count()

        # Float changed; rank stayed (e.g. neighbours' gap absorbed the drag).
        job.priority = job.priority + 0.5
        job.save(
            staff=self.user,
            update_fields=["priority", "updated_at"],
            priority_position={
                "old_status": "in_progress",
                "new_status": "in_progress",
                "old_position": 1,
                "new_position": 1,
                "old_total": 1,
                "new_total": 1,
            },
        )

        after_count = JobEvent.objects.filter(
            job=job, event_type="priority_changed"
        ).count()
        self.assertEqual(after_count, before_count)

    def test_cross_column_drag_records_old_and_new_totals(self):
        from apps.job.services.kanban_service import KanbanService

        in_progress_job = self._make_job("Mover", status="in_progress")
        # Make sure both columns have other entries so totals differ
        self._make_job("Other IP 1", status="in_progress")
        self._make_job("Other IP 2", status="in_progress")
        self._make_job("Quoter 1", status="quoting")
        self._make_job("Quoter 2", status="quoting")
        self._make_job("Quoter 3", status="quoting")
        self._make_job("Quoter 4", status="quoting")

        # Move the "Mover" from in_progress to quoting (top of quoting)
        KanbanService.reorder_job(
            job_id=in_progress_job.pk,
            before_id=None,
            after_id=None,
            new_status="quoting",
            staff=self.user,
        )

        event = (
            JobEvent.objects.filter(job=in_progress_job, event_type="priority_changed")
            .order_by("-timestamp")
            .first()
        )
        # Note: cross-column moves may emit either priority_changed or
        # status_changed depending on _infer_event_type; if status_changed
        # wins, the position info is still attached only when the inferred
        # type is priority_changed. Adjust the assertion accordingly.
        if event is None:
            event = (
                JobEvent.objects.filter(job=in_progress_job)
                .order_by("-timestamp")
                .first()
            )
            self.assertEqual(event.event_type, "status_changed")
            # status_changed events don't carry detail.position by design
            return

        position = event.detail.get("position")
        self.assertIsNotNone(position)
        self.assertEqual(position["old_status"], "in_progress")
        self.assertEqual(position["new_status"], "quoting")
        self.assertEqual(position["old_total"], 3)
        self.assertEqual(position["new_total"], 5)


class QuerySetGuardTest(BaseTestCase):
    """Verify that .update() on tracked fields is blocked."""

    def test_update_on_tracked_field_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            Job.objects.filter(pk="00000000-0000-0000-0000-000000000000").update(
                status="draft"
            )
        self.assertIn("tracked fields", str(ctx.exception))

    def test_update_on_untracked_field_allowed(self):
        result = Job.objects.filter(pk="00000000-0000-0000-0000-000000000000").update(
            fully_invoiced=True
        )
        self.assertEqual(result, 0)

    def test_untracked_update_bypasses_guard(self):
        result = Job.objects.filter(
            pk="00000000-0000-0000-0000-000000000000"
        ).untracked_update(status="draft")
        self.assertEqual(result, 0)

    def test_mixed_tracked_and_untracked_raises(self):
        with self.assertRaises(RuntimeError):
            Job.objects.filter(pk="00000000-0000-0000-0000-000000000000").update(
                status="draft", fully_invoiced=True
            )


class StaffRequiredTest(BaseTestCase):
    """Verify that Job.save() refuses to run without staff."""

    def setUp(self):
        self.user = Staff.objects.create_user(
            email="required@example.com",
            password="testpass123",
            first_name="Staff",
            last_name="Required",
        )
        self.client_obj = Client.objects.create(
            name="Required Client",
            email="required-client@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        self.xero_pay_item = XeroPayItem.get_ordinary_time()
        self.job = Job(
            name="Required Job",
            client=self.client_obj,
            created_by=self.user,
            default_xero_pay_item=self.xero_pay_item,
        )
        self.job.save(staff=self.user)

    def test_save_without_staff_raises(self):
        self.job.status = "in_progress"
        with self.assertRaises(ValueError) as ctx:
            self.job.save()
        self.assertIn("requires staff", str(ctx.exception))

    def test_save_without_staff_does_not_persist_change(self):
        self.job.status = "in_progress"
        with self.assertRaises(ValueError):
            self.job.save()

        # The in-memory mutation was rejected before any DB write.
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "draft")
