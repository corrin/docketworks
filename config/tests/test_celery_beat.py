"""The beat schedule's contract with the scheduled-task endpoints.

Business risk: ``django_celery_results`` stores a task execution's originating
schedule in ``TaskResult.periodic_task_name``, filled from a message header that
``django_celery_beat`` would have set but an in-code ``beat_schedule`` does not.
Miss the header and executions are recorded with a NULL name, so the endpoints
that look executions up by that column report every scheduled task as never
having run — for the weekly scraper, that is indistinguishable from the Feb 2026
outage where the scrape silently stopped for eight months.

These tests are the reason a new beat entry cannot reintroduce that hole.
"""

import importlib
from datetime import timedelta

import pytest
from celery import Celery
from celery.app.task import Context
from celery.schedules import crontab

from config.celery import _with_periodic_task_headers, app


def test_every_beat_entry_carries_its_own_name_as_a_header() -> None:
    """The invariant the scheduled-task endpoints depend on, over the real schedule."""
    schedule = app.conf.beat_schedule
    assert schedule, "beat schedule is empty — this test would vacuously pass"

    for name, entry in schedule.items():
        headers = entry["options"]["headers"]
        assert headers["periodic_task_name"] == name, (
            f"beat entry {name!r} is stamped {headers.get('periodic_task_name')!r}; "
            "its executions would not be attributable to it"
        )


def test_every_beat_entry_names_an_importable_task() -> None:
    """A typo'd task path fails at runtime with no execution recorded at all."""
    for name, entry in app.conf.beat_schedule.items():
        module_path, _, attribute = entry["task"].rpartition(".")
        module = importlib.import_module(module_path)
        assert hasattr(module, attribute), (
            f"beat entry {name!r} points at a task that does not exist"
        )


def test_every_beat_entry_is_registered_under_its_scheduled_name() -> None:
    """The schedule dispatches by REGISTERED name, not by import path.

    hasattr alone cannot catch a task whose ``@shared_task(name=...)``
    diverges from its module path (apps.xero re-exports its worker task
    under apps.xero.tasks); an unregistered name schedules nothing, silently
    — the exact eight-months-dark failure this file's docstring cites.
    """
    for module in (
        "apps.xero.tasks",
        "apps.crm.tasks",
        "apps.job.tasks",
        "apps.quoting.tasks",
        "apps.purchasing.tasks",
        "apps.diagnostics.tasks",
    ):
        importlib.import_module(module)  # registration happens at import
    for name, entry in app.conf.beat_schedule.items():
        assert entry["task"] in app.tasks, (
            f"beat entry {name!r} names task {entry['task']!r} that is not registered with Celery"
        )


def test_a_stamped_entry_reaches_the_worker_as_request_periodic_task_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The end of the chain: our options -> published headers -> the attribute results reads.

    Asserting the options dict alone would pass even if Celery stopped
    propagating the header, which is the failure that actually loses the data.
    Dispatch happens on a scratch app with a memory broker because the project
    app runs eager under test, and eager execution skips the message layer
    entirely — the very layer under test here.
    """
    options = app.conf.beat_schedule["run_all_scrapers_weekly"]["options"]

    probe_app = Celery("beat_header_probe", broker="memory://", backend="cache+memory://")

    @probe_app.task(name="probe.capture")
    def probe() -> None: ...

    captured: list[dict[str, object]] = []
    send_task_message = probe_app.amqp.send_task_message

    def spy(
        producer: object, name: str, message: tuple[dict[str, object], ...], **kwargs: object
    ) -> object:
        # Keep the reference, not a copy: send_task_message merges the extra
        # headers into this very dict, so a snapshot taken here would miss them.
        captured.append(message[0])
        return send_task_message(producer, name, message, **kwargs)

    monkeypatch.setattr(probe_app.amqp, "send_task_message", spy)
    probe.apply_async(**options)

    published = captured[0]
    assert published["periodic_task_name"] == "run_all_scrapers_weekly"
    # getattr, not attribute access: Context resolves this dynamically, and this
    # is the exact expression django_celery_results uses (backends/database.py).
    assert getattr(Context(published), "periodic_task_name", None) == "run_all_scrapers_weekly"


def test_stamping_preserves_existing_options() -> None:
    """An entry that sets its own options (queue, expires) keeps them."""
    stamped = _with_periodic_task_headers(
        {
            "nightly": {
                "task": "apps.job.tasks.noop",
                "schedule": crontab(),
                "options": {"expires": 900},
            }
        }
    )

    assert stamped["nightly"]["options"] == {
        "expires": 900,
        "headers": {"periodic_task_name": "nightly"},
    }


def test_stamping_does_not_mutate_the_input() -> None:
    """Guards against the stamp leaking into a caller's dict and being applied twice."""
    original = {"nightly": {"task": "apps.job.tasks.noop", "schedule": crontab()}}

    _with_periodic_task_headers(original)

    assert "options" not in original["nightly"]


