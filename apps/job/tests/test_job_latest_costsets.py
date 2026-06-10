"""Tests for required Job latest CostSet pointers."""

from django.db.models import RestrictedError

from apps.client.models import Client
from apps.job.models import Job
from apps.job.models.costing import CostSet
from apps.testing import BaseTestCase


class JobLatestCostSetCreationTests(BaseTestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(
            name="Latest CostSet Client",
            xero_last_modified="2024-01-01T00:00:00Z",
        )

    def _assert_initial_cost_sets(self, job: Job) -> None:
        job.refresh_from_db()

        self.assertEqual(job.latest_estimate.kind, "estimate")
        self.assertEqual(job.latest_estimate.job_id, job.id)
        self.assertEqual(job.latest_estimate.rev, 1)

        self.assertEqual(job.latest_quote.kind, "quote")
        self.assertEqual(job.latest_quote.job_id, job.id)
        self.assertEqual(job.latest_quote.rev, 1)

        self.assertEqual(job.latest_actual.kind, "actual")
        self.assertEqual(job.latest_actual.job_id, job.id)
        self.assertEqual(job.latest_actual.rev, 1)

        self.assertEqual(job.cost_sets.filter(kind="estimate").count(), 1)
        self.assertEqual(job.cost_sets.filter(kind="quote").count(), 1)
        self.assertEqual(job.cost_sets.filter(kind="actual").count(), 1)

    def test_manager_create_seeds_required_latest_cost_sets(self):
        job = Job.objects.create(
            client=self.client_obj,
            name="Manager create job",
            staff=self.test_staff,
        )

        self._assert_initial_cost_sets(job)

    def test_model_save_seeds_required_latest_cost_sets(self):
        job = Job(client=self.client_obj, name="Model save job")
        job.save(staff=self.test_staff)

        self._assert_initial_cost_sets(job)


class JobLatestCostSetDeletionTests(BaseTestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(
            name="Latest CostSet Deletion Client",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        self.job = Job.objects.create(
            client=self.client_obj,
            name="Deletion behavior job",
            staff=self.test_staff,
        )

    def test_latest_cost_set_cannot_be_deleted_directly(self):
        with self.assertRaises(RestrictedError):
            self.job.latest_quote.delete()

        self.assertTrue(CostSet.objects.filter(id=self.job.latest_quote_id).exists())

    def test_deleting_job_cascades_cost_sets(self):
        cost_set_ids = list(self.job.cost_sets.values_list("id", flat=True))

        self.job.delete()

        self.assertFalse(Job.objects.filter(id=self.job.id).exists())
        self.assertFalse(CostSet.objects.filter(id__in=cost_set_ids).exists())
