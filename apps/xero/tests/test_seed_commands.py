"""The three operator commands, driven through call_command.

These assert the command CONTRACT — refusals, flag validation, what a dry run
is allowed to touch, what setup persists — not the seeding logic itself, which
test_seeding.py and test_payroll_setup.py cover. Nothing reaches Xero: the SDK
entry points are patched, and any test that lets a phase run asserts the API
was never constructed.
"""

from collections.abc import Iterator
from datetime import date
from io import StringIO
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from django.core.cache import cache, caches
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from pytest_django.fixtures import SettingsWrapper

from apps.accounting.types import DocumentTheme
from apps.company.tests.conftest import make_company
from apps.core.models import CompanyDefaults
from apps.xero.client import XeroQuotaFloorReached
from apps.xero.constants import TENANT_ID_CACHE_KEY
from apps.xero.payroll_setup import PayrollCalendar
from apps.xero.sync_constants import SYNC_STATUS_KEY

TENANT = "demo-tenant-id"
THEME_ID = "44444444-4444-4444-4444-444444444444"
CALENDAR_ID = "55555555-5555-5555-5555-555555555555"
CALENDAR_NAME = "Weekly Demo"
TEST_COMPANY_NAME = "ABC Carpet Cleaning TEST IGNORE"


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    """Each command test starts with no tenant cache entry and no sync lock."""
    cache.delete(TENANT_ID_CACHE_KEY)
    caches["shared"].delete(SYNC_STATUS_KEY)


@pytest.fixture
def _writes_enabled(settings: SettingsWrapper) -> None:
    """Lift settings_test's XERO_READONLY pin for the commands under test."""
    settings.XERO_READONLY = False


@pytest.mark.django_db
class TestReadonlyRefusals:
    """XERO_READONLY writes fabricated ids; these commands exist to repair the mirror."""

    @pytest.mark.parametrize(
        ("command", "args"),
        [
            ("xero", ["--setup"]),
            ("seed_xero_from_database", []),
            ("start_xero_sync", []),
        ],
    )
    def test_command_refuses_under_readonly(self, command: str, args: list[str]) -> None:
        # settings_test pins XERO_READONLY=true, which is the state under test.
        with pytest.raises(RuntimeError, match="XERO_READONLY is set"):
            call_command(command, *args)

    def test_refusal_happens_before_any_xero_call(self) -> None:
        # Patched where the command BOUND the name at import, not where it is
        # defined: patching apps.xero.auth would leave the command's own
        # reference untouched and the assertion would pass vacuously.
        with patch("apps.xero.management.commands.xero.get_valid_token") as token:
            with pytest.raises(RuntimeError, match="XERO_READONLY"):
                call_command("xero", "--setup")
            token.assert_not_called()


@pytest.mark.django_db
@pytest.mark.usefixtures("_writes_enabled")
class TestXeroCommandFlags:
    """Flag validation happens before anything reaches Xero."""

    def test_seed_xero_requires_setup(self) -> None:
        with pytest.raises(CommandError, match="--seed-xero is only valid with --setup"):
            call_command("xero", "--seed-xero")

    def test_setup_and_configure_payroll_are_exclusive(self) -> None:
        with pytest.raises(CommandError, match="not both"):
            call_command("xero", "--setup", "--configure-payroll")

    def test_no_action_is_an_error(self) -> None:
        # v1 fell through to listing tenants; that flag is not ported, so
        # doing nothing quietly would be the wrong answer.
        with pytest.raises(CommandError, match="Nothing to do"):
            call_command("xero")

    def test_missing_token_is_an_error(self) -> None:
        with (
            patch("apps.xero.management.commands.xero.get_valid_token", return_value=None),
            pytest.raises(CommandError, match="No valid Xero token"),
        ):
            call_command("xero", "--setup")


