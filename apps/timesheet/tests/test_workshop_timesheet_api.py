"""API tests for the workshop "my time" self-service surface.

``/api/job/workshop/timesheets/`` is the one timesheet surface open to ordinary
workshop staff, and the whole safety story is ownership: a staff member may
read and write only their OWN entries. Those rules are asserted here for every
verb, alongside the pricing the entries pick up from the shared rate pipeline.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.timesheet.tests.conftest import (
    WEEK_START,
    authenticated_client,
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
        """v1 gated on IsAuthenticated only — office staff book their own time here."""
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
            "total_cost": 8 * 48.0,
            "total_revenue": 8 * 120.0,
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
        # Workshop staff bookings await office approval (v1).
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
        """The canonical (job-aware) pipeline; v1's workshop copy billed leave."""
        from django.apps import apps as django_apps  # noqa: PLC0415

        leave_job = make_job(company, superuser, name="Sick Leave")
        leave_job.default_xero_pay_item = django_apps.get_model(
            "xero", "XeroPayItem"
        )._default_manager.get(name="Sick Leave", uses_leave_api=True)
        leave_job.save(staff=superuser, update_fields=["default_xero_pay_item", "updated_at"])

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
        """v1's workshop path costed these entries at 0.00; v2 refuses by name."""
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
    """v1's DRF serializers bounded every numeric and text field; so must v2.

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
        """v1 left the stored 0x bill multiplier in place, so re-enabling was a no-op."""
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
        """v1 set bill_rate_multiplier from the wage multiplier as a side effect, so
        bumping a non-billable line to 1.5x silently started billing the customer."""
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
