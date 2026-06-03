"""Manual note deduplication must prevent double-click spam without hiding history."""

from django.core.exceptions import ValidationError

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import Job, JobEvent
from apps.job.services.job_rest_service import JobRestService
from apps.testing import BaseTestCase
from apps.workflow.models import XeroPayItem


class EventDeduplicationTest(BaseTestCase):
    """Manual note dedup rules must be consistent across model and service paths.

    A user can submit the same note twice through retries/double-clicks, while
    automatic audit events and other staff members' notes must still be kept.
    These tests catch both duplicate leakage and over-broad deduplication.
    """

    def setUp(self):
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
        """Direct model writes must not bypass manual-note duplicate guards.

        This catches imports/admin paths that create ``JobEvent`` rows without
        the REST service and would otherwise allow duplicate user notes.
        """
        event1 = JobEvent.objects.create(
            job=self.job,
            staff=self.user,
            detail={"note_text": "Test event"},
            event_type="manual_note",
        )
        self.assertIsNotNone(event1.dedup_hash)

        with self.assertRaises(ValidationError):
            JobEvent.objects.create(
                job=self.job,
                staff=self.user,
                detail={"note_text": "Test event"},
                event_type="manual_note",
            )

    def test_create_safe_method_prevents_duplicates(self):
        """Retry-safe creation must return the existing note, not error or duplicate.

        This catches callers that use ``create_safe`` during retry flows and
        expect idempotent success when the same manual note was already stored.
        """
        event1, created1 = JobEvent.create_safe(
            job=self.job,
            staff=self.user,
            detail={"note_text": "Test event"},
            event_type="manual_note",
        )
        self.assertTrue(created1)

        event2, created2 = JobEvent.create_safe(
            job=self.job,
            staff=self.user,
            detail={"note_text": "Test event"},
            event_type="manual_note",
        )
        self.assertFalse(created2)
        self.assertEqual(event1.id, event2.id)

    def test_service_prevents_duplicate_events(self):
        """The REST service must collapse immediate duplicate submissions.

        This catches frontend retry/double-click regressions by going through
        the same service boundary used by the API and proving only one note row
        is stored.
        """
        description = "Test service event"

        result1 = JobRestService.add_job_event(self.job.id, description, self.user)
        self.assertTrue(result1["success"])
        self.assertFalse(result1.get("duplicate_prevented", False))

        result2 = JobRestService.add_job_event(self.job.id, description, self.user)
        self.assertTrue(result2["success"])
        self.assertTrue(result2.get("duplicate_prevented", False))

        events = JobEvent.objects.filter(
            job=self.job,
            staff=self.user,
            detail__note_text=description,
            event_type="manual_note",
        )
        self.assertEqual(events.count(), 1)

    def test_different_users_can_create_same_event(self):
        """Deduplication must not erase another staff member's identical note.

        This catches over-broad dedup identity that keys only on job and note
        text, which would lose audit history when two users record the same
        observation.
        """
        user2 = Staff.objects.create_user(
            email="test2@example.com",
            password="testpass123",
            first_name="Test2",
            last_name="User",
        )

        description = "Same description"

        result1 = JobRestService.add_job_event(self.job.id, description, self.user)
        self.assertTrue(result1["success"])

        result2 = JobRestService.add_job_event(self.job.id, description, user2)
        self.assertTrue(result2["success"])
        self.assertFalse(result2.get("duplicate_prevented", False))

        events = JobEvent.objects.filter(
            job=self.job, detail__note_text=description, event_type="manual_note"
        )
        self.assertEqual(events.count(), 2)

    def test_automatic_events_not_affected(self):
        """Automatic audit events must not be collapsed like manual notes.

        This catches a dedup refactor that applies manual-note rules to status
        changes and would hide repeated workflow transitions from the audit log.
        """
        detail = {
            "changes": [
                {
                    "field_name": "Status",
                    "old_value": "Draft",
                    "new_value": "In Progress",
                }
            ]
        }
        for i in range(3):
            JobEvent.objects.create(
                job=self.job,
                staff=self.user,
                detail=detail,
                event_type="status_changed",
            )

        events = JobEvent.objects.filter(job=self.job, event_type="status_changed")
        self.assertEqual(events.count(), 3)

    def test_manual_note_dedup_identity_normalises_text_only_within_same_user(self):
        """Manual note identity should ignore text case/spacing but keep staff.

        This catches two plausible mistakes: failing to collapse harmless text
        variations from the same user, or collapsing another user's matching
        note and losing who recorded it.
        """
        first = JobEvent.objects.create(
            job=self.job,
            staff=self.user,
            detail={"note_text": "  Same Observation  "},
            event_type="manual_note",
        )
        user2 = Staff.objects.create_user(
            email="identity2@example.com",
            password="testpass123",
            first_name="Identity",
            last_name="User",
        )

        with self.assertRaises(ValidationError):
            JobEvent.objects.create(
                job=self.job,
                staff=self.user,
                detail={"note_text": "same observation"},
                event_type="manual_note",
            )

        second_user_event = JobEvent.objects.create(
            job=self.job,
            staff=user2,
            detail={"note_text": "same observation"},
            event_type="manual_note",
        )

        self.assertNotEqual(first.id, second_user_event.id)
