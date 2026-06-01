"""Tests for KanbanService.serialize_job_for_api()."""

from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
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

    def test_get_all_active_jobs_preloads_serializer_relations(self):
        job = self._create_job()
        self._set_summary_revenue(job.latest_actual, Decimal("900.00"))
        self._set_summary_revenue(job.latest_quote, Decimal("500.00"))

        jobs = list(KanbanService.get_all_active_jobs())

        self.assertEqual([loaded.id for loaded in jobs], [job.id])
        with CaptureQueriesContext(connection) as captured:
            KanbanService.serialize_job_for_api(jobs[0])

        relation_queries = [
            query["sql"]
            for query in captured
            if any(
                table in query["sql"]
                for table in [
                    "accounts_staff",
                    "job_costset",
                    "client_clientcontact",
                ]
            )
            or (
                "client_client" in query["sql"]
                and "Demo Company Shop" not in query["sql"]
            )
        ]
        self.assertEqual(relation_queries, [])

    def test_get_jobs_by_status_preloads_serializer_relations(self):
        job = self._create_job()
        self._set_summary_revenue(job.latest_actual, Decimal("900.00"))
        self._set_summary_revenue(job.latest_quote, Decimal("500.00"))

        jobs = list(KanbanService.get_jobs_by_status(job.status))

        self.assertEqual([loaded.id for loaded in jobs], [job.id])
        with CaptureQueriesContext(connection) as captured:
            KanbanService.serialize_job_for_api(jobs[0])

        relation_queries = [
            query["sql"]
            for query in captured
            if any(
                table in query["sql"]
                for table in [
                    "accounts_staff",
                    "job_costset",
                    "client_clientcontact",
                ]
            )
            or (
                "client_client" in query["sql"]
                and "Demo Company Shop" not in query["sql"]
            )
        ]
        self.assertEqual(relation_queries, [])

    def test_serialize_jobs_for_api_resolves_shop_client_once_for_batch(self):
        shop_client = Client.objects.create(
            name="Demo Company Shop",
            xero_last_modified=timezone.now(),
        )
        shop_job = Job(
            client=shop_client,
            name="Shop Job",
            pricing_methodology="time_materials",
        )
        shop_job.save(staff=self.test_staff)
        self._set_summary_revenue(shop_job.latest_actual, Decimal("0.00"))
        self._set_summary_revenue(shop_job.latest_quote, Decimal("0.00"))

        work_job = self._create_job()
        self._set_summary_revenue(work_job.latest_actual, Decimal("900.00"))
        self._set_summary_revenue(work_job.latest_quote, Decimal("500.00"))

        jobs = list(
            Job.objects.filter(id__in=[shop_job.id, work_job.id])
            .select_related(
                "client",
                "contact",
                "created_by",
                "latest_quote",
                "latest_actual",
            )
            .prefetch_related("people")
            .order_by("name")
        )

        with CaptureQueriesContext(connection) as captured:
            serialized = KanbanService.serialize_jobs_for_api(jobs)

        shop_client_queries = [
            query["sql"]
            for query in captured
            if "client_client" in query["sql"] and "Demo Company Shop" in query["sql"]
        ]
        self.assertLessEqual(len(shop_client_queries), 2)
        self.assertEqual(
            {job["name"]: job["shop_job"] for job in serialized},
            {"Shop Job": True, "Test Job": False},
        )
