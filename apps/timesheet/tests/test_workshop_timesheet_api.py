"""API tests for the workshop "my time" self-service surface.

``/api/job/workshop/timesheets/`` is the one timesheet surface open to ordinary
workshop staff, and the whole safety story is ownership: a staff member may
read and write only their OWN entries. Those rules are asserted here for every
verb, alongside the pricing the entries pick up from the shared rate pipeline.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.timesheet.models import TimesheetEvent
from apps.timesheet.tests.conftest import (
    WEEK_START,
    authenticated_client,
    make_leave_job,
    make_staff,
    make_time_line,
)

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.timesheet.tests.urls"),
]

URL = "/api/job/workshop/timesheets/"
ENTRY_DATE = WEEK_START


def _entry_id(entry: dict[str, object]) -> str:
    """The created entry's id, narrowed for the type checker."""
    entry_id = entry["id"]
    assert isinstance(entry_id, str)
    return entry_id


def _create(client: Client, job: Job, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "job_id": str(job.id),
        "accounting_date": ENTRY_DATE.isoformat(),
        "hours": "4.00",
        "description": "Fabrication",
    }
    payload.update(overrides)
    response = client.post(URL, data=payload, content_type="application/json")
    assert response.status_code == 201, response.content
    body: dict[str, object] = response.json()
    return body


class TestAuth:
    def test_anonymous_is_rejected(self) -> None:
        assert Client().get(URL).status_code == 401

    def test_any_authenticated_staff_may_read(self, worker_client: Client) -> None:
        assert worker_client.get(URL).status_code == 200

    def test_office_staff_may_use_it_too(self, office_staff: Staff) -> None:
        """Any authenticated staff member may book their own workshop time."""
        response = authenticated_client(office_staff).get(URL)
        assert response.status_code == 200


class TestList:
    def test_defaults_to_today_and_summarises(
        self, worker_client: Client, job: Job, worker: Staff
    ) -> None:
        today = timezone.localdate()
        make_time_line(job, worker, accounting_date=today, hours="5.000")
        make_time_line(job, worker, accounting_date=today, hours="3.000", is_billable=False)

        body = worker_client.get(URL).json()

        assert body["date"] == today.isoformat()
        assert len(body["entries"]) == 2
        assert body["summary"] == {
            "total_hours": 8.0,
            "billable_hours": 5.0,
            "non_billable_hours": 3.0,
        }

    def test_only_the_callers_own_entries_are_listed(
        self, worker_client: Client, job: Job, worker: Staff, other_worker: Staff
    ) -> None:
        mine = make_time_line(job, worker, accounting_date=ENTRY_DATE, hours="2.000")
        make_time_line(job, other_worker, accounting_date=ENTRY_DATE, hours="7.000")

        body = worker_client.get(f"{URL}?date={ENTRY_DATE.isoformat()}").json()

        assert [entry["id"] for entry in body["entries"]] == [str(mine.id)]
        assert body["summary"]["total_hours"] == 2.0

    def test_bad_date_is_400(self, worker_client: Client) -> None:
        response = worker_client.get(f"{URL}?date=05-05-2026")
        assert response.status_code == 400
        assert "YYYY-MM-DD" in response.json()["detail"]


