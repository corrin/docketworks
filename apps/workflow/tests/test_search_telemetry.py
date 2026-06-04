import json

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.workflow.models import SearchTelemetryEvent
from apps.workflow.services.search_telemetry import SearchTelemetryService


def test_search_click_endpoint_records_generic_event(db):
    staff = Staff.objects.create_user(
        email="search-telemetry@example.test",
        password="testpass",
        first_name="Search",
        last_name="Telemetry",
        is_office_staff=True,
    )
    api = APIClient()
    api.force_authenticate(user=staff)

    resp = api.post(
        "/api/search-events/click/",
        {
            "domain": "client",
            "query": "FUME",
            "selected_result_id": "client-123",
            "selected_label": "Fumecare Ltd",
            "selected_rank": 1,
            "result_count": 7,
            "source": "client_lookup",
            "metadata": {"extra": "future-safe"},
        },
        format="json",
    )

    assert resp.status_code == 200, resp.content
    event = SearchTelemetryEvent.objects.get()
    assert event.event_type == SearchTelemetryEvent.EventType.CLICK
    assert event.domain == SearchTelemetryEvent.Domain.CLIENT
    assert event.query == "FUME"
    assert event.normalized_query == "fume"
    assert event.selected_result_id == "client-123"
    assert event.selected_label == "Fumecare Ltd"
    assert event.selected_rank == 1
    assert event.result_count == 7
    assert event.metadata == {"extra": "future-safe"}


@pytest.mark.django_db
def test_search_telemetry_caps_displayed_results_at_100():
    SearchTelemetryService.log_search(
        request=None,
        domain="stock",
        source="stock_search",
        query="stainless",
        result_count=150,
        returned_result_ids=[f"stock-{index}" for index in range(150)],
        metadata={"results": [{"rank": index + 1} for index in range(150)]},
    )

    event = SearchTelemetryEvent.objects.get()
    assert event.result_count == 150
    assert event.returned_count == 100
    assert len(event.returned_result_ids) == 100
    assert len(event.metadata["results"]) == 100


@pytest.mark.django_db
def test_backfill_kanban_search_log_is_idempotent(tmp_path):
    payload = {
        "event": "kanban_search_results",
        "source": "advanced",
        "query": "977",
        "filters": {"universal_search": "977"},
        "result_count": 1,
        "results": [
            {
                "rank": 1,
                "job_id": "job-123",
                "job_number": 96977,
                "name": "Workshop Closed",
                "search_score": 85.0,
                "search_reasons": {"tokens": [{"reason": "job_number_contains"}]},
            }
        ],
    }
    log_path = tmp_path / "kanban_search.log"
    log_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    call_command("backfill_kanban_search_telemetry", path=str(log_path))
    call_command("backfill_kanban_search_telemetry", path=str(log_path))

    event = SearchTelemetryEvent.objects.get()
    assert event.domain == SearchTelemetryEvent.Domain.KANBAN
    assert event.event_type == SearchTelemetryEvent.EventType.SEARCH
    assert event.query == "977"
    assert event.returned_result_ids == ["job-123"]
    assert event.metadata["results"][0]["job_number"] == 96977
