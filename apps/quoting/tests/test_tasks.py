"""The quoting app's beat-scheduled task.

Task NAMES are the operational contract — a beat entry names the task by string
— so the name is asserted, not just the behaviour.
"""

from unittest.mock import patch

import pytest

from apps.core.models import AppError
from apps.quoting.tasks import run_all_scrapers_task

pytestmark = [pytest.mark.django_db]

CALL_COMMAND = "apps.quoting.tasks.call_command"


class TestRunAllScrapersTask:
    def test_the_weekly_run_refreshes_known_products_not_just_new_ones(self) -> None:
        """Without --refresh-old the weekly run would never re-price anything."""
        with patch(CALL_COMMAND) as command:
            run_all_scrapers_task()

        command.assert_called_once_with("run_scrapers", refresh_old=True)

    def test_a_failure_is_persisted_with_context_and_re_raised(self) -> None:
        """ADR 0019: celery's own retry needs the exception; the operator needs the row."""
        with (
            patch(CALL_COMMAND, side_effect=RuntimeError("No scrapers configured")),
            pytest.raises(RuntimeError, match="No scrapers configured"),
        ):
            run_all_scrapers_task()

        error = AppError.objects.get(message="No scrapers configured")
        assert error.data is not None
        assert error.data["task"] == "run_all_scrapers_task"

    def test_the_task_name_matches_v1(self) -> None:
        assert run_all_scrapers_task.name == "apps.quoting.tasks.run_all_scrapers_task"
