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
from unittest.mock import MagicMock, call, patch
from uuid import UUID

import pytest
from django.core.cache import cache, caches
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from pytest_django.fixtures import SettingsWrapper

from apps.accounting.models import Invoice
from apps.accounting.types import DocumentTheme
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_invoice, make_job
from apps.core.models import CompanyDefaults
from apps.xero.client import XeroQuotaFloorReached, XeroSyncDisabled
from apps.xero.constants import TENANT_ID_CACHE_KEY
from apps.xero.models import XeroPayItem
from apps.xero.payroll_setup import PayrollCalendar
from apps.xero.sync_constants import LOCK_TIMEOUT, SYNC_STATUS_KEY

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


# Opus: docstring rationale unratified (ADR 0051).
@pytest.fixture
def _readonly(settings: SettingsWrapper) -> None:
    """Set the production hotfix valve, which is the state these tests are about.

    Set here and nowhere else: XERO_READONLY exists so an operator running a
    local process against PRODUCTION cannot emit real side effects, and a
    global default would make every other test silently fake (ADR 0050).
    Testing the valve itself is its one legitimate test use.
    """
    settings.XERO_READONLY = True


@pytest.mark.django_db
@pytest.mark.usefixtures("_readonly")
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

    def test_seeding_is_refused_against_a_production_tenant(self) -> None:
        # --seed-xero CREATES payroll calendars, leave types and earnings
        # rates. The demo and production setup docs differ by exactly this
        # flag, so the refusal is what stops a copy-paste writing demo payroll
        # into a client's real books.
        with (
            override_settings(PRODUCTION_XERO_TENANT_IDS=[TENANT]),
            pytest.raises(CommandError, match="production Xero tenant"),
        ):
            self._run_setup("--seed-xero")

    def test_seeding_judges_the_discovered_tenant_not_the_stored_one(self) -> None:
        # The stored tenant is the org being LEFT — checking it would pass a
        # rebind onto a production org, which is the hole this closes. Here
        # the stored value is non-production and only the discovered one is
        # production, so a stored-value check would let it through.
        defaults = CompanyDefaults.get_solo()
        defaults.xero_tenant_id = "some-demo-tenant"
        defaults.save(update_fields=["xero_tenant_id"])

        with (
            override_settings(PRODUCTION_XERO_TENANT_IDS=[TENANT]),
            pytest.raises(CommandError, match="production Xero tenant"),
        ):
            self._run_setup("--seed-xero")

    def test_plain_setup_is_allowed_against_production(self) -> None:
        # finalize_instance_onboarding runs --setup on production instances;
        # it only reads and validates, so it must not be caught by the guard.
        with override_settings(PRODUCTION_XERO_TENANT_IDS=[TENANT]):
            production = self._run_setup()

        production.validate.assert_called_once()
        production.ensure.assert_not_called()

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


def _converge_mirror() -> None:
    """Leave the database with no seed work outstanding against TENANT.

    Every count the seed measures is zero: the test company holds a contact id
    stamped with the connected tenant, the baseline pay items are stamped too
    (the fixtures create them with a Xero id and no tenant, which is exactly
    the "belongs to some other org" shape), and there are no jobs, documents or
    stock rows. The gate is measured, so a run over this database opens it.
    """
    Company.objects.filter(name=TEST_COMPANY_NAME).update(
        xero_contact_id="demo-contact", xero_tenant_id=TENANT
    )
    XeroPayItem.objects.update(xero_tenant_id=TENANT)


