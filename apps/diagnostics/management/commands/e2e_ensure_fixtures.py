"""Put the rows the E2E suite assumes into a database that never held them.

No production dump carries the E2E users, and a fresh instance carries no test
company: ``global-setup.ts`` fails at sign-in without the first, and every
UI-seeded spec searches for the second. Idempotent, so a restore runbook and
``verify-instance.sh --e2e`` (ADR 0064) both run it unconditionally.

The users' credentials come from the environment — the same
``E2E_TEST_USERNAME`` / ``E2E_TEST_PASSWORD``, ``E2E_WORKSHOP_USERNAME`` /
``E2E_WORKSHOP_PASSWORD`` and ``E2E_OFFICE_STAFF_USERNAME`` /
``E2E_OFFICE_STAFF_PASSWORD`` Playwright reads — so a password is never on a
command line. Three properties of the office user gate whole
clusters of specs: office staff (the navbar's Create Job), superuser (the
timesheet management surface), and a costing wage of exactly 45.00, which
``job-cost-entry-data.spec.ts`` pins. The wage is computed on save from the
base rate and this database's labour-cost loading, so the base is derived
from the loading rather than hard-coded (37.50 is only right at 20%).

The workshop user is who the phone specs sign in as: shop-floor staff, so
neither office nor superuser. Those two flags are the point of the row — a
workshop login that reaches an office-only endpoint is the defect the phone
specs exist to catch — and are re-aligned on every run for that reason.

The office staff user is office staff and nothing more: not a superuser. The
approve-time spec signs in as it, because a screen any office staff member
may use is only proven by a login that is not also allowed everything.

All three are created employed from ``E2E_EMPLOYMENT_START``. A timesheet only
lists staff employed on its date who are linked to a payroll employee, and specs
book time on past weekdays for the workshop login, so that login must be a proper
payroll employee. On a dev restore the seed's employees phase makes it one, from
this start date. Where no seed runs (``verify-instance.sh --e2e``, against the
fake), ``--payroll`` does the same through the seed's own ``sync_staff``, once the
organisation is reachable. A plain run never calls Xero: on a restore it runs
before Xero is reconnected, while the data still names production's tenant.
Once linked, Xero owns the start date and the wage (each sync copies them back),
so they are set only when a row is created, never re-aligned.
"""

import os
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.core.environment import ProductionDatabaseError, assert_not_production_database
from apps.core.models import CompanyDefaults, loaded_wage_rate
from apps.core.test_data import TEST_COMPANY_NAME
from apps.timesheet.services import payroll_employee_sync
from apps.xero.auth import get_tenant_id

#: The costing wage job-cost-entry-data.spec.ts pins as its environment prerequisite.
E2E_USER_WAGE_RATE = Decimal("45.00")
#: No spec pins the workshop user's wage; it only has to be a real hourly rate.
E2E_WORKSHOP_BASE_WAGE_RATE = Decimal("30.00")
#: Before any date a spec books time on.
E2E_EMPLOYMENT_START = date(2020, 1, 1)


def _credentials(username_key: str, password_key: str) -> tuple[str, str]:
    try:
        return os.environ[username_key], os.environ[password_key]
    except KeyError as exc:
        raise CommandError(
            f"{exc.args[0]} is not set; the E2E users' credentials come from the environment "
            "(frontend/.env.test on a workstation, the instance's e2e.env on a server)."
        ) from exc