@pytest.mark.django_db
@pytest.mark.usefixtures("_writes_enabled")
class TestXeroSetup:
    """--setup rebinds the installation to the connected organisation."""

    def _run_setup(self, *extra_args: str) -> MagicMock:
        """Run --setup with every Xero seam stubbed; returns the accounting API mock."""
        defaults = CompanyDefaults.get_solo()
        defaults.xero_tenant_id = "stale-prod-tenant"
        defaults.xero_payroll_calendar_name = CALENDAR_NAME
        # Production setup refuses to pick a theme for the operator, so the
        # baseline carries the one the connected org still has.
        defaults.xero_sales_branding_theme_id = UUID(THEME_ID)
        defaults.save(
            update_fields=[
                "xero_tenant_id",
                "xero_payroll_calendar_name",
                "xero_sales_branding_theme_id",
            ]
        )

        accounting_api = MagicMock()
        accounting_api.get_organisations.return_value = MagicMock(
            organisations=[MagicMock(short_code="!ABC12")]
        )
        identity_api = MagicMock()
        identity_api.get_connections.return_value = [
            MagicMock(tenant_id=TENANT, tenant_name="Demo Company (NZ)")
        ]
        provider = MagicMock()
        provider.list_document_themes.return_value = [
            DocumentTheme(external_id=THEME_ID, name="Standard", is_default=True)
        ]

        with (
            patch("apps.xero.management.commands.xero.get_valid_token", return_value={"a": 1}),
            patch("apps.xero.management.commands.xero.get_api_client", return_value=MagicMock()),
            patch("apps.xero.management.commands.xero.IdentityApi", return_value=identity_api),
            patch("apps.xero.management.commands.xero.AccountingApi", return_value=accounting_api),
            patch("apps.xero.management.commands.xero.get_provider", return_value=provider),
            patch(
                "apps.xero.management.commands.xero.get_payroll_calendars",
                return_value=[
                    PayrollCalendar(
                        id=CALENDAR_ID,
                        name=CALENDAR_NAME,
                        calendar_type="Weekly",
                        period_start_date=date(2026, 7, 13),
                        period_end_date=date(2026, 7, 19),
                        payment_date=date(2026, 7, 22),
                    )
                ],
            ),
            patch("apps.xero.management.commands.xero.validate_production_pay_items") as validate,
            patch(
                "apps.xero.management.commands.xero.ensure_demo_pay_items_exist",
                return_value=MagicMock(
                    calendar_created=None, leave_types_created=[], earnings_rates_created=[]
                ),
            ) as ensure,
        ):
            call_command("xero", "--setup", *extra_args)
        accounting_api.validate = validate
        accounting_api.ensure = ensure
        return accounting_api

    def test_persists_tenant_shortcode_theme_and_calendar(self) -> None:
        self._run_setup()

        defaults = CompanyDefaults.get_solo()
        assert defaults.xero_tenant_id == TENANT
        assert defaults.xero_shortcode == "!ABC12"
        assert defaults.xero_sales_branding_theme_id == UUID(THEME_ID)
        assert defaults.xero_payroll_calendar_id == UUID(CALENDAR_ID)

    def test_caches_the_rebound_tenant_id(self) -> None:
        # Without this the rest of the process resolves the PREVIOUS tenant
        # from cache and configures the wrong organisation.
        self._run_setup()

        assert cache.get(TENANT_ID_CACHE_KEY) == TENANT

    def test_production_validates_payroll_and_seed_creates_it(self) -> None:
        production = self._run_setup()
        production.validate.assert_called_once()
        production.ensure.assert_not_called()

        seeded = self._run_setup("--seed-xero")
        seeded.ensure.assert_called_once()
        seeded.validate.assert_not_called()

    def test_production_requires_a_configured_theme(self) -> None:
        defaults = CompanyDefaults.get_solo()
        defaults.xero_payroll_calendar_name = CALENDAR_NAME
        defaults.xero_sales_branding_theme_id = None
        defaults.save(update_fields=["xero_payroll_calendar_name", "xero_sales_branding_theme_id"])
        identity_api = MagicMock()
        identity_api.get_connections.return_value = [
            MagicMock(tenant_id=TENANT, tenant_name="Prod Co")
        ]
        accounting_api = MagicMock()
        accounting_api.get_organisations.return_value = MagicMock(
            organisations=[MagicMock(short_code="!ABC12")]
        )

        with (
            patch("apps.xero.management.commands.xero.get_valid_token", return_value={"a": 1}),
            patch("apps.xero.management.commands.xero.get_api_client", return_value=MagicMock()),
            patch("apps.xero.management.commands.xero.IdentityApi", return_value=identity_api),
            patch("apps.xero.management.commands.xero.AccountingApi", return_value=accounting_api),
            patch("apps.xero.management.commands.xero.validate_production_pay_items"),
            patch("apps.xero.management.commands.xero.get_provider", return_value=MagicMock()),
            pytest.raises(CommandError, match="explicitly selected Xero sales branding theme"),
        ):
            call_command("xero", "--setup")


