"""
Tests for event deduplication functionality.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import Job, JobEvent
from apps.job.services.job_rest_service import JobRestService
from apps.testing import BaseTestCase
from apps.workflow.models import XeroPayItem

User = get_user_model()


class EventDeduplicationTest(BaseTestCase):
    """Test event deduplication at model and service levels."""

    def setUp(self):
        """Set up test data."""
        self.user = Staff.objects.create_user(
            email="test@example.com",
            password="testpass123",
            first_name="Test",
            last_name="User",
        )
        self.client_obj = Client.objects.create(
            name="Test Client",
            email="client@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        # Get Ordinary Time pay item (created by migration)
        self.xero_pay_item = XeroPayItem.get_ordinary_time()
        self.job = Job.objects.create(
            name="Test Job",
            client=self.client_obj,
            created_by=self.user,
            default_xero_pay_item=self.xero_pay_item,
            staff=self.test_staff,
        )

    def test_model_prevents_duplicate_manual_events(self):
        """Test that the model prevents duplicate manual events."""
        # Create first event
        event1 = JobEvent.objects.create(
            job=self.job,
            staff=self.user,
            detail={"note_text": "Test event"},
            event_type="manual_note",
        )
        self.assertIsNotNone(event1.dedup_hash)

        # Try to create duplicate - should raise ValidationError (model validates before save)
        with self.assertRaises(ValidationError):
            JobEvent.objects.create(
                job=self.job,
                staff=self.user,
                detail={"note_text": "Test event"},
                event_type="manual_note",
            )

    def test_create_safe_method_prevents_duplicates(self):
        """Test that create_safe method handles duplicates gracefully."""
        # Create first event
        event1, created1 = JobEvent.create_safe(
            job=self.job,
            staff=self.user,
            detail={"note_text": "Test event"},
            event_type="manual_note",
        )
        self.assertTrue(created1)

        # Try to create duplicate
        event2, created2 = JobEvent.create_safe(
            job=self.job,
            staff=self.user,
            detail={"note_text": "Test event"},
            event_type="manual_note",
        )
        self.assertFalse(created2)
        self.assertEqual(event1.id, event2.id)

    def test_service_prevents_duplicate_events(self):
        """Test that the service layer prevents duplicate events."""
        description = "Test service event"

        # Create first event
        result1 = JobRestService.add_job_event(self.job.id, description, self.user)
        self.assertTrue(result1["success"])
        self.assertFalse(result1.get("duplicate_prevented", False))

        # Try to create duplicate immediately
        result2 = JobRestService.add_job_event(self.job.id, description, self.user)
        self.assertTrue(result2["success"])
        self.assertTrue(result2.get("duplicate_prevented", False))

        # Verify only one event exists in database
        events = JobEvent.objects.filter(
            job=self.job,
            staff=self.user,
            detail__note_text=description,
            event_type="manual_note",
        )
        self.assertEqual(events.count(), 1)

    def test_different_users_can_create_same_event(self):
        """Test that different users can create events with same description."""
        user2 = Staff.objects.create_user(
            email="test2@example.com",
            password="testpass123",
            first_name="Test2",
            last_name="User",
        )

        description = "Same description"

        # Event from first user
        result1 = JobRestService.add_job_event(self.job.id, description, self.user)
        self.assertTrue(result1["success"])

        # Event from second user (should be allowed)
        result2 = JobRestService.add_job_event(self.job.id, description, user2)
        self.assertTrue(result2["success"])
        self.assertFalse(result2.get("duplicate_prevented", False))

        # Verify both events exist
        events = JobEvent.objects.filter(
            job=self.job, detail__note_text=description, event_type="manual_note"
        )
        self.assertEqual(events.count(), 2)

    def test_automatic_events_not_affected(self):
        """Test that automatic events are not affected by deduplication."""
        # Create multiple automatic events with same description
        for i in range(3):
            JobEvent.objects.create(
                job=self.job,
                staff=self.user,
                description="Status changed",
                event_type="status_changed",
            )

        # All should be created successfully
        events = JobEvent.objects.filter(
            job=self.job, description="Status changed", event_type="status_changed"
        )
        self.assertEqual(events.count(), 3)

    def test_hash_generation(self):
        """Test that dedup_hash is generated correctly."""
        event = JobEvent.objects.create(
            job=self.job,
            staff=self.user,
            detail={"note_text": "Test hash generation"},
            event_type="manual_note",
        )

        # Hash should be generated
        self.assertIsNotNone(event.dedup_hash)
        self.assertEqual(len(event.dedup_hash), 32)  # MD5 hash length

        # Hash should be consistent
        expected_hash = event._generate_dedup_hash()
        self.assertEqual(event.dedup_hash, expected_hash)
