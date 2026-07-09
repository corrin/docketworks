"""Tests for KanbanService kanban job serialization."""

from decimal import Decimal
from typing import Any

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company, CompanyPersonLink, Person
from apps.job.models import Job
from apps.job.services.kanban_service import KanbanService
from apps.testing import BaseTestCase
from apps.workflow.models import CompanyDefaults


class TestSerializeJobForApi(BaseTestCase):
    """Tests for KanbanService kanban job serialization."""

    def setUp(self):
        self.client_obj = Company.objects.create(
            name="Test Company",
            xero_last_modified=timezone.now(),
        )
        self.shop_company = CompanyDefaults.get_solo().shop_company

    def _create_job(self, pricing_methodology="time_materials", name="Test Job"):
        """Create a job. Job.save() auto-creates CostSets (actual, quote, estimate)."""
        job = Job(
            company=self.client_obj,
            name=name,
            pricing_methodology=pricing_methodology,
        )
        job.save(staff=self.test_staff)
        return job

    def _set_summary_revenue(self, cost_set, revenue):
        """Set the precomputed revenue total that serialize_job_for_api reads."""
        cost_set.summary = {"rev": float(revenue)}
        cost_set.save(update_fields=["summary"])

    def _serialize_one(self, job: Job) -> dict[str, Any]:
        return KanbanService.serialize_jobs_for_api([job])[0]

    def _link(self, name: str) -> CompanyPersonLink:
        person = Person.objects.create(name=name)
        return CompanyPersonLink.objects.create(
            company=self.client_obj,
            person=person,
            xero_name=name,
        )

    def test_over_budget_when_tm_actual_exceeds_price_cap(self):
        """T&M jobs show over-budget when actual revenue exceeds the price cap."""
        job = self._create_job("time_materials")
        job.price_cap = Decimal("1000.00")
        job.save(staff=self.test_staff, update_fields=["price_cap"])
        self._set_summary_revenue(job.latest_actual, Decimal("1200.00"))
        self._set_summary_revenue(job.latest_quote, Decimal("5000.00"))

        self.assertTrue(self._serialize_one(job)["over_budget"])

    def test_not_over_budget_when_tm_actual_within_price_cap(self):
        """T&M jobs do not show over-budget when actual revenue stays within the cap."""
        job = self._create_job("time_materials")
        job.price_cap = Decimal("1000.00")
        job.save(staff=self.test_staff, update_fields=["price_cap"])
        self._set_summary_revenue(job.latest_actual, Decimal("900.00"))
        self._set_summary_revenue(job.latest_quote, Decimal("500.00"))

        self.assertFalse(self._serialize_one(job)["over_budget"])

    def test_fixed_price_uses_quote_revenue_threshold(self):
        """Fixed-price jobs compare actual revenue against quote revenue, not price cap."""
        job = self._create_job("fixed_price")
        job.price_cap = Decimal("1000.00")
        job.save(staff=self.test_staff, update_fields=["price_cap"])
        self._set_summary_revenue(job.latest_actual, Decimal("1200.00"))
        self._set_summary_revenue(job.latest_quote, Decimal("1500.00"))

        self.assertFalse(self._serialize_one(job)["over_budget"])

    def test_serialize_jobs_for_api_query_count_is_constant(self):
        """Serialization batches related data: O(1) queries regardless of job
        count, and no per-job relation lazy loads (each one stalls the dev/E2E
        n+1 guard with a ~20ms stack inspection)."""
        jobs = []
        for index in range(3):
            job = self._create_job(name=f"Batch Job {index}")
            link = self._link(f"Contact {index}")
            job.person = link.person
            job.save(staff=self.test_staff, update_fields=["person"])
            job.people.add(self.test_staff)
            self._set_summary_revenue(job.latest_actual, Decimal("100.00"))
            self._set_summary_revenue(job.latest_quote, Decimal("200.00"))
            jobs.append(job)

        plain_one = list(Job.objects.filter(id=jobs[0].id))
        plain_all = list(Job.objects.filter(id__in=[job.id for job in jobs]))

        with CaptureQueriesContext(connection) as captured_one:
            KanbanService.serialize_jobs_for_api(plain_one)
        with CaptureQueriesContext(connection) as captured_all:
            serialized = KanbanService.serialize_jobs_for_api(plain_all)

        self.assertEqual(len(serialized), 3)
        self.assertEqual(
            len(captured_one.captured_queries), len(captured_all.captured_queries)
        )
        self.assertLessEqual(len(captured_all.captured_queries), 6)

    def test_serialized_shape_for_fully_populated_job(self):
        """The rewritten serializer must keep the exact response contract the
        frontend Zod schema requires."""
        job = self._create_job(name="Shape Job")
        contact = self._link("Jane Doe")
        job.person = contact.person
        job.delivery_date = timezone.localdate()
        job.save(staff=self.test_staff, update_fields=["person", "delivery_date"])
        staff_b = Staff.objects.create_user(
            email="kanban-shape-b@example.com",
            password="testpass",
            first_name="Bob",
            last_name="Zeta",
        )
        staff_a = Staff.objects.create_user(
            email="kanban-shape-a@example.com",
            password="testpass",
            first_name="Ann",
            last_name="Alpha",
        )
        job.people.add(staff_b, staff_a)
        self._set_summary_revenue(job.latest_actual, Decimal("100.00"))
        self._set_summary_revenue(job.latest_quote, Decimal("200.00"))

        serialized = self._serialize_one(job)

        self.assertEqual(
            set(serialized),
            {
                "id",
                "name",
                "description",
                "job_number",
                "company_name",
                "person_name",
                "people",
                "status",
                "status_key",
                "rejected_flag",
                "paid",
                "fully_invoiced",
                "speed_quality_tradeoff",
                "created_by_id",
                "created_at",
                "updated_at",
                "delivery_date",
                "priority",
                "shop_job",
                "over_budget",
                "quote_revenue",
                "time_and_materials_revenue",
                "min_people",
                "max_people",
                "is_urgent",
                "badge_label",
                "badge_color",
            },
        )
        self.assertEqual(serialized["company_name"], "Test Company")
        self.assertEqual(serialized["person_name"], "Jane Doe")
        self.assertEqual(serialized["quote_revenue"], 200.0)
        self.assertEqual(serialized["time_and_materials_revenue"], 100.0)
        self.assertEqual(serialized["created_by_id"], str(self.test_staff.id))
        self.assertEqual(serialized["delivery_date"], job.delivery_date.isoformat())
        self.assertFalse(serialized["is_urgent"])
        # People sorted by (last_name, first_name), matching the old
        # prefetched Staff.Meta ordering
        self.assertEqual(
            [person["display_name"] for person in serialized["people"]],
            ["Ann Alpha", "Bob Zeta"],
        )
        self.assertIsNone(serialized["people"][0]["icon_url"])

    def test_serialize_jobs_for_api_resolves_shop_client_once_for_batch(self):
        shop_job = Job(
            company=self.shop_company,
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
            Job.objects.filter(id__in=[shop_job.id, work_job.id]).order_by("name")
        )

        with CaptureQueriesContext(connection) as captured:
            serialized = KanbanService.serialize_jobs_for_api(jobs)

        shop_client_queries = [
            query["sql"]
            for query in captured
            if "company_company" in query["sql"] and "Demo Company Shop" in query["sql"]
        ]
        self.assertEqual(shop_client_queries, [])
        self.assertEqual(
            {job["name"]: job["shop_job"] for job in serialized},
            {"Shop Job": True, "Test Job": False},
        )

    def test_non_shop_job_serializes_false_when_client_differs_from_configured_shop(
        self,
    ):
        job = self._create_job()
        self._set_summary_revenue(job.latest_actual, Decimal("900.00"))
        self._set_summary_revenue(job.latest_quote, Decimal("500.00"))

        serialized = KanbanService.serialize_jobs_for_api([job])

        self.assertFalse(serialized[0]["shop_job"])
