"""HTTP contracts and authorization for the leave management surface."""

import json
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.test import Client

from apps.accounting.types import PayrollLeaveBalance
from apps.accounts.models import Staff
from apps.job.models import Job
from apps.timesheet.models import LeaveRequest, LeaveType
from apps.timesheet.services import leave_service
from apps.timesheet.tests.test_leave_service import MONDAY, configure_type

pytestmark = pytest.mark.django_db

__all__ = ["MONDAY"]


def _request_payload(staff: Staff, code: str) -> dict[str, object]:
    return {
        "staff_id": str(staff.id),
        "leave_type_code": code,
        "start_date": MONDAY.isoformat(),
        "end_date": MONDAY.isoformat(),
        "note": "API leave",
        "days": [{"date": MONDAY.isoformat(), "hours": "4.000"}],
    }


def test_preview_create_list_update_and_cancel(
    manage_client: Client, worker: Staff, job: Job, superuser: Staff
) -> None:
    leave_type = configure_type(
        code=LeaveType.Code.ANNUAL,
        name="Annual Leave",
        job=job,
        superuser=superuser,
    )

    preview = manage_client.post(
        "/api/timesheets/leave/preview/",
        data=json.dumps(
            {
                "staff_id": str(worker.id),
                "start_date": MONDAY.isoformat(),
                "end_date": MONDAY.isoformat(),
            }
        ),
        content_type="application/json",
    )
    assert preview.status_code == 200
    assert preview.json()["available_hours"] == pytest.approx(8)

    created = manage_client.post(
        "/api/timesheets/leave/requests/",
        data=json.dumps(_request_payload(worker, leave_type.code)),
        content_type="application/json",
    )
    assert created.status_code == 200
    request_id = created.json()["request"]["id"]
    assert created.json()["request"]["total_hours"] == pytest.approx(4)

    current = manage_client.get("/api/timesheets/leave/requests/?scope=current&search=Wendy")
    assert current.status_code == 200
    assert [row["id"] for row in current.json()["requests"]] == [request_id]

    update_payload = _request_payload(worker, leave_type.code)
    update_payload.pop("staff_id")
    update_payload["note"] = "Changed"
    updated = manage_client.patch(
        f"/api/timesheets/leave/requests/{request_id}/",
        data=json.dumps(update_payload),
        content_type="application/json",
    )
    assert updated.status_code == 200
    assert updated.json()["request"]["note"] == "Changed"

    deleted = manage_client.delete(f"/api/timesheets/leave/requests/{request_id}/")
    assert deleted.status_code == 204
    assert not LeaveRequest.objects.exists()


def test_leave_and_settings_endpoints_are_superuser_only(worker_client: Client) -> None:
    assert worker_client.get("/api/timesheets/leave/requests/").status_code == 403
    assert worker_client.get("/api/timesheets/leave-settings/").status_code == 403
    refused = worker_client.patch(
        "/api/timesheets/leave-settings/",
        data=json.dumps({"leave_types": []}),
        content_type="application/json",
    )
    assert refused.status_code == 403


