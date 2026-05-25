"""Tests for Kanban drag reorder priority persistence."""

from django.contrib.auth import get_user_model

from apps.client.models import Client
from apps.job.models import Job, JobEvent
from apps.job.services.kanban_service import KanbanService
from apps.testing import BaseTestCase
from apps.workflow.models import XeroPayItem

User = get_user_model()


class KanbanReorderPriorityTest(BaseTestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="reorder@example.com",
            password="testpass123",
            first_name="Reorder",
            last_name="Tester",
        )
        self.client = Client.objects.create(
            name="Reorder Client",
            email="reorder-client@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        self.xero_pay_item = XeroPayItem.get_ordinary_time()

    def _make_job(self, name, status="in_progress"):
        job = Job(
            name=name,
            client=self.client,
            created_by=self.user,
            default_xero_pay_item=self.xero_pay_item,
            status=status,
        )
        job.save(staff=self.user)
        return job

    def _ordered_names(self, status="in_progress"):
        return list(
            Job.objects.filter(status=status)
            .order_by("-priority", "-created_at")
            .values_list("name", flat=True)
        )

    def test_reorder_below_visible_anchor_uses_canonical_lower_neighbour(self):
        self._make_job("Bottom")
        self._make_job("Hidden")
        anchor = self._make_job("Anchor")
        mover = self._make_job("Mover")

        KanbanService.reorder_job(
            job_id=mover.pk,
            anchor_job_id=str(anchor.pk),
            placement="below",
            staff=self.user,
        )

        self.assertEqual(
            self._ordered_names(),
            ["Anchor", "Mover", "Hidden", "Bottom"],
        )
        event = JobEvent.objects.filter(job=mover).order_by("-timestamp").first()
        self.assertEqual(
            event.description,
            "Priority decreased from 1st to 2nd of 4 in In Progress",
        )
        self.assertNotIn("800", event.description)

    def test_reorder_above_visible_anchor(self):
        anchor = self._make_job("Anchor")
        mover = self._make_job("Mover")
        self._make_job("Top")

        KanbanService.reorder_job(
            job_id=mover.pk,
            anchor_job_id=str(anchor.pk),
            placement="above",
            staff=self.user,
        )

        self.assertEqual(self._ordered_names(), ["Top", "Mover", "Anchor"])

    def test_reorder_without_anchor_places_at_top_of_target_status(self):
        mover = self._make_job("Mover", status="in_progress")

        KanbanService.reorder_job(
            job_id=mover.pk,
            new_status="quoting",
            staff=self.user,
        )

        self.assertEqual(self._ordered_names("in_progress"), [])
        self.assertEqual(self._ordered_names("quoting"), ["Mover"])

    def test_rejects_self_anchor(self):
        mover = self._make_job("Mover")

        with self.assertRaisesMessage(
            ValueError, "Reorder anchor cannot be the moved job"
        ):
            KanbanService.reorder_job(
                job_id=mover.pk,
                anchor_job_id=str(mover.pk),
                placement="below",
                staff=self.user,
            )

    def test_rejects_anchor_in_different_status(self):
        mover = self._make_job("Mover", status="in_progress")
        anchor = self._make_job("Anchor", status="quoting")

        with self.assertRaisesMessage(
            ValueError, "Reorder anchor must be in the target status"
        ):
            KanbanService.reorder_job(
                job_id=mover.pk,
                anchor_job_id=str(anchor.pk),
                placement="below",
                staff=self.user,
            )