@pytest.mark.django_db
@pytest.mark.usefixtures("_writes_enabled")
class TestSeedCommandPhases:
    """--only names the phases; the unported ones are refused, not skipped."""

    @pytest.fixture(autouse=True)
    def _non_production(self) -> None:
        CompanyDefaults.objects.filter(id=1).update(test_company_name=TEST_COMPANY_NAME)
        make_company(TEST_COMPANY_NAME)

    @pytest.mark.parametrize("entity", ["employees", "projects"])
    def test_deferred_phases_are_refused_by_name(self, entity: str) -> None:
        with pytest.raises(CommandError, match="not ported"):
            call_command("seed_xero_from_database", f"--only={entity}")

    def test_unknown_phase_is_refused(self) -> None:
        with pytest.raises(CommandError, match="Unknown phase"):
            call_command("seed_xero_from_database", "--only=widgets")

    def test_production_target_is_refused_even_with_skip_clear(self) -> None:
        # v1 only checked inside the clear phase, so --skip-clear bypassed the
        # production refusal entirely.
        with (
            override_settings(DATABASES={"default": {"NAME": "dw_morris_prod"}}),
            pytest.raises(CommandError, match="production database"),
        ):
            call_command("seed_xero_from_database", "--skip-clear")

    def test_dry_run_makes_no_xero_calls_and_writes_nothing(self) -> None:
        CompanyDefaults.objects.filter(id=1).update(enable_xero_sync=False)

        with (
            patch("apps.xero.operator_guards.get_tenant_id", return_value=TENANT),
            patch("apps.xero.seeding.AccountingApi") as seeding_api,
            patch("apps.xero.sync.AccountingApi") as sync_api,
            patch("apps.xero.payroll_sync.PayrollNzApi") as payroll_api,
        ):
            call_command("seed_xero_from_database", "--dry-run")

        seeding_api.assert_not_called()
        sync_api.assert_not_called()
        payroll_api.assert_not_called()
        # The finale is skipped on a dry run: sync must not be enabled until
        # the mirror actually points at the target organisation.
        assert CompanyDefaults.get_solo().enable_xero_sync is False

    def test_full_run_enables_sync_and_warns_about_employees(self) -> None:
        with (
            patch("apps.xero.operator_guards.get_tenant_id", return_value=TENANT),
            patch(
                "apps.xero.management.commands.seed_xero_from_database.clear_production_xero_ids"
            ),
            patch(
                "apps.xero.management.commands.seed_xero_from_database.sync_xero_pay_items",
                return_value={"records_updated": 7},
            ),
            patch(
                "apps.xero.management.commands.seed_xero_from_database.seed_accounts_from_xero"
            ) as accounts,
            patch(
                "apps.xero.management.commands.seed_xero_from_database.seed_companies_to_xero"
            ) as contacts,
            patch(
                "apps.xero.management.commands.seed_xero_from_database.seed_invoices"
            ) as invoices,
            patch("apps.xero.management.commands.seed_xero_from_database.seed_quotes") as quotes,
            patch(
                "apps.xero.management.commands.seed_xero_from_database.sync_all_local_stock_to_xero",
                return_value={"synced_count": 0, "failed_count": 0, "failed_items": []},
            ) as stock,
        ):
            output = StringIO()
            call_command("seed_xero_from_database", stdout=output)

        accounts.assert_called_once()
        contacts.assert_called_once()
        invoices.assert_called_once()
        quotes.assert_called_once()
        stock.assert_called_once()
        assert CompanyDefaults.get_solo().enable_xero_sync is True
        # The operator must leave the run knowing timesheet posting is still
        # broken against this organisation.
        printed = output.getvalue()
        assert "Payroll employees were NOT seeded" in printed
        assert "timesheet posting" in printed

    def test_partial_run_leaves_the_sync_gate_closed(self) -> None:
        # The seed is a batch process: syncing exists only after the FULL
        # batch succeeds. A partial run that re-enabled the gate let beat
        # syncs and webhook echoes run mid-batch (2026-08-14 duplicates).
        CompanyDefaults.objects.filter(id=1).update(enable_xero_sync=False)
        with (
            patch("apps.xero.operator_guards.get_tenant_id", return_value=TENANT),
            patch(
                "apps.xero.management.commands.seed_xero_from_database.seed_companies_to_xero"
            ) as contacts,
        ):
            output = StringIO()
            call_command(
                "seed_xero_from_database", "--only=contacts", "--skip-clear", stdout=output
            )
        contacts.assert_called_once()
        assert CompanyDefaults.get_solo().enable_xero_sync is False
        assert "enable_xero_sync left unchanged" in output.getvalue()

    def test_only_runs_the_named_phase(self) -> None:
        with (
            patch("apps.xero.operator_guards.get_tenant_id", return_value=TENANT),
            patch(
                "apps.xero.management.commands.seed_xero_from_database.clear_production_xero_ids"
            ),
            patch(
                "apps.xero.management.commands.seed_xero_from_database.sync_xero_pay_items",
                return_value={"records_updated": 0},
            ),
            patch(
                "apps.xero.management.commands.seed_xero_from_database.seed_accounts_from_xero"
            ) as accounts,
            patch(
                "apps.xero.management.commands.seed_xero_from_database.seed_invoices"
            ) as invoices,
        ):
            call_command("seed_xero_from_database", "--only=accounts")

        accounts.assert_called_once()
        invoices.assert_not_called()

    def test_quota_floor_becomes_an_operator_instruction(self) -> None:
        with (
            patch("apps.xero.operator_guards.get_tenant_id", return_value=TENANT),
            patch(
                "apps.xero.management.commands.seed_xero_from_database.sync_all_local_stock_to_xero",
                side_effect=XeroQuotaFloorReached("at floor (500)"),
            ),
            patch(
                "apps.xero.management.commands.seed_xero_from_database.clear_production_xero_ids"
            ),
            patch(
                "apps.xero.management.commands.seed_xero_from_database.sync_xero_pay_items",
                return_value={"records_updated": 0},
            ),
            pytest.raises(CommandError, match="daily API quota is at the configured floor"),
        ):
            call_command("seed_xero_from_database", "--only=stock")


