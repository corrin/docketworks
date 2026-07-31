"""Tests for the Finish Job completion checklist.

The checklist is advisory by design: these tests pin both that changes are
audited and that ticking a box never affects what a user can invoice or what
status a job is in.
"""

from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.accounting.services.invoice_calculation import calculate_invoice_amount
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.job.models import Job, JobCompletionChecklist, JobEvent
from apps.job.services.job_completion_checklist_service import (
    CHECKLIST_UPDATED_EVENT,
    ChecklistUpdateError,
    get_completion_checklist,
    update_completion_checklist,
)
from apps.testing import BaseAPITestCase, BaseTestCase


class TestCompletionChecklistService(BaseTestCase):
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

    # --- Reading ---

    def test_unconfirmed_job_reads_as_all_false_without_writing_a_row(self) -> None:
        checklist = get_completion_checklist(self.job)

        self.assertFalse(checklist.time_entries_complete)
        self.assertFalse(checklist.materials_complete)
        self.assertFalse(checklist.customer_approval_confirmed)
        self.assertIsNone(checklist.updated_at)
        self.assertIsNone(checklist.updated_by)
        self.assertFalse(JobCompletionChecklist.objects.filter(job=self.job).exists())

    # --- Partial updates ---

    def test_update_touches_only_the_named_item(self) -> None:
        update_completion_checklist(
            self.job, {"materials_complete": True}, self.test_staff
        )

        checklist = get_completion_checklist(self.job)
        self.assertTrue(checklist.materials_complete)
        self.assertFalse(checklist.time_entries_complete)
        self.assertFalse(checklist.customer_approval_confirmed)

    def test_update_records_who_and_when(self) -> None:
        checklist = update_completion_checklist(
            self.job, {"time_entries_complete": True}, self.test_staff
        )

        self.assertEqual(checklist.updated_by, self.test_staff)
        self.assertIsNotNone(checklist.updated_at)

    def test_second_update_preserves_the_first(self) -> None:
        update_completion_checklist(
            self.job, {"time_entries_complete": True}, self.test_staff
        )
        update_completion_checklist(
            self.job, {"customer_approval_confirmed": True}, self.test_staff
        )

        checklist = get_completion_checklist(self.job)
        self.assertTrue(checklist.time_entries_complete)
        self.assertTrue(checklist.customer_approval_confirmed)

    def test_unknown_item_is_rejected(self) -> None:
        with self.assertRaises(ChecklistUpdateError) as ctx:
            update_completion_checklist(
                self.job, {"everything_is_fine": True}, self.test_staff
            )

        self.assertIn("everything_is_fine", str(ctx.exception))
        self.assertFalse(JobCompletionChecklist.objects.filter(job=self.job).exists())

    def test_non_boolean_value_is_rejected(self) -> None:
        with self.assertRaises(ChecklistUpdateError):
            update_completion_checklist(
                self.job,
                {"materials_complete": "yes"},  # type: ignore[dict-item]  # the guard exists for untyped JSON off the wire
                self.test_staff,
            )

    def test_rejected_update_does_not_apply_its_valid_items(self) -> None:
        """An unknown key fails the whole payload rather than half-applying it."""
        with self.assertRaises(ChecklistUpdateError):
            update_completion_checklist(
                self.job,
                {"materials_complete": True, "nonsense": True},
                self.test_staff,
            )

        self.assertFalse(get_completion_checklist(self.job).materials_complete)

    # --- Audit history ---

    def test_each_changed_item_adds_one_history_event(self) -> None:
        update_completion_checklist(
            self.job,
            {"time_entries_complete": True, "materials_complete": True},
            self.test_staff,
        )

        events = JobEvent.objects.filter(
            job=self.job, event_type=CHECKLIST_UPDATED_EVENT
        )
        self.assertEqual(events.count(), 2)

    def test_history_event_records_item_values_and_staff(self) -> None:
        update_completion_checklist(
            self.job, {"customer_approval_confirmed": True}, self.test_staff
        )

        event = JobEvent.objects.get(job=self.job, event_type=CHECKLIST_UPDATED_EVENT)
        change = event.detail["changes"][0]
        self.assertEqual(change["field_name"], "Customer approval confirmed")
        self.assertEqual(change["old_value"], "No")
        self.assertEqual(change["new_value"], "Yes")
        self.assertEqual(event.staff, self.test_staff)
        self.assertIsNotNone(event.timestamp)

    def test_withdrawing_a_confirmation_is_audited(self) -> None:
        """The change most worth finding later is someone unticking a box."""
        update_completion_checklist(
            self.job, {"materials_complete": True}, self.test_staff
        )
        update_completion_checklist(
            self.job, {"materials_complete": False}, self.test_staff
        )

        events = JobEvent.objects.filter(
            job=self.job, event_type=CHECKLIST_UPDATED_EVENT
        ).order_by("timestamp")
        self.assertEqual(events.count(), 2)
        self.assertEqual(
            events[1].description, "Withdrew confirmation of all materials entered"
        )

    def test_confirmation_reads_as_plain_english_in_history(self) -> None:
        update_completion_checklist(
            self.job, {"time_entries_complete": True}, self.test_staff
        )

        event = JobEvent.objects.get(job=self.job, event_type=CHECKLIST_UPDATED_EVENT)
        self.assertEqual(event.description, "Confirmed all time entered")

    def test_setting_an_item_to_its_current_value_adds_no_event(self) -> None:
        update_completion_checklist(
            self.job, {"materials_complete": True}, self.test_staff
        )
        update_completion_checklist(
            self.job, {"materials_complete": True}, self.test_staff
        )

        self.assertEqual(
            JobEvent.objects.filter(
                job=self.job, event_type=CHECKLIST_UPDATED_EVENT
            ).count(),
            1,
        )

    # --- The checklist must not become a gate ---

    def test_checklist_does_not_change_job_status(self) -> None:
        original_status = self.job.status

        update_completion_checklist(
            self.job,
            {
                "time_entries_complete": True,
                "materials_complete": True,
                "customer_approval_confirmed": True,
            },
            self.test_staff,
        )

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, original_status)

    def test_invoicing_works_with_an_untouched_checklist(self) -> None:
        """Nothing confirmed must not stand between a customer and an invoice."""
        self._add_actual_revenue(Decimal("500"))

        result = calculate_invoice_amount(self.job, mode="invoice_costs_to_date")

        self.assertEqual(result.calculated_amount, Decimal("500"))

    def test_invoice_amount_is_unchanged_by_confirmations(self) -> None:
        self._add_actual_revenue(Decimal("500"))
        before = calculate_invoice_amount(
            self.job, mode="invoice_costs_to_date"
        ).calculated_amount

        update_completion_checklist(
            self.job,
            {"time_entries_complete": True, "materials_complete": True},
            self.test_staff,
        )

        after = calculate_invoice_amount(
            self.job, mode="invoice_costs_to_date"
        ).calculated_amount
        self.assertEqual(before, after)

    def _add_actual_revenue(self, revenue: Decimal) -> None:
        from datetime import date

        from apps.job.models.costing import CostLine

        CostLine.objects.create(
            cost_set=self.job.latest_actual,
            kind="adjust",
            desc="Test line",
            quantity=Decimal("1.000"),
            unit_cost=Decimal("0.00"),
            unit_rev=revenue,
            accounting_date=date.today(),
        )


