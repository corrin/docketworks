from datetime import timedelta

import pytest
from django.utils import timezone

from apps.workflow.models import AppError, XeroError
from apps.workflow.services.error_grouping import (
    list_grouped_app_errors,
    list_grouped_xero_errors,
    mark_app_error_group_resolved,
    mark_app_error_group_unresolved,
)


@pytest.fixture
def app_errors(db):
    now = timezone.now()
    AppError.objects.create(message="Failure A", app="workflow", severity=40)
    old = AppError.objects.create(message="Failure A", app="workflow", severity=40)
    AppError.objects.all().update(timestamp=now - timedelta(days=2))
    AppError.objects.create(message="Failure A", app="workflow", severity=40)
    AppError.objects.create(message="Failure B", app="job", severity=30)
    resolved = AppError.objects.create(message="Failure C", app="workflow", severity=40)
    resolved.resolved = True
    resolved.save(update_fields=["resolved"])
    return {"old": old, "resolved": resolved}


def test_groups_unresolved_by_default(app_errors):
    payload = list_grouped_app_errors(limit=50, offset=0)

    messages = [row["message"] for row in payload["results"]]
    assert "Failure A" in messages
    assert "Failure B" in messages
    assert "Failure C" not in messages


def test_group_has_count_and_first_last_seen(app_errors):
    payload = list_grouped_app_errors(limit=50, offset=0)
    group_a = next(row for row in payload["results"] if row["message"] == "Failure A")

    assert group_a["occurrence_count"] == 3
    assert group_a["first_seen"] < group_a["last_seen"]


def test_includes_resolved_when_requested(app_errors):
    payload = list_grouped_app_errors(limit=50, offset=0, resolved=True)
    messages = [row["message"] for row in payload["results"]]
    assert messages == ["Failure C"]


def test_filters_by_app(app_errors):
    payload = list_grouped_app_errors(limit=50, offset=0, app="job")
    messages = [row["message"] for row in payload["results"]]
    assert messages == ["Failure B"]


def test_xero_errors_grouped(db):
    XeroError.objects.create(
        message="Skipping bill X",
        entity="Bill",
        reference_id="b1",
        kind="Xero",
    )
    XeroError.objects.create(
        message="Skipping bill X",
        entity="Bill",
        reference_id="b1",
        kind="Xero",
    )
    payload = list_grouped_xero_errors(limit=50, offset=0)

    assert len(payload["results"]) == 1
    assert payload["results"][0]["occurrence_count"] == 2


def test_mark_group_resolved_cascades(db):
    staff_kwargs = {
        "email": "tester@example.test",
        "first_name": "T",
        "last_name": "E",
        "password_needs_reset": False,
    }
    from apps.accounts.models import Staff

    staff = Staff.objects.create(**staff_kwargs)
    for _ in range(3):
        AppError.objects.create(message="Recurring", app="workflow", severity=40)

    count = mark_app_error_group_resolved("Recurring", staff)
    assert count == 3
    assert AppError.objects.filter(resolved=True).count() == 3
    assert all(
        err.resolved_by_id == staff.id
        for err in AppError.objects.filter(message="Recurring")
    )


def test_mark_group_unresolved_clears(db):
    from apps.accounts.models import Staff

    staff = Staff.objects.create(
        email="tester2@example.test",
        first_name="T",
        last_name="E",
        password_needs_reset=False,
    )
    AppError.objects.create(message="R", app="workflow", severity=40, resolved=True)
    AppError.objects.create(message="R", app="workflow", severity=40, resolved=True)

    count = mark_app_error_group_unresolved("R", staff)
    assert count == 2
    assert AppError.objects.filter(resolved=False).count() == 2


def test_regression_creates_new_unresolved_group(db):
    from apps.accounts.models import Staff

    staff = Staff.objects.create(
        email="tester3@example.test",
        first_name="T",
        last_name="E",
        password_needs_reset=False,
    )
    AppError.objects.create(message="Regress", app="workflow", severity=40)
    mark_app_error_group_resolved("Regress", staff)
    # New occurrence arrives after resolution
    AppError.objects.create(message="Regress", app="workflow", severity=40)

    payload = list_grouped_app_errors(limit=50, offset=0)
    regress = [r for r in payload["results"] if r["message"] == "Regress"]
    assert len(regress) == 1
    assert regress[0]["occurrence_count"] == 1
