"""Configure this installation's Xero connection.

Ported from v1's ``xero`` command, which carried fifteen flags. Only the three
that configure an installation are here: ``--setup``, its ``--seed-xero``
modifier, and ``--configure-payroll``. The rest were read-only inspection
flags (tenant/user/pay-run listings) or staff linking, which depends on the
payroll employee API that is a recorded Phase 4 deferral.

``--setup`` is the command run after a Xero demo-tenant reset or a database
restore: it rebinds CompanyDefaults to the connected organisation and
re-resolves everything keyed to it (shortcode, branding theme, payroll
calendar).
"""

import logging
from uuid import UUID

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError, CommandParser
from xero_python.accounting import AccountingApi
from xero_python.identity import IdentityApi

from apps.accounting.registry import get_provider
from apps.accounting.services.document_theme import (
    find_document_theme_by_id,
    resolve_sales_branding_theme,
)
from apps.core.errors import AppErrorContext, persist_app_error
from apps.core.models import CompanyDefaults
from apps.xero.auth import get_api_client, get_valid_token
from apps.xero.constants import TENANT_ID_CACHE_KEY
from apps.xero.operator_guards import assert_not_production_target, assert_xero_writes_enabled
from apps.xero.payroll_setup import (
    ensure_demo_pay_items_exist,
    get_payroll_calendars,
    validate_production_pay_items,
)
from apps.xero.payroll_sync import sync_xero_pay_items

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Bind the installation to the connected Xero organisation."""

    help = "Configure the Xero tenant, shortcode, sales branding theme and payroll calendar."

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the three supported actions."""
        parser.add_argument(
            "--setup",
            action="store_true",
            help="Configure tenant id, shortcode, sales branding theme and payroll calendar",
        )
        parser.add_argument(
            "--seed-xero",
            action="store_true",
            help="With --setup: CREATE missing demo-only payroll configuration in Xero",
        )
        parser.add_argument(
            "--configure-payroll",
            action="store_true",
            help="Sync XeroPayItem rows from Xero leave types and earnings rates",
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Run the requested action, persisting any failure with its context."""
        try:
            self._handle(**options)
        except Exception as exc:
            persist_app_error(
                exc,
                AppErrorContext(
                    additional_context={
                        "command": "xero",
                        "setup": bool(options["setup"]),
                        "seed_xero": bool(options["seed_xero"]),
                        "configure_payroll": bool(options["configure_payroll"]),
                    }
                ),
            )
            raise

    def _handle(self, **options: object) -> None:
        setup = bool(options["setup"])
        seed_xero = bool(options["seed_xero"])
        configure_payroll = bool(options["configure_payroll"])

        # First act: this command writes to whichever organisation is
        # connected, so a readonly process must not reach the API at all.
        assert_xero_writes_enabled("manage.py xero")

        if seed_xero and not setup:
            raise CommandError("--seed-xero is only valid with --setup.")
        if setup and configure_payroll:
            raise CommandError("Pass either --setup or --configure-payroll, not both.")
        if not setup and not configure_payroll:
            raise CommandError("Nothing to do: pass --setup or --configure-payroll.")

        if not get_valid_token():
            raise CommandError(
                "No valid Xero token found. Connect to Xero via Admin > Xero Settings "
                "in the web app first."
            )

        if setup:
            self._run_setup(seed_xero=seed_xero)
            return
        self._configure_payroll()

    def _run_setup(self, *, seed_xero: bool) -> None:
        """Rebind CompanyDefaults to the connected organisation."""
        self.stdout.write("Setting up Xero connection...")

        connections = IdentityApi(get_api_client()).get_connections()
        if not connections:
            raise CommandError(
                "No Xero organisations connected. Connect an organisation in Xero first."
            )

        # The FIRST connected organisation, deliberately: this command exists
        # to rebind after Xero's recurring demo-tenant resets, where the new
        # organisation replaces the old one under the same app.
        connection = connections[0]
        tenant_id = connection.tenant_id
        if not tenant_id:
            raise CommandError("Xero returned a connection without a tenant id.")
        # Checked against the tenant just DISCOVERED, not the stored one: this
        # command exists to rebind, so the configured value is the org being
        # left behind. --seed-xero creates payroll calendars, leave types and
        # earnings rates, which must never appear in a client's real books;
        # the demo and production setup docs differ by exactly this flag, so
        # it is one copy-paste away (ADR 0048's --wipe-production reasoning).
        # Plain --setup stays allowed on production: finalize_instance_onboarding
        # needs it, and it only reads and validates.
        if seed_xero:
            try:
                assert_not_production_target(tenant_id)
            except ValueError as exc:
                raise CommandError(str(exc)) from exc

        self.stdout.write(f"Using organisation: {connection.tenant_name}")
        if len(connections) > 1:
            self.stdout.write(
                self.style.WARNING(
                    f"Note: {len(connections)} organisations connected. Using the first."
                )
            )

        company = CompanyDefaults.get_solo()
        # Resolve first, bind late: persisting the tenant id before the
        # resolvers succeed left the installation bound to the new tenant
        # while shortcode/theme/calendar still described the previous
        # organisation — reachable in production, where _resolve_theme raises
        # on the unset-after-restore theme. Only the cache is pointed at the
        # new tenant (the resolvers below resolve through it), and it is
        # dropped on any failure so the next call re-resolves from the DB.
        cache.set(TENANT_ID_CACHE_KEY, tenant_id)
        try:
            calendar_name = company.xero_payroll_calendar_name
            self._configure_payroll_items(
                calendar_name=calendar_name, tenant_id=tenant_id, seed_xero=seed_xero
            )
            shortcode = self._fetch_shortcode(tenant_id)
            theme_id, theme_name = self._resolve_theme(company, seed_xero=seed_xero)
            calendar_id = self._resolve_calendar_id(calendar_name)
        except BaseException:
            cache.delete(TENANT_ID_CACHE_KEY)
            raise

        company.xero_tenant_id = tenant_id
        company.xero_shortcode = shortcode
        company.xero_sales_branding_theme_id = theme_id
        company.xero_payroll_calendar_id = calendar_id
        company.save(
            update_fields=[
                "xero_tenant_id",
                "xero_shortcode",
                "xero_sales_branding_theme_id",
                "xero_payroll_calendar_id",
            ]
        )

        self.stdout.write(self.style.SUCCESS(f"Tenant ID: {tenant_id}"))
        self.stdout.write(self.style.SUCCESS(f"Shortcode: {shortcode}"))
        self.stdout.write(self.style.SUCCESS(f"Sales Branding Theme: {theme_name} ({theme_id})"))
        self.stdout.write(self.style.SUCCESS(f"Payroll Calendar: {calendar_name} ({calendar_id})"))
        self.stdout.write(self.style.SUCCESS("Xero setup complete."))
        self.stdout.write("")
        self.stdout.write("Next step: python manage.py start_xero_sync")

    def _configure_payroll_items(
        self, *, calendar_name: str | None, tenant_id: str, seed_xero: bool
    ) -> None:
        """Create the demo org's payroll configuration, or validate production's."""
        try:
            if not seed_xero:
                validate_production_pay_items(calendar_name or "")
                return
            result = ensure_demo_pay_items_exist(calendar_name or "", tenant_id)
        # Reshaped, not swallowed: the service raises ValueError with an
        # operator-ready message, and CommandError is how Django prints one
        # without a traceback.
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        if result.calendar_created:
            self.stdout.write(
                self.style.SUCCESS(f"Created payroll calendar: {result.calendar_created}")
            )
        for name in result.leave_types_created:
            self.stdout.write(self.style.SUCCESS(f"Created leave type: {name}"))
        for name in result.earnings_rates_created:
            self.stdout.write(self.style.SUCCESS(f"Created earnings rate: {name}"))

    def _fetch_shortcode(self, tenant_id: str) -> str:
        """Read the organisation shortcode used to build deep links into Xero."""
        response = AccountingApi(get_api_client()).get_organisations(xero_tenant_id=tenant_id)
        organisations = response.organisations or []
        if not organisations:
            raise CommandError("Failed to fetch organisation details from Xero.")
        shortcode = organisations[0].short_code
        if not shortcode:
            raise CommandError(
                "The connected Xero organisation has no short code; deep links into Xero "
                "cannot be built without one."
            )
        return shortcode

    def _resolve_theme(self, company: CompanyDefaults, *, seed_xero: bool) -> tuple[UUID, str]:
        """Pick the sales branding theme to invoice under."""
        if seed_xero:
            theme = resolve_sales_branding_theme(
                get_provider(), company.xero_sales_branding_theme_id
            )
        else:
            # Production never picks a theme for the operator: invoices would
            # silently change appearance for real customers.
            configured_id = company.xero_sales_branding_theme_id
            if configured_id is None:
                raise CommandError(
                    "Production requires an explicitly selected Xero sales branding theme."
                )
            theme = find_document_theme_by_id(get_provider(), configured_id)
            if theme is None:
                raise CommandError(
                    f"The configured sales branding theme ({configured_id}) does not "
                    "exist in the connected Xero organisation. Re-select a live theme "
                    "in CompanyDefaults before running setup."
                )
        if theme is None:
            raise CommandError(
                "Xero returned no usable branding theme. Create (or re-select) a branding "
                "theme in Xero before running setup."
            )
        return UUID(theme.external_id), theme.name

    def _resolve_calendar_id(self, calendar_name: str | None) -> UUID:
        """Resolve the configured payroll calendar name to its id in this org."""
        if not calendar_name:
            raise CommandError("xero_payroll_calendar_name is required.")
        calendars = get_payroll_calendars()
        matching = next((c for c in calendars if c.name == calendar_name), None)
        if matching is None:
            raise CommandError(
                f"Payroll calendar '{calendar_name}' not found in Xero. Available calendars: "
                f"{[c.name for c in calendars]}"
            )
        return UUID(matching.id)

    def _configure_payroll(self) -> None:
        """Mirror Xero's leave types and earnings rates into XeroPayItem."""
        self.stdout.write("Syncing Xero pay items...")
        result = sync_xero_pay_items()
        leave = result["leave_types"]
        earnings = result["earnings_rates"]
        self.stdout.write(f"Leave types: {leave['created']} created, {leave['updated']} updated")
        self.stdout.write(
            f"Earnings rates: {earnings['created']} created, {earnings['updated']} updated"
        )
        self.stdout.write(self.style.SUCCESS("XeroPayItem sync complete."))
