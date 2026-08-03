"""API tests for /api/quoting/scheduled-tasks/ and /scheduled-task-executions/.

These are the four operations ``frontend/schema.yml`` tags ``quoting``. The
schedule they list is the in-code one from ``config/celery.py``; the tests
override ``current_app.conf.beat_schedule`` so they assert on the endpoint's
behaviour rather than on whichever tasks happen to be scheduled today.
"""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from celery import current_app
from celery.schedules import crontab
from django.test import Client
from django.utils import timezone
from django_celery_results.models import TaskResult

from apps.accounts.models import Staff
from apps.company.tests.conftest import authenticate

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.quoting.tests.urls"),
]

TASKS_URL = "/api/quoting/scheduled-tasks/"
EXECUTIONS_URL = "/api/quoting/scheduled-task-executions/"


@pytest.fixture
def beat_schedule() -> Iterator[dict[str, dict[str, Any]]]:
    """Replace the app's beat schedule with a known two-entry one."""
    schedule: dict[str, dict[str, Any]] = {
        "nightly_paid_flag": {
            "task": "apps.job.tasks.set_paid_flag_task",
            "schedule": crontab(minute="0", hour="2"),
        },
        "frequent_phone_sync": {
            "task": "apps.crm.tasks.sync_phone_calls_task",
            "schedule": timedelta(minutes=5),
        },
    }
    original = current_app.conf.beat_schedule
    current_app.conf.beat_schedule = schedule
    yield schedule
    current_app.conf.beat_schedule = original


def make_execution(
    *,
    task_id: str,
    task_name: str,
    periodic_task_name: str | None,
    status: str = "SUCCESS",
) -> TaskResult:
    """Record a task execution the way django-celery-results' backend does."""
    return TaskResult.objects.create(
        task_id=task_id,
        task_name=task_name,
        periodic_task_name=periodic_task_name,
        status=status,
        content_type="application/json",
        content_encoding="utf-8",
    )


@pytest.mark.usefixtures("beat_schedule")
class TestScheduledTaskList:
    def test_lists_the_in_code_beat_schedule_sorted_by_name(self, client: Client) -> None:
        body = client.get(TASKS_URL).json()

        assert body["count"] == 2
        assert [row["name"] for row in body["results"]] == [
            "frequent_phone_sync",
            "nightly_paid_flag",
        ]
        assert body["results"][0]["task"] == "apps.crm.tasks.sync_phone_calls_task"
        assert body["next"] is None
        assert body["previous"] is None

    def test_ids_are_stable_positions_in_the_sorted_schedule(self, client: Client) -> None:
        rows = client.get(TASKS_URL).json()["results"]

        assert [row["id"] for row in rows] == [1, 2]
        again = client.get(TASKS_URL).json()["results"]
        assert [row["id"] for row in again] == [1, 2]

    def test_renders_a_crontab_and_an_interval_as_human_strings(self, client: Client) -> None:
        by_name = {row["name"]: row["schedule"] for row in client.get(TASKS_URL).json()["results"]}

        assert by_name["nightly_paid_flag"].startswith("0 2 * * *")
        assert by_name["frequent_phone_sync"] == "5.00 minutes"

    def test_every_in_code_entry_reports_as_enabled(self, client: Client) -> None:
        rows = client.get(TASKS_URL).json()["results"]

        assert all(row["enabled"] is True for row in rows)

    def test_last_run_at_comes_from_the_newest_recorded_execution(self, client: Client) -> None:
        make_execution(
            task_id="old",
            task_name="apps.job.tasks.set_paid_flag_task",
            periodic_task_name="nightly_paid_flag",
        )
        newest = make_execution(
            task_id="new",
            task_name="apps.job.tasks.set_paid_flag_task",
            periodic_task_name="nightly_paid_flag",
        )
        TaskResult.objects.filter(task_id="old").update(
            date_done=timezone.now() - timedelta(days=1)
        )

        by_name = {
            row["name"]: row["last_run_at"] for row in client.get(TASKS_URL).json()["results"]
        }

        newest.refresh_from_db()
        assert by_name["nightly_paid_flag"] is not None
        assert by_name["nightly_paid_flag"].startswith(newest.date_done.strftime("%Y-%m-%dT%H:%M"))
        assert by_name["frequent_phone_sync"] is None

    def test_search_matches_the_entry_name_or_the_dotted_task(self, client: Client) -> None:
        by_name = client.get(TASKS_URL, {"search": "phone"}).json()
        assert [row["name"] for row in by_name["results"]] == ["frequent_phone_sync"]

        by_task = client.get(TASKS_URL, {"search": "apps.job.tasks"}).json()
        assert [row["name"] for row in by_task["results"]] == ["nightly_paid_flag"]

    def test_retrieve_returns_one_entry_by_its_listed_id(self, client: Client) -> None:
        response = client.get(f"{TASKS_URL}1/")

        assert response.status_code == 200
        assert response.json()["name"] == "frequent_phone_sync"

    def test_retrieve_is_404_for_an_id_outside_the_schedule(self, client: Client) -> None:
        assert client.get(f"{TASKS_URL}99/").status_code == 404