class TestFinishJobEndpoint(BaseAPITestCase):
    """The generated client's read and partial-update operations."""

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
        # Changing a checklist item is an office action; the shared test_staff is
        # deliberately neither office nor workshop.
        self.office_staff = Staff.objects.create_user(
            email="office@example.com",
            password="testpass",
            first_name="Office",
            last_name="Person",
            is_office_staff=True,
        )
        self.client.force_login(self.office_staff)

    def test_get_returns_summary_and_checklist(self) -> None:
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("summary", response.data)
        self.assertIn("checklist", response.data)
        self.assertEqual(response.data["summary"]["basis"], "actual_revenue")
        self.assertFalse(response.data["checklist"]["materials_complete"])
        self.assertIsNone(response.data["checklist"]["updated_by_name"])

    def test_get_returns_currency_values_as_json_numbers(self) -> None:
        """Zod on the frontend validates numbers; DRF's default strings fail it."""
        payload = self.client.get(self.url).json()

        for field, value in payload["summary"].items():
            if field == "basis":
                continue
            self.assertIsInstance(value, (int, float), msg=f"{field} is not a number")

    def test_patch_applies_a_partial_update_and_returns_fresh_state(self) -> None:
        response = self.client.patch(
            self.url,
            data={"customer_approval_confirmed": True},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["checklist"]["customer_approval_confirmed"])
        self.assertFalse(response.data["checklist"]["materials_complete"])
        self.assertEqual(
            response.data["checklist"]["updated_by_name"],
            self.office_staff.get_display_full_name(),
        )

    def test_get_on_a_fixed_price_job_reports_the_quote_basis(self) -> None:
        """Exercises the quote prefetch branch under the n+1 middleware."""
        quoted_job = Job(
            company=self.client_obj,
            name="Quoted Job",
            pricing_methodology="fixed_price",
        )
        quoted_job.save(staff=self.test_staff)

        response = self.client.get(
            reverse("jobs:job_finish_rest", args=[quoted_job.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["summary"]["basis"], "quote")

    def test_patch_rejects_an_unknown_item(self) -> None:
        response = self.client.patch(
            self.url,
            data={"not_a_real_item": True},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
