"""Tests for the front-desk completion checklist.

The items are Job fields, so the audit trail comes from the job's own
field-change machinery. These tests pin that each tick is attributed and that
ticking nothing still lets a job be invoiced — the checklist records, it does
not gate.
"""

import uuid
from datetime import date
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from rest_framework.response import Response

from apps.accounting.services.invoice_calculation import calculate_invoice_amount
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.job.models import Job, JobEvent
from apps.job.models.costing import CostLine
from apps.testing import BaseAPITestCase

CHECKLIST_EVENT = "completion_checklist_updated"


class TestCompletionChecklist(BaseAPITestCase):
    def setUp(self) -> None:
        self.client_obj = Company.objects.create(
            name="Test Company",
            xero_last_modified=timezone.now(),
        )
        self.job = Job(
            company=self.client_obj,
            name="Test Job",
            pricing_methodology="time_materials",
        )
        self.job.save(staff=self.test_staff)
        self.url = reverse("jobs:job_finish_rest", args=[self.job.id])
        # Ticking an item is an office action; the shared test_staff is
        # deliberately neither office nor workshop.
        self.office_staff = Staff.objects.create_user(
            email="office@example.com",
            password="testpass",
            first_name="Office",
            last_name="Person",
            is_office_staff=True,
        )
        self.client.force_login(self.office_staff)

    def _patch(self, payload: dict[str, object]) -> Response:
        return self.client.patch(self.url, data=payload, format="json")

    # --- Reading ---

    def test_a_new_job_has_nothing_ticked(self) -> None:
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        for field in Job.COMPLETION_CHECKLIST_FIELDS:
            self.assertFalse(response.data["checklist"][field], msg=field)

    def test_every_item_is_exposed(self) -> None:
        """The API shape and the field tuple must not drift apart."""
        response = self.client.get(self.url)

        self.assertEqual(
            set(response.data["checklist"].keys()), set(Job.COMPLETION_CHECKLIST_FIELDS)
        )

    # --- Updating ---

    def test_a_missing_job_is_not_found(self) -> None:
        """A bad job id is a 404, not the 500 the old handler produced."""
        missing = reverse("jobs:job_finish_rest", args=[uuid.uuid4()])

        self.assertEqual(self.client.get(missing).status_code, 404)
        self.assertEqual(
            self.client.patch(
                missing, data={"released": True}, format="json"
            ).status_code,
            404,
        )

    def test_ticking_one_item_leaves_the_others_alone(self) -> None:
        response = self._patch({"materials_checked": True})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["checklist"]["materials_checked"])
        self.assertFalse(response.data["checklist"]["foreman_signed_off"])
        self.assertFalse(response.data["checklist"]["released"])

    def test_every_item_can_be_ticked(self) -> None:
        for field in Job.COMPLETION_CHECKLIST_FIELDS:
            with self.subTest(field=field):
                response = self._patch({field: True})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.data["checklist"][field])

    def test_a_tick_can_be_withdrawn(self) -> None:
        self._patch({"released": True})

        response = self._patch({"released": False})

        self.assertFalse(response.data["checklist"]["released"])

    def test_unknown_item_is_rejected(self) -> None:
        response = self._patch({"everything_is_fine": True})

        self.assertEqual(response.status_code, 400)

    def test_a_value_that_is_not_a_boolean_is_rejected(self) -> None:
        response = self._patch({"materials_checked": "maybe"})

        self.assertEqual(response.status_code, 400)

    def test_a_rejected_payload_applies_none_of_it(self) -> None:
        """An unknown key fails the whole payload rather than half-applying it."""
        response = self._patch({"materials_checked": True, "nonsense": True})

        self.assertEqual(response.status_code, 400)
        self.job.refresh_from_db()
        self.assertFalse(self.job.materials_checked)

    # --- Audit ---

    def test_each_changed_item_is_attributed_in_job_history(self) -> None:
        self._patch({"foreman_signed_off": True})

        event = JobEvent.objects.filter(
            job=self.job, event_type=CHECKLIST_EVENT
        ).latest("timestamp")
        self.assertEqual(event.staff, self.office_staff)
        self.assertEqual(event.description, "Foreman signed the job off")

    def test_withdrawing_a_tick_is_audited(self) -> None:
        self._patch({"released": True})
        self._patch({"released": False})

        events = JobEvent.objects.filter(
            job=self.job, event_type=CHECKLIST_EVENT
        ).order_by("timestamp")
        self.assertEqual(
            [e.description for e in events], ["Job released", "Job release withdrawn"]
        )

    def test_reticking_the_same_value_adds_no_event(self) -> None:
        self._patch({"materials_checked": True})
        self._patch({"materials_checked": True})

        self.assertEqual(
            JobEvent.objects.filter(job=self.job, event_type=CHECKLIST_EVENT).count(), 1
        )

    # --- The checklist records, it does not gate ---

    def test_ticking_everything_does_not_change_job_status(self) -> None:
        original_status = self.job.status

        for field in Job.COMPLETION_CHECKLIST_FIELDS:
            self._patch({field: True})

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, original_status)

    def test_an_untouched_checklist_does_not_block_invoicing(self) -> None:
        self._add_actual_revenue(Decimal("500"))

        result = calculate_invoice_amount(self.job, mode="invoice_costs_to_date")

        self.assertEqual(result.calculated_amount, Decimal("500"))

    def test_ticks_do_not_change_the_invoice_amount(self) -> None:
        self._add_actual_revenue(Decimal("500"))
        before = calculate_invoice_amount(
            self.job, mode="invoice_costs_to_date"
        ).calculated_amount

        self._patch({"timesheets_collected": True})
        self._patch({"materials_checked": True})

        self.job.refresh_from_db()
        after = calculate_invoice_amount(
            self.job, mode="invoice_costs_to_date"
        ).calculated_amount
        self.assertEqual(before, after)

    def _add_actual_revenue(self, revenue: Decimal) -> None:
        CostLine.objects.create(
            cost_set=self.job.latest_actual,
            kind="adjust",
            desc="Test line",
            quantity=Decimal("1.000"),
            unit_cost=Decimal("0.00"),
            unit_rev=revenue,
            accounting_date=date.today(),
        )