def test_settings_update_returns_every_mapping_after_saving(
    manage_client: Client, job: Job, superuser: Staff
) -> None:
    """The save's response is the whole page state, so no second GET is needed."""
    leave_type = configure_type(
        code=LeaveType.Code.ANNUAL,
        name="Annual Leave",
        job=job,
        superuser=superuser,
    )

    response = manage_client.patch(
        "/api/timesheets/leave-settings/",
        data=json.dumps(
            {
                "leave_types": [
                    {
                        "code": leave_type.code,
                        "display_name": "Holiday Leave",
                        "job_id": str(job.id),
                        "xero_pay_item_id": str(job.default_xero_pay_item_id),
                    }
                ]
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 200
    rows = {row["code"]: row for row in response.json()["leave_types"]}
    assert len(rows) == 5
    assert rows[LeaveType.Code.ANNUAL]["display_name"] == "Holiday Leave"
    assert rows[LeaveType.Code.ANNUAL]["configured"] is True


def test_settings_expose_only_the_fixed_leave_types(manage_client: Client) -> None:
    response = manage_client.get("/api/timesheets/leave-settings/")

    assert response.status_code == 200
    assert {row["code"] for row in response.json()["leave_types"]} == {
        LeaveType.Code.ANNUAL,
        LeaveType.Code.SICK,
        LeaveType.Code.UNPAID,
        LeaveType.Code.BEREAVEMENT,
        LeaveType.Code.PUBLIC_HOLIDAY,
    }


def test_unknown_request_is_a_404(manage_client: Client) -> None:
    assert manage_client.delete(f"/api/timesheets/leave/requests/{uuid4()}/").status_code == 404


class TestLeaveHttpContract:
    """What the API layer decides: which refusal becomes which status, and the wire shape.

    The rules themselves are asserted once at the service (test_leave_service.py).
    These pin only what HTTP adds, so nothing is asserted at two layers.
    """

    def test_an_unknown_employee_is_a_404(self, manage_client: Client) -> None:
        """create takes staff_id straight off the body, so without this it is a 500."""
        payload = {
            "staff_id": str(uuid4()),
            "leave_type_code": LeaveType.Code.ANNUAL,
            "start_date": MONDAY.isoformat(),
            "end_date": MONDAY.isoformat(),
            "note": None,
            "days": [{"date": MONDAY.isoformat(), "hours": "4.000"}],
        }

        response = manage_client.post(
            "/api/timesheets/leave/requests/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 404
        assert "Employee not found" in response.json()["detail"]

    def test_an_unknown_leave_type_is_a_400(self, manage_client: Client, worker: Staff) -> None:
        """The code is free text on the wire, so a bad one is a client error, not a fault."""
        payload = _request_payload(worker, "banana_leave")

        response = manage_client.post(
            "/api/timesheets/leave/requests/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "Unknown leave type" in response.json()["detail"]

    def test_a_refused_rule_reaches_the_operator_as_a_400_carrying_its_message(
        self, manage_client: Client, worker: Staff, job: Job, superuser: Staff
    ) -> None:
        """ADR 0038: the diagnosis travels, rather than being flattened to a 500."""
        configure_type(
            code=LeaveType.Code.ANNUAL, name="Annual Leave", job=job, superuser=superuser
        )
        payload = _request_payload(worker, LeaveType.Code.ANNUAL)
        payload["days"] = [{"date": MONDAY.isoformat(), "hours": "12.000"}]

        response = manage_client.post(
            "/api/timesheets/leave/requests/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "no more than the scheduled" in response.json()["detail"]

    def test_an_unknown_request_is_a_404_on_update_as_well_as_delete(
        self, manage_client: Client, worker: Staff
    ) -> None:
        payload = _request_payload(worker, LeaveType.Code.ANNUAL)
        payload.pop("staff_id")

        response = manage_client.patch(
            f"/api/timesheets/leave/requests/{uuid4()}/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 404

    def test_settings_refuse_an_unknown_code_as_404_and_an_unknown_job_as_400(
        self, manage_client: Client, job: Job
    ) -> None:
        """A deliberate asymmetry: the leave type is the resource, the job is an argument."""
        body = {
            "leave_types": [
                {
                    "code": "banana_leave",
                    "display_name": "Banana Leave",
                    "job_id": str(job.id),
                    "xero_pay_item_id": str(uuid4()),
                }
            ]
        }
        unknown_code = manage_client.patch(
            "/api/timesheets/leave-settings/",
            data=json.dumps(body),
            content_type="application/json",
        )
        assert unknown_code.status_code == 404
        assert "Leave type not found" in unknown_code.json()["detail"]

        body["leave_types"][0]["code"] = LeaveType.Code.ANNUAL
        body["leave_types"][0]["job_id"] = str(uuid4())
        unknown_job = manage_client.patch(
            "/api/timesheets/leave-settings/",
            data=json.dumps(body),
            content_type="application/json",
        )
        assert unknown_job.status_code == 400
        assert "Docketworks Job not found" in unknown_job.json()["detail"]

    def test_the_balance_endpoint_reads_two_query_params_and_returns_a_number(
        self,
        monkeypatch: pytest.MonkeyPatch,
        manage_client: Client,
        worker: Staff,
        job: Job,
        superuser: Staff,
    ) -> None:
        """ADR 0046: balance is a JSON number, which a bare Decimal would not be."""
        configure_type(
            code=LeaveType.Code.ANNUAL, name="Annual Leave", job=job, superuser=superuser
        )
        provider = SimpleNamespace(
            get_payroll_leave_balances=lambda _employee_id: [
                PayrollLeaveBalance(
                    leave_type_external_id="xero-annual_leave",
                    name="Annual Leave",
                    balance=Decimal("72.5"),
                    unit="Hours",
                )
            ]
        )
        monkeypatch.setattr(leave_service, "get_provider", lambda: provider)

        response = manage_client.get(
            f"/api/timesheets/leave/balance/?staff_id={worker.id}"
            f"&leave_type_code={LeaveType.Code.ANNUAL}"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["balance"] == 72.5
        assert isinstance(body["balance"], float)
        assert body["unit"] == "Hours"

    def test_office_closure_preview_reports_what_a_closure_would_cost(
        self, manage_client: Client, worker: Staff, job: Job, superuser: Staff
    ) -> None:
        configure_type(
            code=LeaveType.Code.PUBLIC_HOLIDAY,
            name="Public Holiday",
            job=job,
            superuser=superuser,
            uses_leave_api=False,
        )
        del worker

        response = manage_client.post(
            "/api/timesheets/leave/office-closure/preview/",
            data=json.dumps({"start_date": MONDAY.isoformat(), "end_date": MONDAY.isoformat()}),
            content_type="application/json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["available_staff"] >= 1
        assert isinstance(body["available_hours"], float)
        assert body["available_hours"] > 0

    def test_office_closure_creates_a_batch_over_the_whole_firm(
        self, manage_client: Client, worker: Staff, job: Job, superuser: Staff
    ) -> None:
        """The HTTP shape only; that one request lands per staff member is a service test."""
        configure_type(
            code=LeaveType.Code.PUBLIC_HOLIDAY,
            name="Public Holiday",
            job=job,
            superuser=superuser,
            uses_leave_api=False,
        )
        del worker

        response = manage_client.post(
            "/api/timesheets/leave/office-closure/",
            data=json.dumps(
                {
                    "start_date": MONDAY.isoformat(),
                    "end_date": MONDAY.isoformat(),
                    "note": "Shutdown",
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["batch_id"]
        assert len(body["requests"]) >= 1

    def test_history_and_current_are_separate_scopes_with_their_own_summary(
        self, manage_client: Client, worker: Staff, job: Job, superuser: Staff
    ) -> None:
        """The header tiles on the leave page read these figures."""
        configure_type(
            code=LeaveType.Code.ANNUAL, name="Annual Leave", job=job, superuser=superuser
        )
        manage_client.post(
            "/api/timesheets/leave/requests/",
            data=json.dumps(_request_payload(worker, LeaveType.Code.ANNUAL)),
            content_type="application/json",
        )

        current = manage_client.get("/api/timesheets/leave/requests/?scope=current").json()
        history = manage_client.get("/api/timesheets/leave/requests/?scope=history").json()

        assert len(current["requests"]) == 1
        assert history["requests"] == []
        # MONDAY is in the future, so it is upcoming rather than away-today.
        assert current["summary"]["upcoming_requests"] == 1
        assert current["summary"]["away_today"] == 0
        assert current["summary"]["upcoming_hours"] == pytest.approx(4)
