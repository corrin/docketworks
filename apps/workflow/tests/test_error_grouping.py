from datetime import timedelta

import pytest
from django.utils import timezone

from apps.workflow.models import AppError, XeroError
from apps.workflow.services.error_grouping import (
    list_grouped_app_errors,
    list_grouped_xero_errors,
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
