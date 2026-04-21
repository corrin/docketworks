"""Tests for automatic JobEvent tracking via Job.save()."""

from django.contrib.auth import get_user_model

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import Job, JobEvent
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