@pytest.mark.django_db
class TestSeedCommandPhases:
    """--only names the phases; the unported ones are refused, not skipped."""

    @pytest.fixture(autouse=True)
    def _non_production(self) -> None:
        CompanyDefaults.objects.filter(id=1).update(test_company_name=TEST_COMPANY_NAME)
        make_company(TEST_COMPANY_NAME)

    @pytest.fixture
    def _tenant(self) -> Iterator[None]:
        """Resolve the connected tenant to the demo org everywhere the seed asks."""
        with (
            patch("apps.xero.operator_guards.get_tenant_id", return_value=TENANT),
            patch("apps.xero.seeding.get_tenant_id", return_value=TENANT),
        ):
            yield

    @pytest.fixture
    def seed_staff(self) -> Staff:
        return Staff.objects.create_user(
            email="seedcmd@example.com",
            password="s3cret-Pass!",
            first_name="Seed",
            last_name="Runner",
            is_office_staff=True,
        )

    def test_the_deferred_phase_is_refused_by_name(self) -> None:
        with pytest.raises(CommandError, match="not ported"):
            call_command("seed_xero_from_database", "--only=projects")

    def test_unknown_phase_is_refused(self) -> None:
        with pytest.raises(CommandError, match="Unknown phase"):
            call_command("seed_xero_from_database", "--only=widgets")

    def test_production_target_is_refused_before_any_phase(self) -> None:
        # One guard, in run_seed, ahead of the phase ladder: v1 checked inside
        # the clear phase, so any run that skipped the clear reached the writes
        # unchecked.
        with (
            override_settings(DATABASES={"default": {"NAME": "dw_morris_prod"}}),
            pytest.raises(CommandError, match="production database"),
        ):
            call_command("seed_xero_from_database")

    @pytest.mark.usefixtures("_tenant")
    def test_dry_run_makes_no_xero_calls_and_writes_nothing(self) -> None:
        CompanyDefaults.objects.filter(id=1).update(enable_xero_sync=False)

        with (
            patch("apps.xero.seeding.AccountingApi") as seeding_api,
            patch("apps.xero.sync.AccountingApi") as sync_api,
            patch("apps.xero.payroll_sync.PayrollNzApi") as payroll_api,
        ):
            output = StringIO()
            call_command("seed_xero_from_database", "--dry-run", stdout=output)

        seeding_api.assert_not_called()
        sync_api.assert_not_called()
        payroll_api.assert_not_called()
        # The clear is derived from local rows, so a dry run can report it
        # without touching anything.
        assert "would clear the production ids" in output.getvalue()
        assert XeroPayItem.objects.filter(xero_id__isnull=False).exists()
        assert CompanyDefaults.get_solo().enable_xero_sync is False

    @pytest.mark.usefixtures("_tenant")
    def test_a_converged_run_enables_sync(self) -> None:
        _converge_mirror()
        CompanyDefaults.objects.filter(id=1).update(enable_xero_sync=False)

        with patch(
            "apps.xero.seeding.sync_all_local_stock_to_xero",
            return_value={"synced_count": 0, "failed_count": 0, "failed_items": []},
        ) as stock:
            output = StringIO()
            call_command("seed_xero_from_database", stdout=output)

        stock.assert_called_once()
        printed = output.getvalue()
        assert "Remaining work: none" in printed
        assert CompanyDefaults.get_solo().enable_xero_sync is True

    @pytest.mark.usefixtures("_tenant")
    def test_a_non_converged_run_reports_the_remaining_counts(self) -> None:
        # The test company has no contact id, so the contacts count is one and
        # the mirror is not fully linked however many phases were asked for.
        CompanyDefaults.objects.filter(id=1).update(enable_xero_sync=True)

        output = StringIO()
        call_command("seed_xero_from_database", "--only=accounts", stdout=output)

        printed = output.getvalue()
        assert "Remaining work:" in printed
        assert "contacts: 1" in printed
        assert "Not converged - enable_xero_sync stays False" in printed
        assert CompanyDefaults.get_solo().enable_xero_sync is False

    @pytest.mark.usefixtures("_tenant")
    def test_a_converged_only_run_opens_the_gate(self) -> None:
        # Deliberate change from the flag-driven design: the gate states
        # whether the mirror is fully linked, which is measured, so an --only
        # run that leaves nothing outstanding opens it.
        _converge_mirror()
        CompanyDefaults.objects.filter(id=1).update(enable_xero_sync=False)

        call_command("seed_xero_from_database", "--only=accounts")

        assert CompanyDefaults.get_solo().enable_xero_sync is True

    @pytest.mark.usefixtures("_tenant")
    def test_a_stale_mirror_is_cleared_and_the_gate_closes(self) -> None:
        # The restore shape: a production contact id with no tenant claiming
        # it. The clear is what makes the mirror unsyncable, so the clear is
        # what closes the gate.
        _converge_mirror()
        stale = make_company("Restored Ltd", xero_contact_id="prod-contact")
        CompanyDefaults.objects.filter(id=1).update(enable_xero_sync=True)

        output = StringIO()
        call_command("seed_xero_from_database", "--only=accounts", stdout=output)

        stale.refresh_from_db()
        assert "Mirror is linked to a different organisation - clearing" in output.getvalue()
        assert stale.xero_contact_id is None
        assert CompanyDefaults.get_solo().enable_xero_sync is False

    @pytest.mark.usefixtures("_tenant")
    def test_an_already_stamped_mirror_is_not_cleared(self) -> None:
        _converge_mirror()

        output = StringIO()
        call_command("seed_xero_from_database", "--only=accounts", stdout=output)

        assert "Mirror already linked to this organisation" in output.getvalue()
        assert Company.objects.get(name=TEST_COMPANY_NAME).xero_contact_id == "demo-contact"

    @pytest.mark.usefixtures("_tenant")
    def test_the_relink_phase_runs_when_a_referenced_pay_item_is_unlinked(
        self, seed_staff: Staff
    ) -> None:
        # A job references its default pay item, and the fixtures leave that
        # item stamped with no tenant — the shape a restore produces.
        _converge_mirror()
        make_job(
            make_company("Jobbing Ltd", xero_contact_id="c-1", xero_tenant_id=TENANT), seed_staff
        )
        XeroPayItem.objects.update(xero_tenant_id=None)

        with patch(
            "apps.xero.seeding.sync_xero_pay_items", return_value={"records_updated": 3}
        ) as relink:
            call_command("seed_xero_from_database", "--only=accounts")

        relink.assert_called_once()

    @pytest.mark.usefixtures("_tenant")
    def test_the_relink_phase_is_skipped_when_every_referenced_item_is_ours(self) -> None:
        _converge_mirror()

        with patch("apps.xero.seeding.sync_xero_pay_items") as relink:
            call_command("seed_xero_from_database", "--only=accounts")

        relink.assert_not_called()

    @pytest.mark.usefixtures("_tenant")
    def test_an_unreferenced_unmatched_pay_item_does_not_hold_the_gate(self) -> None:
        # Nothing posts through it, so demanding a re-link would ask for work
        # that can never complete and the gate would never open again.
        _converge_mirror()
        XeroPayItem.objects.create(name="Retired Rate", uses_leave_api=False, xero_id=None)
        CompanyDefaults.objects.filter(id=1).update(enable_xero_sync=False)

        with patch(
            "apps.xero.seeding.sync_all_local_stock_to_xero",
            return_value={"synced_count": 0, "failed_count": 0, "failed_items": []},
        ):
            call_command("seed_xero_from_database")

        assert CompanyDefaults.get_solo().enable_xero_sync is True

    @pytest.mark.usefixtures("_tenant")
    def test_only_runs_the_named_phase(self) -> None:
        # An orphan invoice a full run would delete: the phase filter is what
        # leaves it alone.
        _converge_mirror()
        orphan = make_invoice(make_company("Orphaned Ltd"))

        with patch("apps.xero.seeding.seed_accounts_from_xero") as accounts:
            call_command("seed_xero_from_database", "--only=accounts")

        accounts.assert_called_once()
        assert Invoice.objects.filter(id=orphan.id).exists()

    @pytest.mark.usefixtures("_tenant")
    def test_quota_floor_becomes_an_operator_instruction(self) -> None:
        _converge_mirror()
        with (
            patch(
                "apps.xero.seeding.sync_all_local_stock_to_xero",
                side_effect=XeroQuotaFloorReached("at floor (500)"),
            ),
            pytest.raises(CommandError, match="daily API quota is at the configured floor"),
        ):
            call_command("seed_xero_from_database", "--only=stock")


