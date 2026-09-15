"""Put the rows the E2E suite assumes into a database that never held them.

No production dump carries the E2E user, and a fresh instance carries no test
company: ``global-setup.ts`` fails at sign-in without the first, and every
UI-seeded spec searches for the second. Idempotent, so a restore runbook and
``verify-instance.sh --e2e`` (ADR 0064) both run it unconditionally.

The user's credentials come from the environment — the same
``E2E_TEST_USERNAME`` / ``E2E_TEST_PASSWORD`` Playwright reads — so the
password is never on a command line. Three properties of that user gate whole
clusters of specs: office staff (the navbar's Create Job), superuser (the
timesheet management surface), and a costing wage of exactly 45.00, which
``job-cost-entry-data.spec.ts`` pins. The wage is computed on save from the
base rate and this database's labour-cost loading, so the base is derived
from the loading rather than hard-coded (37.50 is only right at 20%).
"""

import os
from decimal import ROUND_HALF_UP, Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.core.environment import ProductionDatabaseError, assert_not_production_database
from apps.core.models import CompanyDefaults, loaded_wage_rate
from apps.core.test_data import TEST_COMPANY_NAME

#: The costing wage job-cost-entry-data.spec.ts pins as its environment prerequisite.
E2E_USER_WAGE_RATE = Decimal("45.00")


def _credentials() -> tuple[str, str]:
    try:
        return os.environ["E2E_TEST_USERNAME"], os.environ["E2E_TEST_PASSWORD"]
    except KeyError as exc:
        raise CommandError(
            f"{exc.args[0]} is not set; the E2E user's credentials come from the environment "
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
    """Create or align the E2E user and the test company."""

    help = "Create or align the E2E user and the test company the suite assumes (idempotent)."

    def handle(self, *_args: object, **_options: object) -> None:
        """Ensure both fixtures, reporting what each ended as."""
        try:
            assert_not_production_database(
                "it installs a superuser whose password is held in a file."
            )
        except ProductionDatabaseError as exc:
            raise CommandError(str(exc)) from exc
        username, password = _credentials()
        with transaction.atomic():
            user = self._ensure_user(username, password)
            company = self._ensure_test_company()
        self.stdout.write(
            f"E2E user {user.office_email}: office staff, superuser, wage {user.wage_rate}"
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