@pytest.mark.usefixtures("beat_schedule")
class TestScheduledTaskAuth:
    def test_workshop_staff_may_not_read_the_schedule(self, workshop_staff: Staff) -> None:
        client = Client()
        authenticate(client, workshop_staff)

        assert client.get(TASKS_URL).status_code == 403

    def test_anonymous_callers_are_rejected(self) -> None:
        assert Client().get(TASKS_URL).status_code == 401


class TestScheduledTaskExecutionList:
    def test_ad_hoc_executions_are_excluded(self, client: Client) -> None:
        make_execution(
            task_id="beat-1",
            task_name="apps.job.tasks.set_paid_flag_task",
            periodic_task_name="nightly_paid_flag",
        )
        make_execution(
            task_id="webhook-1",
            task_name="apps.crm.tasks.rematch_phone_calls_task",
            periodic_task_name=None,
        )
        make_execution(
            task_id="webhook-2",
            task_name="apps.crm.tasks.rematch_phone_calls_task",
            periodic_task_name="",
        )

        body = client.get(EXECUTIONS_URL).json()

        assert body["count"] == 1
        assert body["results"][0]["task_id"] == "beat-1"
        assert body["results"][0]["periodic_task_name"] == "nightly_paid_flag"

    def test_newest_execution_comes_first(self, client: Client) -> None:
        make_execution(task_id="first", task_name="apps.job.tasks.t", periodic_task_name="entry")
        make_execution(task_id="second", task_name="apps.job.tasks.t", periodic_task_name="entry")
        TaskResult.objects.filter(task_id="first").update(
            date_done=timezone.now() - timedelta(hours=1)
        )

        rows = client.get(EXECUTIONS_URL).json()["results"]

        assert [row["task_id"] for row in rows] == ["second", "first"]

    def test_search_matches_task_name_periodic_name_or_status(self, client: Client) -> None:
        make_execution(
            task_id="ok",
            task_name="apps.job.tasks.set_paid_flag_task",
            periodic_task_name="nightly_paid_flag",
        )
        make_execution(
            task_id="boom",
            task_name="apps.crm.tasks.sync_phone_calls_task",
            periodic_task_name="frequent_phone_sync",
            status="FAILURE",
        )

        by_status = client.get(EXECUTIONS_URL, {"search": "failure"}).json()
        assert [row["task_id"] for row in by_status["results"]] == ["boom"]

        by_periodic = client.get(EXECUTIONS_URL, {"search": "nightly"}).json()
        assert [row["task_id"] for row in by_periodic["results"]] == ["ok"]

        by_task = client.get(EXECUTIONS_URL, {"search": "sync_phone"}).json()
        assert [row["task_id"] for row in by_task["results"]] == ["boom"]

    def test_pages_at_fifty_rows_and_links_the_next_page(self, client: Client) -> None:
        for index in range(51):
            make_execution(
                task_id=f"run-{index:03d}",
                task_name="apps.job.tasks.t",
                periodic_task_name="entry",
            )

        first = client.get(EXECUTIONS_URL).json()
        assert first["count"] == 51
        assert len(first["results"]) == 50
        assert first["next"] is not None
        assert "page=2" in first["next"]
        assert first["previous"] is None

        second = client.get(EXECUTIONS_URL, {"page": 2}).json()
        assert len(second["results"]) == 1
        assert second["next"] is None
        assert "page=1" in second["previous"]

    def test_an_out_of_range_page_is_404(self, client: Client) -> None:
        assert client.get(EXECUTIONS_URL, {"page": 7}).status_code == 404

    def test_retrieve_returns_one_beat_fired_execution(self, client: Client) -> None:
        execution = make_execution(
            task_id="beat-1",
            task_name="apps.job.tasks.set_paid_flag_task",
            periodic_task_name="nightly_paid_flag",
        )

        body = client.get(f"{EXECUTIONS_URL}{execution.id}/").json()

        assert body["task_id"] == "beat-1"
        assert body["status"] == "SUCCESS"

    def test_retrieve_of_an_ad_hoc_execution_is_404(self, client: Client) -> None:
        execution = make_execution(
            task_id="webhook-1",
            task_name="apps.crm.tasks.rematch_phone_calls_task",
            periodic_task_name=None,
        )

        assert client.get(f"{EXECUTIONS_URL}{execution.id}/").status_code == 404