def _base_wage_for(loading_percent: Decimal) -> Decimal:
    """Return the base rate whose loaded wage is exactly E2E_USER_WAGE_RATE at this loading."""
    multiplier = Decimal("1") + loading_percent / Decimal("100")
    base = (E2E_USER_WAGE_RATE / multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if loaded_wage_rate(base, loading_percent) != E2E_USER_WAGE_RATE:
        raise CommandError(
            f"No two-decimal base wage loads to exactly {E2E_USER_WAGE_RATE} at a "
            f"labour-cost loading of {loading_percent}%; the spec's prerequisite cannot "
            "be met on this database."
        )
    return base


class Command(BaseCommand):
    """Create or align the E2E users and the test company."""

    help = "Create or align the E2E users and the test company the suite assumes (idempotent)."

    def add_arguments(self, parser: CommandParser) -> None:
        """``--payroll``: also make the workshop login a payroll employee."""
        parser.add_argument(
            "--payroll",
            action="store_true",
            help=(
                "Also make the workshop login a payroll employee in the connected "
                "organisation; only once Xero (or the fake) is reachable."
            ),
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Ensure both fixtures, reporting what each ended as."""
        try:
            assert_not_production_database(
                "it installs a superuser whose password is held in a file."
            )
        except ProductionDatabaseError as exc:
            raise CommandError(str(exc)) from exc
        username, password = _credentials("E2E_TEST_USERNAME", "E2E_TEST_PASSWORD")
        workshop_username, workshop_password = _credentials(
            "E2E_WORKSHOP_USERNAME", "E2E_WORKSHOP_PASSWORD"
        )
        office_username, office_password = _credentials(
            "E2E_OFFICE_STAFF_USERNAME", "E2E_OFFICE_STAFF_PASSWORD"
        )
        # Users are found case-insensitively, so two of these naming one
        # address would be one Staff row, and a later pass would take off it
        # the access an earlier pass gave.
        named = {
            "E2E_TEST_USERNAME": username,
            "E2E_WORKSHOP_USERNAME": workshop_username,
            "E2E_OFFICE_STAFF_USERNAME": office_username,
        }
        addresses = [address.casefold() for address in named.values()]
        if len(set(addresses)) != len(addresses):
            raise CommandError(
                f"{', '.join(named)} must name three accounts, and two name the same address "
                f"({', '.join(named.values())})."
            )
        with transaction.atomic():
            user = self._ensure_user(username, password)
            workshop_user = self._ensure_workshop_user(workshop_username, workshop_password)
            office_user = self._ensure_office_staff_user(office_username, office_password)
            company = self._ensure_test_company()
        # Outside the transaction: it calls Xero, and a refused call must not
        # roll back the logins it has nothing to do with.
        if options["payroll"]:
            self._ensure_on_payroll(workshop_user)
        self.stdout.write(
            f"E2E user {user.office_email}: office staff, superuser, wage {user.wage_rate}"
        )
        self.stdout.write(
            f"E2E workshop user {workshop_user.office_email}: workshop staff, "
            f"wage {workshop_user.wage_rate}"
        )
        self.stdout.write(
            f"E2E office staff user {office_user.office_email}: office staff, not superuser"
        )
        self.stdout.write(f"Test company: {company.name} (ID: {company.id})")

    def _ensure_user(self, username: str, password: str) -> Staff:
        defaults = CompanyDefaults.get_solo()
        base_wage = _base_wage_for(defaults.labour_cost_loading)
        user = Staff.objects.filter(office_email__iexact=username).first()
        if user is None:
            user = Staff.objects.create_user(
                office_email=username,
                password=password,
                first_name="E2E",
                last_name="Test",
                is_office_staff=True,
                is_superuser=True,
                base_wage_rate=base_wage,
                employment_start_date=E2E_EMPLOYMENT_START,
            )
        else:
            user.set_password(password)
            user.is_office_staff = True
            user.is_superuser = True
            user.base_wage_rate = base_wage
            user.save()
        if user.wage_rate != E2E_USER_WAGE_RATE:
            raise CommandError(
                f"The E2E user's wage computed to {user.wage_rate}, not {E2E_USER_WAGE_RATE}."
            )
        return user

    def _ensure_workshop_user(self, username: str, password: str) -> Staff:
        user = Staff.objects.filter(office_email__iexact=username).first()
        if user is None:
            return Staff.objects.create_user(
                office_email=username,
                password=password,
                first_name="E2E",
                last_name="Workshop",
                is_office_staff=False,
                is_workshop_staff=True,
                is_superuser=False,
                base_wage_rate=E2E_WORKSHOP_BASE_WAGE_RATE,
                employment_start_date=E2E_EMPLOYMENT_START,
            )
        user.set_password(password)
        user.is_office_staff = False
        user.is_workshop_staff = True
        user.is_superuser = False
        user.save()
        return user

    def _ensure_on_payroll(self, workshop_user: Staff) -> None:
        """Make the workshop login a payroll employee in the connected organisation.

        Specs book, approve and post its time, so it must be on every timesheet.
        The seed's own path creates the employee (employment, pay calendar,
        wages, working pattern, tax, payment method, leave) or links one that
        already holds its address.
        """
        tenant_id = get_tenant_id()
        if workshop_user.xero_user_id is not None and workshop_user.xero_tenant_id == tenant_id:
            return
        payroll_employee_sync.sync_staff([workshop_user], tenant_id=tenant_id, allow_create=True)
        workshop_user.refresh_from_db()
        if workshop_user.xero_user_id is None or workshop_user.xero_tenant_id != tenant_id:
            raise CommandError(
                f"The E2E workshop user {workshop_user.office_email} is still not a payroll "
                "employee in the connected Xero organisation."
            )
        self.stdout.write(
            f"E2E workshop user linked to payroll employee {workshop_user.xero_user_id}"
        )

    def _ensure_office_staff_user(self, username: str, password: str) -> Staff:
        user = Staff.objects.filter(office_email__iexact=username).first()
        if user is None:
            return Staff.objects.create_user(
                office_email=username,
                password=password,
                first_name="E2E",
                last_name="Office",
                is_office_staff=True,
                is_superuser=False,
                base_wage_rate=E2E_WORKSHOP_BASE_WAGE_RATE,
                employment_start_date=E2E_EMPLOYMENT_START,
            )
        user.set_password(password)
        user.is_office_staff = True
        user.is_superuser = False
        user.save()
        return user

    def _ensure_test_company(self) -> Company:
        defaults = CompanyDefaults.get_solo()
        if not defaults.test_company_name:
            defaults.test_company_name = TEST_COMPANY_NAME
            defaults.save(update_fields=["test_company_name"])
        company = Company.objects.filter(name=defaults.test_company_name).first()
        if company is None:
            now = timezone.now()
            company = Company.objects.create(
                name=defaults.test_company_name,
                is_account_customer=False,
                xero_last_modified=now,
                xero_last_synced=now,
            )
        return company
