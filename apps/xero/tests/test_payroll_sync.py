"""Payroll sync reads: pay runs, pay slips and the pay-item catalogue.

Business risk covered: pay items drive timesheet costing — a wrong multiplier
misprices every hour charged against the item, and a pay item left without a
xero_id while jobs reference it silently breaks payroll posting. E2E cannot
reach these paths (Xero must answer), so they are exercised here against a
mocked SDK.
"""

from collections.abc import Iterator
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from apps.accounts.models import Staff
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import Job
from apps.xero.models import XeroPayItem
from apps.xero.payroll_sync import (
    get_all_pay_slips_for_sync,
    get_earnings_rates,
    get_leave_types,
    get_pay_run,
    get_pay_runs_for_sync,
    sync_xero_pay_items,
)


@pytest.fixture(autouse=True)
def payroll_api() -> Iterator[Mock]:
    """The mocked PayrollNzApi instance every fetcher builds.

    get_api_client needs an active XeroApp row and get_tenant_id a connected
    tenant; neither exists in tests, and the SDK itself is what is being
    faked, so all three are patched at the payroll_sync seam.
    """
    with (
        patch("apps.xero.payroll_sync.get_api_client", return_value=object()),
        patch("apps.xero.payroll_sync.get_tenant_id", return_value="tenant-x"),
        patch("apps.xero.payroll_sync.PayrollNzApi") as api_cls,
    ):
        yield api_cls.return_value


def _earnings_rate(
    name: str,
    rate_type: str,
    *,
    multiple: float | None = None,
    expense_account_id: str | None = None,
) -> SimpleNamespace:
    # SimpleNamespace, never Mock(name=...): Mock treats ``name`` as its own
    # configuration keyword, not an attribute.
    return SimpleNamespace(
        earnings_rate_id=f"rate-{name.lower().replace(' ', '-')}",
        name=name,
        earnings_type="RegularEarnings",
        rate_type=rate_type,
        type_of_units="Hours",
        multiple_of_ordinary_earnings_rate=multiple,
        expense_account_id=expense_account_id,
    )


def _leave_type(name: str) -> SimpleNamespace:
    return SimpleNamespace(leave_type_id=f"leave-{name.lower().replace(' ', '-')}", name=name)


class TestGetPayRunsForSync:
    def test_returns_the_raw_pay_runs(self, payroll_api: Mock) -> None:
        runs = [SimpleNamespace(pay_run_id="run-1"), SimpleNamespace(pay_run_id="run-2")]
        payroll_api.get_pay_runs.return_value = SimpleNamespace(pay_runs=runs)

        result = get_pay_runs_for_sync()

        assert result.pay_runs == runs
        payroll_api.get_pay_runs.assert_called_once_with(xero_tenant_id="tenant-x")

    def test_empty_response_yields_empty_result(self, payroll_api: Mock) -> None:
        payroll_api.get_pay_runs.return_value = SimpleNamespace(pay_runs=[])

        assert get_pay_runs_for_sync().pay_runs == []

    def test_explicit_tenant_kwarg_overrides_the_configured_tenant(self, payroll_api: Mock) -> None:
        payroll_api.get_pay_runs.return_value = SimpleNamespace(pay_runs=[])

        get_pay_runs_for_sync(xero_tenant_id="tenant-other")

        payroll_api.get_pay_runs.assert_called_once_with(xero_tenant_id="tenant-other")