class TestCreate:
    def test_entry_is_priced_and_owned_by_the_caller(
        self, worker_client: Client, job: Job, worker: Staff
    ) -> None:
        body = _create(worker_client, job)

        assert body["hours"] == 4.0
        assert body["job_number"] == job.job_number
        assert body["company_name"] == "Timesheet Test Company"
        assert body["is_billable"] is True
        assert body["wage_rate_multiplier"] == 1.0
        line = CostLine.objects.get(id=_entry_id(body))
        assert line.staff_id == worker.id
        assert line.meta["staff_id"] == str(worker.id)
        assert line.meta["created_from_timesheet"] is True
        assert line.unit_cost == Decimal("48.00")
        assert line.unit_rev == Decimal("120.00")
        assert line.xero_pay_item is not None
        # Workshop staff bookings await office approval.
        assert line.approved is False

    def test_overtime_multiplier_selects_the_overtime_pay_item(
        self, worker_client: Client, job: Job
    ) -> None:
        body = _create(worker_client, job, wage_rate_multiplier="1.5")

        line = CostLine.objects.get(id=_entry_id(body))
        assert line.unit_cost == Decimal("72.00")
        assert line.unit_rev == Decimal("180.00")
        assert line.xero_pay_item is not None
        assert line.xero_pay_item.name == "Time and one half"

    def test_non_billable_entry_earns_no_revenue(self, worker_client: Client, job: Job) -> None:
        body = _create(worker_client, job, is_billable=False)

        assert body["is_billable"] is False
        assert body["bill_rate_multiplier"] == 0.0
        assert CostLine.objects.get(id=_entry_id(body)).unit_rev == Decimal("0.00")

    def test_start_and_end_times_round_trip(self, worker_client: Client, job: Job) -> None:
        body = _create(worker_client, job, start_time="08:00:00", end_time="12:00:00")

        assert body["start_time"] == "08:00:00"
        assert body["end_time"] == "12:00:00"

    def test_leave_job_entry_is_leave_not_billable_work(
        self, worker_client: Client, company: Company, superuser: Staff
    ) -> None:
        """The canonical job-aware pipeline treats leave as non-billable."""
        # Opus: Claimed by its category, as an onboarded instance has it: whether leave
        # is paid comes from the LeaveType now, not from the pay item's name, and
        # an unmapped leave item is refused rather than assumed paid.
        leave_job = make_leave_job(company, superuser, "Sick Leave")

        body = _create(worker_client, leave_job, wage_rate_multiplier="1.5")

        assert body["is_billable"] is False
        assert body["wage_rate_multiplier"] == 1.0
        line = CostLine.objects.get(id=_entry_id(body))
        assert line.unit_rev == Decimal("0.00")
        assert line.xero_pay_item is not None
        assert line.xero_pay_item.name == "Sick Leave"

    def test_staff_without_a_wage_rate_cannot_book_time(
        self, job: Job, unpaid_worker: Staff
    ) -> None:
        """A missing wage rate is refused by staff name, never costed at zero."""
        response = authenticated_client(unpaid_worker).post(
            URL,
            data={
                "job_id": str(job.id),
                "accounting_date": ENTRY_DATE.isoformat(),
                "hours": "4.00",
            },
            content_type="application/json",
        )

        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "Wage rate is not configured" in detail
        assert "Unpriced Person" in detail
        assert not CostLine.objects.filter(staff=unpaid_worker).exists()

    def test_unknown_job_is_404(self, worker_client: Client) -> None:
        response = worker_client.post(
            URL,
            data={
                "job_id": "00000000-0000-0000-0000-000000000000",
                "accounting_date": ENTRY_DATE.isoformat(),
                "hours": "1.00",
            },
            content_type="application/json",
        )
        assert response.status_code == 404


