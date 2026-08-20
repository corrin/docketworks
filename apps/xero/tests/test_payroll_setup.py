"""Payroll setup: calendar/pay-item creation for a demo org, validation for production.

Every test mocks at the SDK boundary (``PayrollNzApi``) — nothing here reaches
Xero. The behaviours guarded are the ones that break silently weeks later:
Xero ignoring the Monday anchor (payroll posting hard-requires Mon-Sun periods)
and by-name matching against a target org whose ids differ from the backup's.
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from apps.xero.models import XeroPayItem
from apps.xero.payroll_setup import (
    ensure_demo_pay_items_exist,
    get_payroll_calendars,
    validate_production_pay_items,
)

TENANT = "tenant-demo"


def _sdk_calendar(name: str, period_start: date) -> MagicMock:
    calendar = MagicMock()
    calendar.payroll_calendar_id = "cal-1"
    calendar.name = name
    calendar.calendar_type = MagicMock(value="Weekly")
    calendar.period_start_date = period_start
    calendar.period_end_date = period_start + timedelta(days=6)
    calendar.payment_date = period_start + timedelta(days=9)
    return calendar


def _api_returning(*calendar_pages: list[MagicMock]) -> MagicMock:
    """An API mock whose successive get_pay_run_calendars calls return each page."""
    api = MagicMock()
    api.get_pay_run_calendars.side_effect = [
        MagicMock(pay_run_calendars=page) for page in calendar_pages
    ]
    return api


@pytest.fixture
def _tenant() -> object:
    """Stub the auth seam: no token row, no api client; the tenant is an argument now."""
    with (
        patch("apps.xero.payroll_sdk.connected_tenant", return_value=TENANT),
        patch("apps.xero.payroll_setup.get_api_client", return_value=MagicMock()),
    ):
        yield


@pytest.mark.usefixtures("_tenant")
class TestGetPayrollCalendars:
    """The read that v2 was missing entirely (payroll writes were a Phase 4 deferral)."""

    def test_maps_sdk_calendars_to_typed_records(self) -> None:
        api = _api_returning([_sdk_calendar("Weekly Demo", date(2026, 7, 6))])

        with patch("apps.xero.payroll_setup.PayrollNzApi", return_value=api):
            calendars = get_payroll_calendars(tenant_id="tenant-1")

        assert len(calendars) == 1
        assert calendars[0].name == "Weekly Demo"
        assert calendars[0].id == "cal-1"
        assert calendars[0].period_start_date == date(2026, 7, 6)
        assert calendars[0].calendar_type == "Weekly"

    def test_empty_response_is_no_calendars(self) -> None:
        api = _api_returning([])

        with patch("apps.xero.payroll_setup.PayrollNzApi", return_value=api):
            assert get_payroll_calendars(tenant_id="tenant-1") == []

    def test_calendar_missing_a_period_start_is_rejected(self) -> None:
        broken = _sdk_calendar("Weekly Demo", date(2026, 7, 6))
        broken.period_start_date = None
        api = _api_returning([broken])

        with (
            patch("apps.xero.payroll_setup.PayrollNzApi", return_value=api),
            pytest.raises(ValueError, match="period_start_date"),
        ):
            get_payroll_calendars(tenant_id="tenant-1")


@pytest.fixture
def _no_seeded_pay_items() -> None:
    """Drop the migration-seeded pay items so each test owns the local set."""
    XeroPayItem.objects.all().delete()


@pytest.mark.django_db
@pytest.mark.usefixtures("_tenant", "_no_seeded_pay_items")
class TestEnsureDemoPayItemsExist:
    """Calendar + pay-item creation against a freshly reset demo org."""

    def test_creates_weekly_calendar_anchored_four_mondays_back(self) -> None:
        today = date(2026, 8, 13)  # a Thursday
        expected_start = date(2026, 7, 13)  # Monday, four weeks back
        api = _api_returning([], [_sdk_calendar("Weekly Demo", expected_start)])

        with (
            patch("apps.xero.payroll_setup.PayrollNzApi", return_value=api),
            patch("apps.xero.payroll_setup.localdate", return_value=today),
        ):
            result = ensure_demo_pay_items_exist("Weekly Demo", TENANT)

        assert result.calendar_created == "Weekly Demo"
        submitted = api.create_pay_run_calendar.call_args.kwargs["pay_run_calendar"]
        assert submitted.period_start_date == expected_start
        assert submitted.period_start_date.weekday() == 0
        assert submitted.payment_date == expected_start + timedelta(days=9)

    def test_rejects_a_calendar_xero_did_not_anchor_on_monday(self) -> None:
        # The failure this exists for: Xero silently re-anchors the period and
        # payroll posting (Mon-Sun only) breaks weeks later.
        tuesday = date(2026, 7, 14)
        api = _api_returning([], [_sdk_calendar("Weekly Demo", tuesday)])

        with (
            patch("apps.xero.payroll_setup.PayrollNzApi", return_value=api),
            patch("apps.xero.payroll_setup.localdate", return_value=date(2026, 8, 13)),
            pytest.raises(ValueError, match="not a Monday"),
        ):
            ensure_demo_pay_items_exist("Weekly Demo", TENANT)

    def test_rejects_a_calendar_that_is_absent_after_creation(self) -> None:
        api = _api_returning([], [])

        with (
            patch("apps.xero.payroll_setup.PayrollNzApi", return_value=api),
            patch("apps.xero.payroll_setup.localdate", return_value=date(2026, 8, 13)),
            pytest.raises(ValueError, match="calendar not found after creation"),
        ):
            ensure_demo_pay_items_exist("Weekly Demo", TENANT)

    def test_existing_calendar_is_left_alone(self) -> None:
        api = _api_returning([_sdk_calendar("Weekly Demo", date(2026, 7, 13))])

        with patch("apps.xero.payroll_setup.PayrollNzApi", return_value=api):
            result = ensure_demo_pay_items_exist("Weekly Demo", TENANT)

        assert result.calendar_created is None
        api.create_pay_run_calendar.assert_not_called()

    def test_blank_calendar_name_fails_early(self) -> None:
        api = _api_returning([])

        with (
            patch("apps.xero.payroll_setup.PayrollNzApi", return_value=api),
            pytest.raises(ValueError, match="xero_payroll_calendar_name"),
        ):
            ensure_demo_pay_items_exist("", TENANT)

    def test_pay_items_matched_by_name_are_not_recreated(self) -> None:
        # By name, not by null xero_id: on the first run the backup's stale
        # prod ids are still populated, so a null-id filter would create
        # duplicates of every item in the demo org.
        XeroPayItem.objects.create(
            name="Ordinary Time", uses_leave_api=False, xero_id="stale-prod-id"
        )
        XeroPayItem.objects.create(name="Annual Leave", uses_leave_api=True, xero_id="stale-prod-2")
        api = _api_returning([_sdk_calendar("Weekly Demo", date(2026, 7, 13))])

        with (
            patch("apps.xero.payroll_setup.PayrollNzApi", return_value=api),
            patch(
                "apps.xero.payroll_setup.get_earnings_rates",
                return_value=[{"name": "Ordinary Time", "expense_account_id": "acct-1"}],
            ),
            patch(
                "apps.xero.payroll_setup.get_leave_types", return_value=[{"name": "Annual Leave"}]
            ),
        ):
            result = ensure_demo_pay_items_exist("Weekly Demo", TENANT)

        assert result.leave_types_created == []
        assert result.earnings_rates_created == []
        api.create_leave_type.assert_not_called()
        api.create_earnings_rate.assert_not_called()

    def test_creates_missing_leave_type_and_earnings_rate(self) -> None:
        XeroPayItem.objects.create(
            name="Time and one half", uses_leave_api=False, multiplier=Decimal("1.50")
        )
        XeroPayItem.objects.create(name="Unpaid Leave", uses_leave_api=True)
        api = _api_returning([_sdk_calendar("Weekly Demo", date(2026, 7, 13))])

        with (
            patch("apps.xero.payroll_setup.PayrollNzApi", return_value=api),
            patch(
                "apps.xero.payroll_setup.get_earnings_rates",
                return_value=[{"name": "Ordinary Time", "expense_account_id": "acct-1"}],
            ),
            patch("apps.xero.payroll_setup.get_leave_types", return_value=[]),
        ):
            result = ensure_demo_pay_items_exist("Weekly Demo", TENANT)

        assert result.leave_types_created == ["Unpaid Leave"]
        assert result.earnings_rates_created == ["Time and one half"]
        leave = api.create_leave_type.call_args.kwargs["leave_type"]
        assert leave.is_paid_leave is False
        rate = api.create_earnings_rate.call_args.kwargs["earnings_rate"]
        assert rate.multiple_of_ordinary_earnings_rate == 1.5
        assert rate.expense_account_id == "acct-1"

    def test_missing_expense_account_is_an_error(self) -> None:
        XeroPayItem.objects.create(name="Time and one half", uses_leave_api=False)
        api = _api_returning([_sdk_calendar("Weekly Demo", date(2026, 7, 13))])

        with (
            patch("apps.xero.payroll_setup.PayrollNzApi", return_value=api),
            patch(
                "apps.xero.payroll_setup.get_earnings_rates",
                return_value=[{"name": "Ordinary Time", "expense_account_id": None}],
            ),
            patch("apps.xero.payroll_setup.get_leave_types", return_value=[]),
            pytest.raises(ValueError, match="expense_account_id"),
        ):
            ensure_demo_pay_items_exist("Weekly Demo", TENANT)

    def test_no_local_pay_items_skips_the_pay_item_phase(self) -> None:
        api = _api_returning([_sdk_calendar("Weekly Demo", date(2026, 7, 13))])

        with (
            patch("apps.xero.payroll_setup.PayrollNzApi", return_value=api),
            patch("apps.xero.payroll_setup.get_earnings_rates") as rates,
        ):
            result = ensure_demo_pay_items_exist("Weekly Demo", TENANT)

        assert result.earnings_rates_created == []
        rates.assert_not_called()


@pytest.mark.django_db
@pytest.mark.usefixtures("_tenant", "_no_seeded_pay_items")
class TestValidateProductionPayItems:
    """Production never creates payroll data — it asserts the operator already did."""

    def test_blank_calendar_name_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Production requires xero_payroll_calendar_name"):
            validate_production_pay_items("")

    def test_unknown_calendar_is_rejected(self) -> None:
        api = _api_returning([_sdk_calendar("Some Other Calendar", date(2026, 7, 13))])

        with (
            patch("apps.xero.payroll_setup.PayrollNzApi", return_value=api),
            pytest.raises(ValueError, match="does not exist in the production Xero tenant"),
        ):
            validate_production_pay_items("Weekly Payroll")

    def test_no_local_pay_items_is_rejected(self) -> None:
        api = _api_returning([_sdk_calendar("Weekly Payroll", date(2026, 7, 13))])

        with (
            patch("apps.xero.payroll_setup.PayrollNzApi", return_value=api),
            pytest.raises(ValueError, match="No required XeroPayItem records"),
        ):
            validate_production_pay_items("Weekly Payroll")

    def test_pay_items_absent_from_xero_are_named(self) -> None:
        XeroPayItem.objects.create(name="Ordinary Time", uses_leave_api=False)
        XeroPayItem.objects.create(name="Sick Leave", uses_leave_api=True)
        api = _api_returning([_sdk_calendar("Weekly Payroll", date(2026, 7, 13))])

        with (
            patch("apps.xero.payroll_setup.PayrollNzApi", return_value=api),
            patch(
                "apps.xero.payroll_setup.get_earnings_rates",
                return_value=[{"name": "Ordinary Time", "expense_account_id": "a"}],
            ),
            patch("apps.xero.payroll_setup.get_leave_types", return_value=[]),
            pytest.raises(ValueError, match="missing required pay items: Sick Leave"),
        ):
            validate_production_pay_items("Weekly Payroll")

    def test_complete_configuration_passes(self) -> None:
        XeroPayItem.objects.create(name="Ordinary Time", uses_leave_api=False)
        XeroPayItem.objects.create(name="Sick Leave", uses_leave_api=True)
        api = _api_returning([_sdk_calendar("Weekly Payroll", date(2026, 7, 13))])

        with (
            patch("apps.xero.payroll_setup.PayrollNzApi", return_value=api),
            patch(
                "apps.xero.payroll_setup.get_earnings_rates",
                return_value=[{"name": "Ordinary Time", "expense_account_id": "a"}],
            ),
            patch("apps.xero.payroll_setup.get_leave_types", return_value=[{"name": "Sick Leave"}]),
        ):
            validate_production_pay_items("Weekly Payroll")

        # The absence of a traceback was the only thing this asserted, which
        # makes "never create Xero data" — the other half of the contract, and
        # the half that matters on a production tenant — untested. Naming the
        # writers is deliberate: a blanket "no calls" check would pass just as
        # well if the function stopped reading too.
        api.create_pay_run_calendar.assert_not_called()
        api.create_leave_type.assert_not_called()
        api.create_earnings_rate.assert_not_called()