def _event(**overrides: object) -> dict[str, object]:
    """A sync event carrying every key XeroSyncEvent declares required."""
    event: dict[str, object] = {
        "datetime": "2026-08-15T00:00:00+00:00",
        "entity": "contacts",
        "severity": "info",
        "message": "done",
    }
    event.update(overrides)
    return event


@pytest.mark.django_db
class TestStartXeroSync:
    """The inline sync holds the same lock the Celery dispatcher does."""

    def test_releases_the_lock_after_a_successful_run(self) -> None:
        with patch(
            "apps.xero.management.commands.start_xero_sync.synchronise_xero_data",
            return_value=iter([_event(progress=1.0)]),
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

    def test_stops_and_keeps_its_hands_off_a_lock_a_newer_run_now_holds(self) -> None:
        # An inline run can outlive the 4h LOCK_TIMEOUT, after which a newer
        # run owns the key. The stale run must do two things: stop (continuing
        # would be the concurrent sync the lock exists to prevent) and leave
        # the newer lock alone — neither deleting it nor, as an unguarded
        # touch would, extending its lease.
        def steal_the_lock_midway() -> Iterator[dict[str, object]]:
            caches["shared"].set(SYNC_STATUS_KEY, "newer-run", timeout=60)
            yield _event(progress=1.0)
            raise AssertionError("the stale run kept syncing after losing its lock")

        with (
            patch(
                "apps.xero.management.commands.start_xero_sync.synchronise_xero_data",
                return_value=steal_the_lock_midway(),
            ),
            pytest.raises(CommandError, match="no longer holds the lock"),
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

    def test_disabled_gate_is_reported_from_the_engines_refusal(self) -> None:
        # Unpatched engine on purpose: the gate is enforced once, inside the
        # sync engine, and this command's job is to translate its
        # XeroSyncDisabled into an operator-readable CommandError.
        CompanyDefaults.objects.filter(id=1).update(enable_xero_sync=False)

        with pytest.raises(CommandError) as refusal:
            call_command("start_xero_sync")

        assert "enable_xero_sync is False" in str(refusal.value)
        assert "--entity <name> --force" in str(refusal.value)
        assert isinstance(refusal.value.__cause__, XeroSyncDisabled)
        assert caches["shared"].get(SYNC_STATUS_KEY) is None

    def test_disabled_gate_refuses_the_deep_path_too(self) -> None:
        # The deep and one-way generators cannot take --force, and used to
        # return before their first yield — an empty stream the command could
        # only diagnose by guessing the gate's value back out of the count.
        CompanyDefaults.objects.filter(id=1).update(enable_xero_sync=False)

        with pytest.raises(CommandError, match="enable_xero_sync is False"):
            call_command("start_xero_sync", "--deep-sync")

        assert caches["shared"].get(SYNC_STATUS_KEY) is None

    def test_a_run_that_emits_no_events_succeeds(self) -> None:
        # An enabled sync with nothing to do is a success, not the disabled
        # gate: the command no longer infers the gate from the event count.
        with patch(
            "apps.xero.management.commands.start_xero_sync.synchronise_xero_data",
            return_value=iter([]),
        ):
            out = StringIO()
            call_command("start_xero_sync", stdout=out)

        assert "Manual Xero synchronisation complete." in out.getvalue()
        assert caches["shared"].get(SYNC_STATUS_KEY) is None

    def test_an_unknown_severity_is_a_defect(self) -> None:
        # The severity used to pick a logger method by getattr, so a typo
        # silently logged at info; producers are held to the declared set.
        with (
            patch(
                "apps.xero.management.commands.start_xero_sync.synchronise_xero_data",
                return_value=iter([_event(severity="critical")]),
            ),
            pytest.raises(CommandError, match="unknown severity 'critical'"),
        ):
            call_command("start_xero_sync")

        assert caches["shared"].get(SYNC_STATUS_KEY) is None

    def test_progress_renews_the_lock_lease(self) -> None:
        # The lease means "four hours since the last progress event", not
        # "four hours since the run started" — an inline deep sync outlives a
        # fixed lease and would drop its lock while still writing.
        shared = caches["shared"]
        events = iter([_event(), _event(entity="invoices")])

        with (
            patch(
                "apps.xero.management.commands.start_xero_sync.synchronise_xero_data",
                return_value=events,
            ),
            patch(
                "apps.xero.management.commands.start_xero_sync._sync_cache.touch",
                wraps=shared.touch,
            ) as touch,
        ):
            call_command("start_xero_sync")

        assert touch.call_args_list == [call(SYNC_STATUS_KEY, LOCK_TIMEOUT)] * 2

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
                return_value=iter([_event(entity="invoices")]),
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
                return_value=iter([_event()]),
            ) as one_way,
            patch("apps.xero.management.commands.start_xero_sync.synchronise_xero_data") as normal,
        ):
            call_command("start_xero_sync", "--entity=contacts", "--force")

        one_way.assert_called_once_with(entities=["contacts"], force=True)
        normal.assert_not_called()


@pytest.mark.django_db
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
class TestSeedCommandContactsPrerequisites:
    """The seed refuses to run without the configured test company."""

    def test_missing_test_company_is_an_operator_error(self) -> None:
        CompanyDefaults.objects.filter(id=1).update(test_company_name="Nowhere Ltd")

        with (
            patch("apps.xero.operator_guards.get_tenant_id", return_value=TENANT),
            patch("apps.xero.seeding.get_tenant_id", return_value=TENANT),
            pytest.raises(CommandError, match="not found in the database"),
        ):
            call_command("seed_xero_from_database", "--only=contacts")