@pytest.mark.django_db
@pytest.mark.usefixtures("_writes_enabled")
class TestStartXeroSync:
    """The inline sync holds the same lock the Celery dispatcher does."""

    def test_releases_the_lock_after_a_successful_run(self) -> None:
        with patch(
            "apps.xero.management.commands.start_xero_sync.synchronise_xero_data",
            return_value=iter([{"entity": "contacts", "message": "done", "progress": 1.0}]),
        ) as generator:
            call_command("start_xero_sync")

        generator.assert_called_once()
        assert caches["shared"].get(SYNC_STATUS_KEY) is None

    def test_refuses_to_start_while_a_sync_holds_the_lock(self) -> None:
        # v1 held no lock, so a manual run could interleave with the
        # beat-dispatched Celery sync.
        caches["shared"].set(SYNC_STATUS_KEY, "celery-task-1", timeout=60)

        with (
            patch(
                "apps.xero.management.commands.start_xero_sync.synchronise_xero_data"
            ) as generator,
            pytest.raises(CommandError, match="already running"),
        ):
            call_command("start_xero_sync")

        generator.assert_not_called()
        # The other run's lock survives the refusal.
        assert caches["shared"].get(SYNC_STATUS_KEY) == "celery-task-1"

    def test_does_not_release_a_lock_a_newer_run_now_holds(self) -> None:
        # An inline run can outlive the 4h LOCK_TIMEOUT. If it then deleted
        # the key unconditionally it would free the NEXT run's lock and permit
        # the concurrent sync the lock exists to prevent.
        def steal_the_lock_midway() -> Iterator[dict[str, object]]:
            caches["shared"].set(SYNC_STATUS_KEY, "newer-run", timeout=60)
            yield {"entity": "contacts", "message": "done", "progress": 1.0}

        with patch(
            "apps.xero.management.commands.start_xero_sync.synchronise_xero_data",
            return_value=steal_the_lock_midway(),
        ):
            call_command("start_xero_sync")

        assert caches["shared"].get(SYNC_STATUS_KEY) == "newer-run"

    def test_force_without_an_entity_is_refused(self) -> None:
        # --force only reaches the engine on the single-entity path; v1
        # accepted it everywhere and reported success having synced nothing.
        with (
            patch("apps.xero.management.commands.start_xero_sync.deep_sync_xero_data") as deep,
            pytest.raises(CommandError, match="only honoured with --entity"),
        ):
            call_command("start_xero_sync", "--deep-sync", "--force")

        deep.assert_not_called()

    def test_full_sync_is_refused_when_sync_is_disabled(self) -> None:
        CompanyDefaults.objects.filter(id=1).update(enable_xero_sync=False)

        with (
            patch("apps.xero.management.commands.start_xero_sync.synchronise_xero_data") as normal,
            pytest.raises(CommandError, match="enable_xero_sync is False"),
        ):
            call_command("start_xero_sync")

        normal.assert_not_called()
        assert caches["shared"].get(SYNC_STATUS_KEY) is None

    def test_a_run_that_emits_nothing_fails(self) -> None:
        # The engine expresses "disabled" by returning before yielding, which
        # v1 drained and reported as a successful sync.
        with (
            patch(
                "apps.xero.management.commands.start_xero_sync.deep_sync_xero_data",
                return_value=iter([]),
            ),
            pytest.raises(CommandError, match="enable_xero_sync"),
        ):
            call_command("start_xero_sync", "--deep-sync")

        assert caches["shared"].get(SYNC_STATUS_KEY) is None

    def test_releases_the_lock_when_the_sync_fails(self) -> None:
        with (
            patch(
                "apps.xero.management.commands.start_xero_sync.synchronise_xero_data",
                side_effect=RuntimeError("Xero exploded"),
            ),
            pytest.raises(CommandError, match="Xero sync failed"),
        ):
            call_command("start_xero_sync")

        assert caches["shared"].get(SYNC_STATUS_KEY) is None

    def test_deep_sync_selects_the_deep_generator(self) -> None:
        with (
            patch(
                "apps.xero.management.commands.start_xero_sync.deep_sync_xero_data",
                return_value=iter([{"entity": "invoices", "message": "done"}]),
            ) as deep,
            patch("apps.xero.management.commands.start_xero_sync.synchronise_xero_data") as normal,
        ):
            call_command("start_xero_sync", "--deep-sync", "--days-back=30")

        deep.assert_called_once_with(days_back=30, entities=None)
        normal.assert_not_called()

    def test_single_entity_selects_the_one_way_generator(self) -> None:
        with (
            patch(
                "apps.xero.management.commands.start_xero_sync.one_way_sync_all_xero_data",
                return_value=iter([{"entity": "contacts", "message": "done"}]),
            ) as one_way,
            patch("apps.xero.management.commands.start_xero_sync.synchronise_xero_data") as normal,
        ):
            call_command("start_xero_sync", "--entity=contacts", "--force")

        one_way.assert_called_once_with(entities=["contacts"], force=True)
        normal.assert_not_called()


