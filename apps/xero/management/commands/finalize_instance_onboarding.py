"""Finalize a freshly created instance after its Xero OAuth connection exists.

The post-OAuth sequence: bind the tenant and validate calendar/pay items/
branding theme (``xero --setup``), sync pay items and accounts, import active
staff from Xero, create the nine shop jobs — and only when every step has
succeeded, set ``enable_xero_sync=True``. Any failure exits non-zero with
sync left disabled; the command is rerunnable from the top.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.core.errors import persist_app_error
from apps.core.models import CompanyDefaults
from apps.xero.auth import get_valid_token
from apps.xero.models import XeroAccount
from apps.xero.payroll_sync import sync_xero_pay_items
from apps.xero.sync import one_way_sync_all_xero_data


def _sync_accounts() -> None:
    """Force a full account sync and require it to have imported something."""
    errors = [
        event.get("message", "Unknown account sync error")
        for event in one_way_sync_all_xero_data(entities=["accounts"], force=True)
        if event.get("severity") == "error"
    ]
    if errors:
        raise CommandError("Xero account sync failed: " + "; ".join(errors))
    if not XeroAccount.objects.exists():
        raise CommandError("Xero account sync completed without importing any accounts.")


def _sync_staff(*, seed_xero: bool) -> None:
    """Link or import staff via Xero Payroll — blocked until Phase 4 lands.

    v1: with ``seed_xero`` it pushed wage-earning Staff to the demo tenant via
    ``sync_staff(allow_create=True)``; otherwise it imported active employees
    via ``import_staff_from_xero(initial_password="Default-staff-password")``,
    then required every wage-earning Staff row to carry a ``xero_user_id``.
    Both orchestration entry points exist as loud seams in
    ``apps.timesheet.services.payroll_employee_sync``; this raises rather than
    calling them so the operator sees the blockage as a refusal, not a
    traceback.
    """
    raise CommandError(
        "blocked-by:payroll-employees — the staff leg of instance onboarding "
        "needs the unported Xero Payroll employee API "
        f"(apps/timesheet/services/payroll_employee_sync.py, seed_xero={seed_xero}). "
        "Automated Xero sync remains disabled."
    )


class Command(BaseCommand):
    """Run the post-OAuth onboarding sequence; enable sync only at the end."""

    help = "Finalize Xero onboarding and enable synchronization for a new instance"

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the demo-seeding flag."""
        parser.add_argument(
            "--seed-xero",
            action="store_true",
            help="Create missing demo-only Xero configuration and employees",
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Run every onboarding leg, re-disabling sync on any failure."""
        seed_xero = options["seed_xero"]
        if not isinstance(seed_xero, bool):
            raise TypeError("The seed-xero option must be a boolean")

        # No gate write in the except path: _finalize's FIRST statement
        # closes the gate and its LAST statement is the only re-open, so any
        # raise between them provably leaves it closed already.
        try:
            self._finalize(seed_xero=seed_xero)
        except Exception as exc:
            # Expected refusals (CommandError) are already operator-readable
            # and create no AppError row; everything unexpected persists.
            if not isinstance(exc, CommandError):
                persist_app_error(exc)
            raise

        self.stdout.write(
            self.style.SUCCESS("Instance onboarding complete; automated Xero sync is enabled.")
        )

    def _finalize(self, *, seed_xero: bool) -> None:
        """Complete Xero-dependent setup, enabling automated sync LAST."""
        CompanyDefaults.set_xero_sync_enabled(enabled=False)

        if not get_valid_token():
            raise CommandError("Complete Xero OAuth before finalising instance onboarding.")

        xero_setup_args = ["--setup"]
        if seed_xero:
            xero_setup_args.append("--seed-xero")
        call_command("xero", *xero_setup_args)
        sync_xero_pay_items()
        _sync_accounts()
        # call_command rather than importing the command's internals: the shop
        # jobs have exactly one implementation and this is its public entry.
        call_command("create_shop_jobs")
        # The blocked leg runs last among the legs so everything portable has
        # actually run before the refusal. v1 ordered staff before shop jobs;
        # neither depends on the other.
        _sync_staff(seed_xero=seed_xero)

        # No completion re-validation: each leg above enforces its own
        # contract (xero --setup refuses unset CompanyDefaults fields,
        # create_shop_jobs raises on its own failures), and re-counting their
        # outputs here was a second implementation of those contracts.
        CompanyDefaults.set_xero_sync_enabled(enabled=True)