class TestRequestValidation:
    """Numeric and text fields must retain their API bounds.

    Unbounded, a workshop staff member could book negative hours, which lands
    negative cost and revenue in the actual CostSet and every total built on it
    (the costing surface has always rejected negative quantities).
    """

    def _post(self, client: Client, job: Job, **overrides: object) -> tuple[int, str]:
        """POST a create payload and return (status code, body text)."""
        payload: dict[str, object] = {
            "job_id": str(job.id),
            "accounting_date": ENTRY_DATE.isoformat(),
            "hours": "4.00",
        }
        payload.update(overrides)
        response = client.post(URL, data=payload, content_type="application/json")
        return response.status_code, response.content.decode()

    def test_negative_hours_are_rejected(self, worker_client: Client, job: Job) -> None:
        status_code, body = self._post(worker_client, job, hours="-4.00")

        assert status_code == 422, body
        assert not CostLine.objects.filter(cost_set__job=job).exists()

    def test_zero_hours_are_rejected(self, worker_client: Client, job: Job) -> None:
        assert self._post(worker_client, job, hours="0.00")[0] == 422

    def test_hours_above_the_field_limit_are_rejected(
        self, worker_client: Client, job: Job
    ) -> None:
        assert self._post(worker_client, job, hours="100000.00")[0] == 422

    def test_over_long_description_is_rejected(self, worker_client: Client, job: Job) -> None:
        assert self._post(worker_client, job, description="x" * 256)[0] == 422

    def test_negative_wage_multiplier_is_a_field_error_not_a_pay_item_error(
        self, worker_client: Client, job: Job
    ) -> None:
        """The bound must catch it before the pay-item lookup produces a confusing message."""
        status_code, body = self._post(worker_client, job, wage_rate_multiplier="-1.00")

        assert status_code == 422, body
        assert "No Xero pay item found" not in body

    def test_negative_bill_multiplier_is_rejected(self, worker_client: Client, job: Job) -> None:
        assert self._post(worker_client, job, bill_rate_multiplier="-0.50")[0] == 422

    def test_negative_hours_are_rejected_on_patch(self, worker_client: Client, job: Job) -> None:
        entry = _create(worker_client, job)

        response = worker_client.patch(
            URL,
            data={"entry_id": entry["id"], "hours": "-1.00"},
            content_type="application/json",
        )

        assert response.status_code == 422, response.content
        assert CostLine.objects.get(id=_entry_id(entry)).quantity == Decimal("4.000")