@pytest.mark.django_db
@pytest.mark.usefixtures("_writes_enabled")
class TestConfigurePayroll:
    """--configure-payroll only mirrors Xero's pay items into local rows."""

    def test_reports_the_sync_counts(self) -> None:
        with (
            patch("apps.xero.management.commands.xero.get_valid_token", return_value={"a": 1}),
            patch(
                "apps.xero.management.commands.xero.sync_xero_pay_items",
                return_value={
                    "leave_types": {"created": 1, "updated": 2},
                    "earnings_rates": {"created": 3, "updated": 4},
                    "records_updated": 10,
                },
            ) as sync,
        ):
            call_command("xero", "--configure-payroll")

        sync.assert_called_once()


@pytest.mark.django_db
@pytest.mark.usefixtures("_writes_enabled")
class TestSeedCommandContactsPrerequisites:
    """The seed refuses to run without the configured test company."""

    def test_missing_test_company_is_an_operator_error(self) -> None:
        CompanyDefaults.objects.filter(id=1).update(test_company_name="Nowhere Ltd")

        with (
            patch("apps.xero.operator_guards.get_tenant_id", return_value=TENANT),
            patch(
                "apps.xero.management.commands.seed_xero_from_database.clear_production_xero_ids"
            ),
            patch(
                "apps.xero.management.commands.seed_xero_from_database.sync_xero_pay_items",
                return_value={"records_updated": 0},
            ),
            pytest.raises(CommandError, match="not found in the database"),
        ):
            call_command("seed_xero_from_database", "--only=contacts")