class TestXeroBeatEntries:
    """The three Xero entries the scheduler must carry.

    The hourly cadence is what keeps DocketWorks and Xero converged without
    anyone clicking Sync; the Saturday 02:00 entry is the only chance the
    30/90-day deep sync gets. Losing either is silent until the data drifts.
    Pinned here rather than in apps/xero/tests because layering forbids apps
    importing config.
    """

    def test_heartbeat_every_five_minutes(self) -> None:
        entry = app.conf.beat_schedule["xero_heartbeat_task"]
        assert entry["task"] == "apps.xero.tasks.xero_heartbeat_task"
        assert entry["schedule"] == crontab(minute="*/5")

    def test_regular_sync_hourly_at_quarter_past(self) -> None:
        entry = app.conf.beat_schedule["xero_regular_sync_task"]
        assert entry["task"] == "apps.xero.tasks.xero_regular_sync_task"
        assert entry["schedule"] == crontab(minute="15")

    def test_deep_sync_window_saturday_2am(self) -> None:
        entry = app.conf.beat_schedule["xero_30_day_sync_task"]
        assert entry["task"] == "apps.xero.tasks.xero_30_day_sync_task"
        assert entry["schedule"] == crontab(minute="0", hour="2", day_of_week="6")


class TestMaintenanceBeatEntries:
    """The catch-up parse and replay purge, whose loss is silent until data piles up.

    parse_unparsed_stock_items_task existed in this codebase for weeks with no
    beat entry at all — nothing failed, rows just stayed unparsed — so the
    entry is pinned the same way the Xero entries are. The replay purge is the
    only bound on workflow_sessionreplay* table growth.
    """

    def test_stock_catchup_parse_hourly_at_half_past(self) -> None:
        entry = app.conf.beat_schedule["parse_unparsed_stock_items_hourly"]
        assert entry["task"] == "apps.purchasing.tasks.parse_unparsed_stock_items_task"
        assert entry["schedule"] == crontab(minute="30")
        assert entry["kwargs"] == {"limit": 50}

    def test_session_replay_purge_daily_at_0130(self) -> None:
        entry = app.conf.beat_schedule["purge_old_session_replays_daily"]
        assert entry["task"] == "apps.diagnostics.tasks.purge_old_session_replays_task"
        assert entry["schedule"] == crontab(minute="30", hour="1")


def test_task_results_outlive_the_longest_schedule_interval() -> None:
    """last_run_at is derived from the newest TaskResult (nothing else stores it).

    Celery's default result_expires is ONE day, and the auto-installed
    celery.backend_cleanup deletes expired rows daily — so the weekly scrape's
    only execution record vanished mid-week and /scheduled-task-executions/
    reported the task as never run for most of every week. The expiry must
    cover the longest gap between firings (weekly) with margin.
    """
    expires = app.conf.result_expires
    assert expires is not None
    if isinstance(expires, int | float):
        expires = timedelta(seconds=expires)
    assert expires >= timedelta(days=8), (
        f"result_expires {expires!r} is shorter than the weekly scrape's interval; "
        "its TaskResult row is deleted before the next run and last_run_at reads null"
    )
