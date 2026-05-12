"""Tests for KanbanService.serialize_job_for_api()."""

from decimal import Decimal

from django.utils import timezone

from apps.client.models import Client
from apps.job.models import Job
from apps.job.services.kanban_service import KanbanService
from apps.testing import BaseTestCase


class TestSerializeJobForApi(BaseTestCase):
    """Tests for KanbanService.serialize_job_for_api()."""

    def setUp(self):
        self.client_obj = Client.objects.create(
            name="Test Client",
            xero_last_modified=timezone.now(),
        )

    def _create_job(self, pricing_methodology="time_materials"):
        """Create a job. Job.save() auto-creates CostSets (actual, quote, estimate)."""
        job = Job(
            client=self.client_obj,
            name="Test Job",
            pricing_methodology=pricing_methodology,
        )
        job.save(staff=self.test_staff)
        return job

    def _set_summary_revenue(self, cost_set, revenue):
        """Set the precomputed revenue total that serialize_job_for_api reads."""
        cost_set.summary = {"rev": float(revenue)}
        cost_set.save(update_fields=["summary"])

    def test_over_budget_when_tm_actual_exceeds_price_cap(self):
        """T&M jobs show over-budget when actual revenue exceeds the price cap."""
        job = self._create_job("time_materials")
        job.price_cap = Decimal("1000.00")
        job.save(staff=self.test_staff, update_fields=["price_cap"])
        self._set_summary_revenue(job.latest_actual, Decimal("1200.00"))
        self._set_summary_revenue(job.latest_quote, Decimal("5000.00"))

        serialized = KanbanService.serialize_job_for_api(job)

        self.assertTrue(serialized["over_budget"])

    def test_not_over_budget_when_tm_actual_within_price_cap(self):
        """T&M jobs do not show over-budget when actual revenue stays within the cap."""
        job = self._create_job("time_materials")
        job.price_cap = Decimal("1000.00")
        job.save(staff=self.test_staff, update_fields=["price_cap"])
        self._set_summary_revenue(job.latest_actual, Decimal("900.00"))
        self._set_summary_revenue(job.latest_quote, Decimal("500.00"))

        serialized = KanbanService.serialize_job_for_api(job)

        self.assertFalse(serialized["over_budget"])

    def test_fixed_price_uses_quote_revenue_threshold(self):
        """Fixed-price jobs compare actual revenue against quote revenue, not price cap."""
        job = self._create_job("fixed_price")
        job.price_cap = Decimal("1000.00")
        job.save(staff=self.test_staff, update_fields=["price_cap"])
        self._set_summary_revenue(job.latest_actual, Decimal("1200.00"))
        self._set_summary_revenue(job.latest_quote, Decimal("1500.00"))

        serialized = KanbanService.serialize_job_for_api(job)

        self.assertFalse(serialized["over_budget"])