class TestGetAllPaySlipsForSync:
    def test_gathers_slips_across_every_pay_run(self, payroll_api: Mock) -> None:
        runs = [SimpleNamespace(pay_run_id="run-1"), SimpleNamespace(pay_run_id="run-2")]
        slip_a = SimpleNamespace(pay_slip_id="slip-a")
        slip_b = SimpleNamespace(pay_slip_id="slip-b")
        slip_c = SimpleNamespace(pay_slip_id="slip-c")
        payroll_api.get_pay_runs.return_value = SimpleNamespace(pay_runs=runs)
        payroll_api.get_pay_slips.side_effect = [
            SimpleNamespace(pay_slips=[slip_a, slip_b]),
            SimpleNamespace(pay_slips=[slip_c]),
        ]

        result = get_all_pay_slips_for_sync()

        assert result.pay_slips == [slip_a, slip_b, slip_c]
        assert payroll_api.get_pay_slips.call_count == 2
        payroll_api.get_pay_slips.assert_any_call(xero_tenant_id="tenant-x", pay_run_id="run-1")
        payroll_api.get_pay_slips.assert_any_call(xero_tenant_id="tenant-x", pay_run_id="run-2")

    def test_run_with_no_slips_contributes_nothing(self, payroll_api: Mock) -> None:
        runs = [SimpleNamespace(pay_run_id="run-1"), SimpleNamespace(pay_run_id="run-2")]
        slip = SimpleNamespace(pay_slip_id="slip-a")
        payroll_api.get_pay_runs.return_value = SimpleNamespace(pay_runs=runs)
        payroll_api.get_pay_slips.side_effect = [
            SimpleNamespace(pay_slips=[slip]),
            SimpleNamespace(pay_slips=None),
        ]

        assert get_all_pay_slips_for_sync().pay_slips == [slip]

    def test_no_pay_runs_yields_empty_result_without_slip_calls(self, payroll_api: Mock) -> None:
        payroll_api.get_pay_runs.return_value = SimpleNamespace(pay_runs=[])

        assert get_all_pay_slips_for_sync().pay_slips == []
        payroll_api.get_pay_slips.assert_not_called()


class TestGetPayRun:
    def test_returns_the_pay_run_when_found(self, payroll_api: Mock) -> None:
        run = SimpleNamespace(pay_run_id="run-1")
        payroll_api.get_pay_run.return_value = SimpleNamespace(pay_run=run)

        result = get_pay_run("run-1")

        # Attribute equality, not ``is run``: the declared return type is the
        # SDK's PayRun, which mypy knows a SimpleNamespace can never be.
        assert result is not None
        assert result.pay_run_id == "run-1"
        payroll_api.get_pay_run.assert_called_once_with(
            xero_tenant_id="tenant-x", pay_run_id="run-1"
        )

    def test_returns_none_when_not_found(self, payroll_api: Mock) -> None:
        payroll_api.get_pay_run.return_value = SimpleNamespace(pay_run=None)

        assert get_pay_run("run-missing") is None


class TestGetLeaveTypes:
    def test_shapes_leave_types_as_id_name_dicts(self, payroll_api: Mock) -> None:
        payroll_api.get_leave_types.return_value = SimpleNamespace(
            leave_types=[_leave_type("Annual Leave"), _leave_type("Sick Leave")]
        )

        assert get_leave_types() == [
            {"id": "leave-annual-leave", "name": "Annual Leave"},
            {"id": "leave-sick-leave", "name": "Sick Leave"},
        ]

    def test_empty_response_yields_empty_list(self, payroll_api: Mock) -> None:
        payroll_api.get_leave_types.return_value = SimpleNamespace(leave_types=None)

        assert get_leave_types() == []


class TestGetEarningsRates:
    def test_multiplier_shaping_per_rate_type(self, payroll_api: Mock) -> None:
        payroll_api.get_earnings_rates.return_value = SimpleNamespace(
            earnings_rates=[
                _earnings_rate(
                    "Time and one half",
                    "MultipleOfOrdinaryEarningsRate",
                    multiple=1.5,
                    expense_account_id="acct-1",
                ),
                _earnings_rate("Ordinary Time", "RatePerUnit"),
                _earnings_rate("Christmas Bonus", "FixedAmount"),
            ]
        )

        rates = {rate["name"]: rate for rate in get_earnings_rates()}

        assert rates["Time and one half"]["multiplier"] == 1.5
        assert rates["Time and one half"]["expense_account_id"] == "acct-1"
        assert rates["Ordinary Time"]["multiplier"] == 1.0
        assert rates["Christmas Bonus"]["multiplier"] is None
        assert rates["Christmas Bonus"]["expense_account_id"] is None