class TestTimeConsistency:
    """When both times are present they must agree with each other and with hours.

    The calendar client derives ``hours`` from the start/end pair, but the wire
    carries all three, so a direct caller could book "08:00-09:00, 8 hours" and
    the payroll cost would silently disagree with the calendar block.
    """

    def test_end_at_or_before_start_is_rejected(self, worker_client: Client, job: Job) -> None:
        payload: dict[str, object] = {
            "job_id": str(job.id),
            "accounting_date": ENTRY_DATE.isoformat(),
            "hours": "4.00",
            "start_time": "12:00:00",
            "end_time": "08:00:00",
        }
        response = worker_client.post(URL, data=payload, content_type="application/json")

        assert response.status_code == 400, response.content
        assert "after" in response.json()["detail"]
        assert not CostLine.objects.filter(cost_set__job=job).exists()

    def test_hours_disagreeing_with_the_times_are_rejected(
        self, worker_client: Client, job: Job
    ) -> None:
        payload: dict[str, object] = {
            "job_id": str(job.id),
            "accounting_date": ENTRY_DATE.isoformat(),
            "hours": "8.00",
            "start_time": "08:00:00",
            "end_time": "09:00:00",
        }
        response = worker_client.post(URL, data=payload, content_type="application/json")

        assert response.status_code == 400, response.content
        assert not CostLine.objects.filter(cost_set__job=job).exists()

    def test_hours_matching_the_times_are_accepted(self, worker_client: Client, job: Job) -> None:
        body = _create(worker_client, job, hours="1.50", start_time="08:00:00", end_time="09:30:00")

        assert body["hours"] == 1.5

    def test_times_without_hours_agreement_is_checked_on_patch(
        self, worker_client: Client, job: Job
    ) -> None:
        """A PATCH is validated against the merged entry, not the patch alone."""
        entry = _create(
            worker_client, job, hours="4.00", start_time="08:00:00", end_time="12:00:00"
        )

        response = worker_client.patch(
            URL,
            data={"entry_id": entry["id"], "end_time": "07:00:00"},
            content_type="application/json",
        )

        assert response.status_code == 400, response.content
        line = CostLine.objects.get(id=_entry_id(entry))
        assert line.meta["end_time"] == "12:00:00"

    def test_new_hours_redraw_the_finish_rather_than_being_refused_by_it(
        self, worker_client: Client, job: Job
    ) -> None:
        """Hours are what he is paid; the times are their picture, stepped over the breaks."""
        entry = _create(
            worker_client, job, hours="4.00", start_time="08:00:00", end_time="12:00:00"
        )

        response = worker_client.patch(
            URL,
            data={"entry_id": entry["id"], "hours": "6.00"},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        line = CostLine.objects.get(id=_entry_id(entry))
        assert line.quantity == Decimal("6.000")
        # Six hours from eight, over the day's three planned breaks.
        assert (line.meta["start_time"], line.meta["end_time"]) == ("08:00:00", "15:00:00")

    def test_clearing_a_time_lifts_the_agreement_requirement(
        self, worker_client: Client, job: Job
    ) -> None:
        entry = _create(
            worker_client, job, hours="4.00", start_time="08:00:00", end_time="12:00:00"
        )

        response = worker_client.patch(
            URL,
            data={"entry_id": entry["id"], "end_time": None, "hours": "6.00"},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        assert response.json()["hours"] == 6.0


class TestUpdate:
    def test_hours_and_description_are_updated(self, worker_client: Client, job: Job) -> None:
        entry = _create(worker_client, job)

        response = worker_client.patch(
            URL,
            data={"entry_id": entry["id"], "hours": "6.50", "description": "Welding"},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["hours"] == 6.5
        assert body["description"] == "Welding"

    def test_an_explicit_unbillable_choice_survives_a_move_off_a_shop_job(
        self, worker_client: Client, job: Job, superuser: Staff
    ) -> None:
        """move_time_line's source rule yields to billing the same request set."""
        shop_company = CompanyDefaults.get_solo().shop_company
        assert shop_company is not None
        shop = make_job(shop_company, superuser, name="Shop work", status="special")
        entry = _create(worker_client, shop, is_billable=False)

        response = worker_client.patch(
            URL,
            data={"entry_id": entry["id"], "job_id": str(job.id), "is_billable": False},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["is_billable"] is False
        assert CostLine.objects.get(id=_entry_id(entry)).unit_rev == Decimal("0.00")

    def test_moving_the_entry_to_another_job_reprices_it(
        self, worker_client: Client, job: Job, company: Company, superuser: Staff
    ) -> None:
        other = make_job(company, superuser, name="Other Job")
        other.labour_rates.update(charge_out_rate=Decimal("200.00"))
        entry = _create(worker_client, job)

        response = worker_client.patch(
            URL,
            data={"entry_id": entry["id"], "job_id": str(other.id)},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        assert response.json()["job_id"] == str(other.id)
        assert CostLine.objects.get(id=_entry_id(entry)).unit_rev == Decimal("200.00")

    def test_switching_to_overtime_reprices_cost_and_revenue(
        self, worker_client: Client, job: Job
    ) -> None:
        entry = _create(worker_client, job)

        response = worker_client.patch(
            URL,
            data={"entry_id": entry["id"], "wage_rate_multiplier": "2.0"},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        line = CostLine.objects.get(id=_entry_id(entry))
        assert line.unit_cost == Decimal("96.00")
        assert line.unit_rev == Decimal("240.00")

    def test_billable_can_be_toggled_off_and_back_on(self, worker_client: Client, job: Job) -> None:
        """Regression: re-enabling billing must replace a stored zero multiplier."""
        entry = _create(worker_client, job)

        off = worker_client.patch(
            URL,
            data={"entry_id": entry["id"], "is_billable": False},
            content_type="application/json",
        )
        assert off.status_code == 200
        assert CostLine.objects.get(id=_entry_id(entry)).unit_rev == Decimal("0.00")

        on = worker_client.patch(
            URL,
            data={"entry_id": entry["id"], "is_billable": True},
            content_type="application/json",
        )
        assert on.status_code == 200, on.content
        assert on.json()["is_billable"] is True
        assert CostLine.objects.get(id=_entry_id(entry)).unit_rev == Decimal("120.00")

    def test_wage_multiplier_patch_does_not_re_bill_a_non_billable_line(
        self, worker_client: Client, job: Job
    ) -> None:
        """Changing a wage multiplier must not re-bill a non-billable line."""
        entry = _create(worker_client, job, is_billable=False)
        assert CostLine.objects.get(id=_entry_id(entry)).unit_rev == Decimal("0.00")

        response = worker_client.patch(
            URL,
            data={"entry_id": entry["id"], "wage_rate_multiplier": "1.5"},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["is_billable"] is False
        assert body["bill_rate_multiplier"] == 0.0
        line = CostLine.objects.get(id=_entry_id(entry))
        assert line.unit_rev == Decimal("0.00")  # still not billed
        assert line.unit_cost == Decimal("72.00")  # but the wage change applied

    def test_another_staff_members_entry_is_403(
        self, worker_client: Client, job: Job, other_worker: Staff
    ) -> None:
        theirs = make_time_line(job, other_worker, accounting_date=ENTRY_DATE)

        response = worker_client.patch(
            URL,
            data={"entry_id": str(theirs.id), "hours": "1.00"},
            content_type="application/json",
        )

        assert response.status_code == 403
        assert "your own" in response.json()["detail"]

    def test_unknown_entry_is_404(self, worker_client: Client) -> None:
        response = worker_client.patch(
            URL,
            data={"entry_id": "00000000-0000-0000-0000-000000000000", "hours": "1.00"},
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_entry_id_alone_is_400(self, worker_client: Client, job: Job) -> None:
        entry = _create(worker_client, job)

        response = worker_client.patch(
            URL, data={"entry_id": entry["id"]}, content_type="application/json"
        )

        assert response.status_code == 400
        assert "At least one field" in response.json()["detail"]


class TestDelete:
    def test_own_entry_is_deleted(self, worker_client: Client, job: Job) -> None:
        entry = _create(worker_client, job)

        response = worker_client.delete(f"{URL}?entry_id={entry['id']}")

        assert response.status_code == 204
        assert not CostLine.objects.filter(id=_entry_id(entry)).exists()

    def test_another_staff_members_entry_is_403(
        self, worker_client: Client, job: Job, other_worker: Staff
    ) -> None:
        theirs = make_time_line(job, other_worker, accounting_date=ENTRY_DATE)

        response = worker_client.delete(f"{URL}?entry_id={theirs.id}")

        assert response.status_code == 403
        assert CostLine.objects.filter(id=theirs.id).exists()

    def test_unknown_entry_is_404(self, worker_client: Client) -> None:
        response = worker_client.delete(f"{URL}?entry_id=00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404


class TestLeaveManagedLines:
    """Leave lines appear in the day but belong to the leave workflow.

    They satisfy every my-time filter (kind, staff, date, meta.staff_id), so
    without a guard a workshop staff member could edit one — desyncing
    CostLine.quantity from LeaveDay.hours — or delete one, which LeaveDay's
    PROTECT turns into a 500.
    """

    def _leave_line(self, job: Job, worker: Staff) -> CostLine:
        line = make_time_line(job, worker, accounting_date=ENTRY_DATE, hours="8.000")
        line.managed_by = "leave"
        line.save()
        return line

    def test_leave_lines_are_listed(self, worker_client: Client, job: Job, worker: Staff) -> None:
        line = self._leave_line(job, worker)

        body = worker_client.get(f"{URL}?date={ENTRY_DATE.isoformat()}").json()

        assert [entry["id"] for entry in body["entries"]] == [str(line.id)]

    def test_a_leave_line_cannot_be_edited_here(
        self, worker_client: Client, job: Job, worker: Staff
    ) -> None:
        line = self._leave_line(job, worker)

        response = worker_client.patch(
            URL,
            data={"entry_id": str(line.id), "hours": "1.00"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "Timesheets → Leave" in response.json()["detail"]
        assert CostLine.objects.get(id=line.id).quantity == Decimal("8.000")

    def test_a_leave_line_cannot_be_deleted_here(
        self, worker_client: Client, job: Job, worker: Staff
    ) -> None:
        line = self._leave_line(job, worker)

        response = worker_client.delete(f"{URL}?entry_id={line.id}")

        assert response.status_code == 400
        assert "Timesheets → Leave" in response.json()["detail"]
        assert CostLine.objects.filter(id=line.id).exists()


class TestEntrySequencing:
    def test_entries_are_listed_in_entry_sequence(self, worker_client: Client, job: Job) -> None:
        first = _create(worker_client, job, description="First")
        second = _create(worker_client, job, description="Second")

        body = worker_client.get(f"{URL}?date={ENTRY_DATE.isoformat()}").json()

        assert [entry["id"] for entry in body["entries"]] == [first["id"], second["id"]]

    def test_entries_on_another_day_are_not_listed(self, worker_client: Client, job: Job) -> None:
        _create(worker_client, job)

        body = worker_client.get(
            f"{URL}?date={(ENTRY_DATE + timedelta(days=1)).isoformat()}"
        ).json()

        assert body["entries"] == []


class TestApprovalStatus:
    """What the worker sees and may change once the office approves (KAN-376)."""

    def test_worker_cannot_edit_or_delete_an_approved_entry(
        self, worker_client: Client, job: Job, worker: Staff
    ) -> None:
        line = make_time_line(job, worker, accounting_date=ENTRY_DATE, hours="4.000")

        edit = worker_client.patch(
            URL, data={"entry_id": str(line.id), "hours": "9.00"}, content_type="application/json"
        )
        delete = worker_client.delete(f"{URL}?entry_id={line.id}")

        assert edit.status_code == 409
        assert "approved" in edit.json()["detail"]
        assert delete.status_code == 409
        line.refresh_from_db()
        assert line.quantity == Decimal("4.000")

    def test_worker_still_changes_an_entry_that_is_waiting(
        self, worker_client: Client, job: Job, worker: Staff
    ) -> None:
        line = make_time_line(job, worker, accounting_date=ENTRY_DATE, approved=False)

        response = worker_client.patch(
            URL, data={"entry_id": str(line.id), "hours": "2.00"}, content_type="application/json"
        )

        assert response.status_code == 200
        assert response.json()["approved"] is False

    def test_office_edit_keeps_an_entry_approved(self, office_staff: Staff, job: Job) -> None:
        line = make_time_line(job, office_staff, accounting_date=ENTRY_DATE, hours="4.000")

        response = authenticated_client(office_staff).patch(
            URL, data={"entry_id": str(line.id), "hours": "5.00"}, content_type="application/json"
        )

        assert response.status_code == 200
        assert response.json()["approved"] is True
        line.refresh_from_db()
        assert line.quantity == Decimal("5.000")

    def test_an_entry_created_after_its_day_is_flagged_late(
        self, worker_client: Client, job: Job, worker: Staff
    ) -> None:
        """Late is judged in local dates: 00:10 the next morning is still the day before in UTC."""
        local = timezone.get_current_timezone()
        on_the_day = make_time_line(job, worker, accounting_date=ENTRY_DATE, hours="1.000")
        next_morning = make_time_line(job, worker, accounting_date=ENTRY_DATE, hours="2.000")
        leave = make_time_line(job, worker, accounting_date=ENTRY_DATE, hours="3.000")
        late_evening = datetime.combine(ENTRY_DATE, time(23, 30), tzinfo=local)
        just_after_midnight = datetime.combine(
            ENTRY_DATE + timedelta(days=1), time(0, 10), tzinfo=local
        )
        CostLine.objects.filter(pk=on_the_day.pk).update(created_at=late_evening)
        CostLine.objects.filter(pk=next_morning.pk).update(created_at=just_after_midnight)
        CostLine.objects.filter(pk=leave.pk).update(
            created_at=just_after_midnight, managed_by="leave"
        )

        body = worker_client.get(f"{URL}?date={ENTRY_DATE.isoformat()}").json()

        assert {entry["hours"]: entry["entered_late"] for entry in body["entries"]} == {
            1.0: False,
            2.0: True,
            3.0: False,
        }

    def test_the_week_splits_hours_into_approved_and_waiting(
        self, worker_client: Client, job: Job, worker: Staff, other_worker: Staff
    ) -> None:
        """Monday to Sunday, the caller's own: the figure the weekly screen holds back."""
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        make_time_line(
            job,
            worker,
            accounting_date=WEEK_START + timedelta(days=6),
            hours="3.000",
            approved=False,
        )
        make_time_line(
            job,
            worker,
            accounting_date=WEEK_START + timedelta(days=7),
            hours="5.000",
            approved=False,
        )
        make_time_line(job, other_worker, accounting_date=WEEK_START, hours="6.000", approved=False)

        midweek = WEEK_START + timedelta(days=2)
        body = worker_client.get(f"{URL}?date={midweek.isoformat()}").json()

        assert body["week"] == {"approved_hours": 8.0, "waiting_hours": 3.0}


WORKSHOP_LATITUDE = Decimal("-36.9220862")
WORKSHOP_LONGITUDE = Decimal("174.8000000")
# About 220 m north of the workshop: inside the 300 m circle.
ACROSS_THE_YARD = {"latitude": -36.9200862, "longitude": 174.8}
# About 1.1 km north: outside it.
DOWN_THE_ROAD = {"latitude": -36.9120862, "longitude": 174.8}


@pytest.fixture
def company_address() -> None:
    """Give the company the geocoded address the remote mark compares against."""
    defaults = CompanyDefaults.get_solo()
    defaults.latitude = WORKSHOP_LATITUDE
    defaults.longitude = WORKSHOP_LONGITUDE
    defaults.save(update_fields=["latitude", "longitude"])


class TestRemoteEntry:
    """`saved_remotely`: a worker's own save is marked unless it is placed at the workshop."""

    @pytest.mark.usefixtures("company_address")
    def test_a_save_is_marked_unless_the_phone_is_at_the_company_address(
        self, worker_client: Client, job: Job
    ) -> None:
        at_the_bench = _create(worker_client, job, location=ACROSS_THE_YARD)
        elsewhere = _create(worker_client, job, location=DOWN_THE_ROAD)
        no_location = _create(worker_client, job)

        assert at_the_bench["remote_entry"] is False
        assert elsewhere["remote_entry"] is True
        assert no_location["remote_entry"] is True

    @pytest.mark.usefixtures("company_address")
    def test_office_staff_are_not_marked(self, office_staff: Staff, job: Job) -> None:
        entry = _create(authenticated_client(office_staff), job)

        assert entry["remote_entry"] is False

    def test_a_company_without_an_address_marks_nothing(
        self, worker_client: Client, job: Job
    ) -> None:
        defaults = CompanyDefaults.get_solo()
        defaults.latitude = None
        defaults.longitude = None
        defaults.save(update_fields=["latitude", "longitude"])

        entry = _create(worker_client, job)

        assert entry["remote_entry"] is False

    @pytest.mark.usefixtures("company_address")
    def test_an_edit_can_set_the_mark_but_never_clears_it(
        self, worker_client: Client, job: Job
    ) -> None:
        entry_id = _entry_id(_create(worker_client, job, location=ACROSS_THE_YARD))

        def edit(description: str, **location: object) -> bool:
            response = worker_client.patch(
                URL,
                data={"entry_id": entry_id, "description": description, **location},
                content_type="application/json",
            )
            assert response.status_code == 200, response.content
            marked: bool = response.json()["remote_entry"]
            return marked

        assert edit("from the workshop", location=ACROSS_THE_YARD) is False
        assert edit("from home") is True
        assert edit("back at the workshop", location=ACROSS_THE_YARD) is True


class TestOfficeActsForAWorker:
    """The office corrects a worker's entry; it does not send it back (KAN-376)."""

    def test_workshop_user_cannot_read_another_persons_day(
        self, worker_client: Client, job: Job, other_worker: Staff
    ) -> None:
        make_time_line(job, other_worker, accounting_date=ENTRY_DATE)

        response = worker_client.get(
            f"{URL}?date={ENTRY_DATE.isoformat()}&staff_id={other_worker.id}"
        )

        assert response.status_code == 403
        assert "office staff" in response.json()["detail"]

    def test_office_reads_the_day_of_the_person_it_names(
        self, office_staff: Staff, job: Job, worker: Staff
    ) -> None:
        theirs = make_time_line(job, worker, accounting_date=ENTRY_DATE, hours="2.000")
        make_time_line(job, office_staff, accounting_date=ENTRY_DATE, hours="7.000")

        body = (
            authenticated_client(office_staff)
            .get(f"{URL}?date={ENTRY_DATE.isoformat()}&staff_id={worker.id}")
            .json()
        )

        assert [entry["id"] for entry in body["entries"]] == [str(theirs.id)]
        assert body["summary"]["total_hours"] == 2.0

    def test_office_correction_prices_at_the_workers_rate(self, job: Job, worker: Staff) -> None:
        """The entry stays the worker's: their wage, not the office user's, prices it."""
        cheaper_office = make_staff(
            "timesheet-cheap-office@example.com",
            is_office_staff=True,
            base_wage_rate=Decimal("10.00"),
            xero_user_id="",
        )
        line = make_time_line(job, worker, accounting_date=ENTRY_DATE, approved=False)

        response = authenticated_client(cheaper_office).patch(
            URL,
            data={"entry_id": str(line.id), "wage_rate_multiplier": "1.5"},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        line.refresh_from_db()
        assert line.unit_cost == Decimal("72.00")  # the worker's 48.00 at time and a half
        assert line.staff_id == worker.id
        assert line.approved is False, "correcting an entry is not approving it"
        [event] = TimesheetEvent.objects.filter(cost_line_id=line.id, event_type="entry_updated")
        assert event.staff_id == cheaper_office.id

    def test_office_corrects_an_approved_entry_and_it_stays_approved(
        self, office_staff: Staff, job: Job, worker: Staff
    ) -> None:
        line = make_time_line(job, worker, accounting_date=ENTRY_DATE, hours="4.000")

        response = authenticated_client(office_staff).patch(
            URL, data={"entry_id": str(line.id), "hours": "3.00"}, content_type="application/json"
        )

        assert response.status_code == 200, response.content
        line.refresh_from_db()
        assert line.quantity == Decimal("3.000")
        assert line.approved is True

    def test_time_the_office_enters_for_a_worker_is_theirs_and_approved(
        self, office_staff: Staff, job: Job, worker: Staff
    ) -> None:
        entry = _create(authenticated_client(office_staff), job, staff_id=str(worker.id))

        line = CostLine.objects.get(id=_entry_id(entry))
        assert line.staff_id == worker.id
        assert line.meta["staff_id"] == str(worker.id)
        assert line.unit_cost == Decimal("48.00")
        assert line.approved is True
        assert line.remote_entry is False

    def test_a_worker_cannot_enter_time_for_someone_else(
        self, worker_client: Client, job: Job, other_worker: Staff
    ) -> None:
        response = worker_client.post(
            URL,
            data={
                "job_id": str(job.id),
                "accounting_date": ENTRY_DATE.isoformat(),
                "hours": "1.00",
                "staff_id": str(other_worker.id),
            },
            content_type="application/json",
        )

        assert response.status_code == 403
        assert not CostLine.objects.filter(staff=other_worker).exists()
