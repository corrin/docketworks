"""The sync engine hands each entity's persist callable the run's tenant.

Business risk: a persist callable that cannot be called at all still lets the
entity report success. ``transform_pay_run`` grew a keyword-only ``tenant_id``
while the engine's ENTITY_CONFIGS entry passed the generic two arguments, so
every pay run raised TypeError into the per-item handler, was filed as an
AppError and skipped — and the run yielded "Completed sync of pay_runs" having
persisted nothing. Prod logged 60 of those an hour, under a green sync.

These tests drive the engine rather than the persist functions directly: the
functions were never broken. ``refresh_pay_runs`` mirrored pay runs correctly
throughout, which is why the operator path kept working and the hourly one did
not. Only the wiring between them was wrong, so only a test that crosses it
can fail when it breaks again.
"""

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from pytest_django.fixtures import SettingsWrapper

from apps.core.models import AppError
from apps.xero.models import XeroPayRun, XeroPaySlip
from apps.xero.sync import ENTITY_CONFIGS, XeroSyncEvent, sync_xero_data

pytestmark = pytest.mark.django_db

OURS = "tenant-ours"
FOREIGN = "tenant-foreign"
CALENDAR_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")


@pytest.fixture(autouse=True)
def _non_production_install(settings: SettingsWrapper) -> None:
    """DEBUG-off is the engine's production signal, and a production install
    aborts every entity when the tenant is not an onboarded one. These tenants
    are fixtures, so the run has to look like a dev install to reach persistence.
    """
    settings.DEBUG = True


def _xero_pay_run(pay_run_id: uuid.UUID) -> SimpleNamespace:
    """A Xero pay run carrying the fields the transform reads."""
    return SimpleNamespace(
        pay_run_id=pay_run_id,
        payroll_calendar_id=CALENDAR_ID,
        period_start_date=date(2026, 5, 4),
        period_end_date=date(2026, 5, 10),
        payment_date=date(2026, 5, 13),
        pay_run_status="Posted",
        pay_run_type="Scheduled",
        total_cost=100,
        total_pay=80,
        posted_date_time=datetime(2026, 5, 13, tzinfo=UTC),
    )


def _xero_pay_slip(pay_slip_id: uuid.UUID, pay_run_id: uuid.UUID) -> SimpleNamespace:
    """A Xero pay slip carrying the fields the transform reads."""
    return SimpleNamespace(
        pay_slip_id=pay_slip_id,
        pay_run_id=pay_run_id,
        employee_id=uuid.uuid4(),
        first_name="Ada",
        last_name="Lovelace",
        gross_earnings=960,
        tax=140,
        net_pay=820,
        timesheet_earnings_lines=[],
        leave_earnings_lines=[],
    )


def _run_entity(entity: str, items: list[Any], *, tenant_id: str) -> list[XeroSyncEvent]:
    """Drive one entity through the engine with a fetch that returns ``items``."""
    xero_type, our_type, _model, _api_method, persist, params, pagination = ENTITY_CONFIGS[entity]
    fetch = SimpleNamespace(**{xero_type: items})

    with patch("apps.xero.sync.time.sleep"):
        return list(
            sync_xero_data(
                xero_entity_type=xero_type,
                our_entity_type=our_type,
                xero_api_fetch_function=lambda **_kwargs: fetch,
                sync_function=persist,
                last_modified_time="2026-01-01",
                additional_params=params,
                pagination_mode=pagination,
                xero_tenant_id=tenant_id,
            )
        )


class TestPayRunsReachTheDatabase:
    def test_the_engine_persists_pay_runs_stamped_with_the_runs_tenant(self) -> None:
        pay_run_id = uuid.uuid4()

        _run_entity("pay_runs", [_xero_pay_run(pay_run_id)], tenant_id=OURS)

        row = XeroPayRun.objects.get(xero_id=pay_run_id)
        assert row.xero_tenant_id == OURS

    def test_a_failed_pay_run_batch_is_not_reported_as_a_completed_sync(self) -> None:
        """The shape of the original defect: errors filed, entity says Completed.

        Asserted together because either half alone passes in the broken world
        — the run did yield Completed, and it did file one AppError per pay
        run. Only "no errors AND the row landed" separates the two.
        """
        pay_run_id = uuid.uuid4()

        events = _run_entity("pay_runs", [_xero_pay_run(pay_run_id)], tenant_id=OURS)

        assert not AppError.objects.exists()
        assert XeroPayRun.objects.filter(xero_id=pay_run_id).exists()
        assert events[-1]["status"] == "Completed"

    def test_orphan_removal_leaves_another_tenants_pay_runs_alone(self) -> None:
        """Xero is master for pay runs, but only for the tenant being synced.

        The engine's own delete was ``exclude(xero_id__in=fetched)`` over the
        whole table, so syncing one organisation deleted the other's mirror.
        """
        ours = XeroPayRun.objects.create(
            xero_id=uuid.uuid4(),
            xero_tenant_id=OURS,
            period_start_date=date(2026, 4, 6),
            period_end_date=date(2026, 4, 12),
            payment_date=date(2026, 4, 15),
            pay_run_status="Posted",
            pay_run_type="Scheduled",
            raw_json={},
            xero_last_modified=datetime(2026, 4, 15, tzinfo=UTC),
        )
        foreign = XeroPayRun.objects.create(
            xero_id=uuid.uuid4(),
            xero_tenant_id=FOREIGN,
            period_start_date=date(2026, 4, 6),
            period_end_date=date(2026, 4, 12),
            payment_date=date(2026, 4, 15),
            pay_run_status="Posted",
            pay_run_type="Scheduled",
            raw_json={},
            xero_last_modified=datetime(2026, 4, 15, tzinfo=UTC),
        )

        _run_entity("pay_runs", [_xero_pay_run(uuid.uuid4())], tenant_id=OURS)

        assert not XeroPayRun.objects.filter(pk=ours.pk).exists()
        assert XeroPayRun.objects.filter(pk=foreign.pk).exists()


class TestPaySlipsCarryTheRunsTenant:
    def test_a_pay_slip_is_stamped_with_the_tenant_the_run_resolved(self) -> None:
        """Not a fresh ``get_tenant_id()``, which is the read that misfiles rows.

        ``transform_pay_run``'s docstring already forbids it; the slip
        transform re-read the singleton per slip, so a run and its own slips
        could disagree about which organisation they came from.
        """
        pay_run_id = uuid.uuid4()
        XeroPayRun.objects.create(
            xero_id=pay_run_id,
            xero_tenant_id=OURS,
            period_start_date=date(2026, 5, 4),
            period_end_date=date(2026, 5, 10),
            payment_date=date(2026, 5, 13),
            pay_run_status="Posted",
            pay_run_type="Scheduled",
            raw_json={},
            xero_last_modified=datetime(2026, 5, 13, tzinfo=UTC),
        )
        slip_id = uuid.uuid4()

        with patch("apps.xero.transforms.get_tenant_id", return_value=FOREIGN):
            _run_entity("pay_slips", [_xero_pay_slip(slip_id, pay_run_id)], tenant_id=OURS)

        assert XeroPaySlip.objects.get(xero_id=slip_id).xero_tenant_id == OURS