@pytest.mark.django_db
class TestSyncXeroPayItems:
    """The DB half: rows written, multipliers inferred, orphans refused.

    The root conftest has already seeded the standard catalogue ("Annual
    Leave", "Ordinary Time", ...), so names reused from it exercise the
    update path and fresh names the create path.
    """

    def _set_responses(
        self,
        payroll_api: Mock,
        leave_types: list[SimpleNamespace],
        earnings_rates: list[SimpleNamespace],
    ) -> None:
        payroll_api.get_leave_types.return_value = SimpleNamespace(leave_types=leave_types)
        payroll_api.get_earnings_rates.return_value = SimpleNamespace(earnings_rates=earnings_rates)

    def test_a_leave_type_carries_no_multiplier_whatever_it_is_called(
        self, payroll_api: Mock
    ) -> None:
        """A leave type has no multiplier; only earnings rates do.

        Opus: These three names are the ones the deleted rule keyed on — it read
        "unpaid" or "annual" out of the Xero NAME and wrote 0.00, the last
        surviving copy of the rule ADR 0007 lists under "Do not". Whether leave
        is paid comes from its Docketworks category, so the guess answered a
        question nothing asked while silently costing renamed leave wrongly.
        """
        self._set_responses(
            payroll_api,
            leave_types=[
                _leave_type("Unpaid Special Leave"),
                _leave_type("Annual Leave"),
                _leave_type("Jury Service"),
            ],
            earnings_rates=[
                _earnings_rate("Ordinary Time", "RatePerUnit"),  # seeded -> 1.0
                _earnings_rate(
                    "Triple Time", "MultipleOfOrdinaryEarningsRate", multiple=3.0
                ),  # new
                _earnings_rate("Christmas Bonus", "FixedAmount"),  # new, no multiplier
            ],
        )

        results = sync_xero_pay_items()

        assert results["leave_types"] == {"created": 2, "updated": 1}
        assert results["earnings_rates"] == {"created": 2, "updated": 1}
        assert results["records_updated"] == 6

        def multiplier(name: str, *, uses_leave_api: bool) -> Decimal | None:
            item = XeroPayItem.objects.get(name=name, uses_leave_api=uses_leave_api)
            assert item.xero_tenant_id == "tenant-x"
            assert item.xero_id is not None
            return item.multiplier

        assert multiplier("Unpaid Special Leave", uses_leave_api=True) is None
        assert multiplier("Annual Leave", uses_leave_api=True) is None
        assert multiplier("Jury Service", uses_leave_api=True) is None
        assert multiplier("Ordinary Time", uses_leave_api=False) == Decimal("1.00")
        assert multiplier("Triple Time", uses_leave_api=False) == Decimal("3.00")
        assert multiplier("Christmas Bonus", uses_leave_api=False) is None

    def test_empty_catalogue_syncs_nothing(self, payroll_api: Mock) -> None:
        self._set_responses(payroll_api, leave_types=[], earnings_rates=[])

        results = sync_xero_pay_items()

        assert results["records_updated"] == 0

    def test_referenced_pay_item_without_xero_id_fails_the_sync(
        self, payroll_api: Mock, office_staff: Staff
    ) -> None:
        self._set_responses(payroll_api, leave_types=[], earnings_rates=[])
        orphan = XeroPayItem.objects.create(
            name="Legacy Backup Item",
            uses_leave_api=False,
            multiplier=Decimal("1.00"),
            xero_id=None,
        )
        job = make_job(make_company("Payroll Co"), office_staff)
        # untracked_update: pointing at the orphan is test arrangement, not a
        # user action worth a JobEvent.
        Job.objects.filter(pk=job.pk).untracked_update(default_xero_pay_item=orphan)

        with pytest.raises(ValueError, match="Legacy Backup Item"):
            sync_xero_pay_items()

    def test_unreferenced_pay_item_without_xero_id_is_tolerated(self, payroll_api: Mock) -> None:
        self._set_responses(payroll_api, leave_types=[], earnings_rates=[])
        XeroPayItem.objects.create(
            name="Legacy Backup Item",
            uses_leave_api=False,
            multiplier=Decimal("1.00"),
            xero_id=None,
        )

        assert sync_xero_pay_items()["records_updated"] == 0
