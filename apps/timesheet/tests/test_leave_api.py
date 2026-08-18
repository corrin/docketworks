"""HTTP contracts and authorization for the leave management surface."""

import json
from uuid import uuid4

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.timesheet.models import LeaveRequest, LeaveType
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
