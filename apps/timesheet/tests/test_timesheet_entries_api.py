"""API tests for the management day view: GET /api/job/timesheet/entries/.

The entry page reads any staff member's day of time lines through this
endpoint; it is management surface (superuser only), unlike the self-service
workshop endpoints that serve only the caller's own lines.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import Client

from apps.accounts.models import Staff
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

WEDNESDAY = WEEK_START + timedelta(days=2)
THURSDAY = WEEK_START + timedelta(days=3)

URL = "/api/job/timesheet/entries/"


def entries_url(staff: Staff, target_date: str) -> str:
    return f"{URL}?staff_id={staff.id}&date={target_date}"


class TestAuth:
    def test_office_staff_are_not_enough(self, office_staff: Staff, worker: Staff) -> None:
        response = authenticated_client(office_staff).get(entries_url(worker, "2026-05-06"))
        assert response.status_code == 403

    def test_anonymous_is_rejected(self, worker: Staff) -> None:
        assert Client().get(entries_url(worker, "2026-05-06")).status_code == 401


class TestRetrieve:
    def test_returns_staff_day_in_entry_seq_order(
        self, manage_client: Client, job: Job, worker: Staff, other_worker: Staff
    ) -> None:
        """Only the requested staff member's time lines for the date, in entry order."""
        first = make_time_line(job, worker, accounting_date=WEDNESDAY, hours="2.000")
        second = make_time_line(job, worker, accounting_date=WEDNESDAY, hours="3.000")
        make_time_line(job, other_worker, accounting_date=WEDNESDAY)  # other staff
        make_time_line(job, worker, accounting_date=THURSDAY)  # other date

        response = manage_client.get(entries_url(worker, WEDNESDAY.isoformat()))

        assert response.status_code == 200
        body = response.json()
        assert [line["id"] for line in body["cost_lines"]] == [str(first.id), str(second.id)]
        line = body["cost_lines"][0]
        assert line["entry_seq"] == first.entry_seq
        assert line["quantity"] == "2.000"
        assert line["meta"]["staff_id"] == str(worker.id)
        assert line["total_cost"] == pytest.approx(2 * 48.0)
        assert line["total_rev"] == pytest.approx(2 * 120.0)

    def test_lines_carry_their_job_identity(
        self, manage_client: Client, job: Job, worker: Staff
    ) -> None:
        """The grid renders per-row job text from the line, so each line names its job."""
        make_time_line(job, worker, accounting_date=WEDNESDAY)

        [line] = manage_client.get(entries_url(worker, WEDNESDAY.isoformat())).json()["cost_lines"]

        assert line["job_id"] == str(job.id)
        assert line["job_number"] == job.job_number
        assert line["job_name"] == job.name
        assert line["company_name"] == "Timesheet Test Company"

    def test_summary_math(self, manage_client: Client, job: Job, worker: Staff) -> None:
        make_time_line(job, worker, accounting_date=WEDNESDAY, hours="2.000")
        make_time_line(job, worker, accounting_date=WEDNESDAY, hours="1.000", is_billable=False)

        body = manage_client.get(entries_url(worker, WEDNESDAY.isoformat())).json()

        summary = body["summary"]
        assert summary["total_hours"] == pytest.approx(3.0)
        assert summary["billable_hours"] == pytest.approx(2.0)
        assert summary["non_billable_hours"] == pytest.approx(1.0)
        assert summary["total_cost"] == pytest.approx(3 * 48.0)
        assert summary["total_revenue"] == pytest.approx(3 * 120.0)
        assert summary["entry_count"] == 2
        assert summary["scheduled_hours"] == pytest.approx(
            float(worker.get_scheduled_hours(WEDNESDAY))
        )

    def test_staff_block_and_date_echo(self, manage_client: Client, worker: Staff) -> None:
        """An empty day still identifies the staff member and echoes the date."""
        body = manage_client.get(entries_url(worker, WEDNESDAY.isoformat())).json()

        assert body["date"] == WEDNESDAY.isoformat()
        assert body["staff"]["id"] == str(worker.id)
        assert body["staff"]["first_name"] == "Wendy"
        assert body["staff"]["last_name"] == "Workshop"
        assert body["staff"]["name"]
        assert body["cost_lines"] == []
        assert body["summary"]["entry_count"] == 0

    def test_material_lines_are_not_timesheet_entries(
        self, manage_client: Client, job: Job, worker: Staff
    ) -> None:
        """A material line on the same day never appears in the timesheet view."""
        make_time_line(job, worker, accounting_date=WEDNESDAY)
        CostLine(
            cost_set=job.cost_sets.get(kind="actual"),
            kind="material",
            desc="Steel",
            quantity=Decimal("1.000"),
            unit_cost=Decimal("10.00"),
            unit_rev=Decimal("12.00"),
            accounting_date=WEDNESDAY,
            ext_refs={},
            meta={},
        ).save()

        body = manage_client.get(entries_url(worker, WEDNESDAY.isoformat())).json()

        assert len(body["cost_lines"]) == 1
        assert body["cost_lines"][0]["kind"] == "time"

    def test_unknown_staff_404s(self, manage_client: Client) -> None:
        response = manage_client.get(
            f"{URL}?staff_id=00000000-0000-0000-0000-000000000000&date=2026-05-06"
        )
        assert response.status_code == 404

    def test_bad_date_400s(self, manage_client: Client, worker: Staff) -> None:
        response = manage_client.get(entries_url(worker, "06/05/2026"))
        assert response.status_code == 400
