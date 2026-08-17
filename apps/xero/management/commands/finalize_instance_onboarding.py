"""Finalize a freshly created instance after its Xero OAuth connection exists.

The post-OAuth sequence: bind the tenant and validate calendar/pay items/
branding theme (``xero --setup``), sync pay items and accounts, import active
staff from Xero, create the eleven shop jobs — and only when every step has
succeeded, set ``enable_xero_sync=True``. Any failure exits non-zero with
sync left disabled; the command is rerunnable from the top.
"""

import logging

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.core.errors import persist_app_error
from apps.core.models import CompanyDefaults
from apps.timesheet.services import payroll_employee_sync
from apps.xero.auth import get_tenant_id, get_valid_token
from apps.xero.leave_configuration import configure_default_leave_types
from apps.xero.models import XeroAccount
from apps.xero.payroll_sync import sync_xero_pay_items
from apps.xero.sync import one_way_sync_all_xero_data

logger = logging.getLogger(__name__)


def _sync_accounts() -> None:
    """Force a full account sync and require it to have imported something."""
    errors = [
        event["message"]
        for event in one_way_sync_all_xero_data(entities=["accounts"], force=True)
        if event["severity"] == "error"
    ]
    if errors:
        raise CommandError("Xero account sync failed: " + "; ".join(errors))
    if not XeroAccount.objects.exists():
        raise CommandError("Xero account sync completed without importing any accounts.")


def _sync_staff(*, seed_xero: bool) -> None:
    """Link staff to payroll employees, or refuse the direction that is unported.

    ``--seed-xero`` is the demo direction: push wage-earning Staff into the
    connected organisation, creating the employees it does not hold. Without
    it, v1 went the other way — importing employees FROM the organisation to
    create Staff rows — which is the fresh-prospect case and still a seam.
    """
    if not seed_xero:
        raise CommandError(
            "blocked-by:payroll-employees — onboarding without --seed-xero imports staff "
            "FROM the payroll organisation, which needs the unported employee salary and "
            "working-pattern reads (apps/timesheet/services/payroll_employee_sync.py, "
            "import_staff_from_xero). Automated Xero sync remains disabled."
        )

    result = payroll_employee_sync.sync_staff(tenant_id=get_tenant_id(), allow_create=True)
    # v1 re-counted wage-earning Staff without a xero_user_id here and failed
    # if any remained. sync_staff creates every unmatched row it is given and
    # raises otherwise, so the re-count could only ever have restated its
    # postcondition (ADR 0039).
    logger.info(
        "Staff payroll sync: %d linked, %d created, %d already linked",
        len(result.linked),
        len(result.created),
        len(result.already_linked),
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
        configure_default_leave_types()
        # The blocked leg runs last among the legs so everything portable has
        # actually run before the refusal. v1 ordered staff before shop jobs;
        # neither depends on the other.
        _sync_staff(seed_xero=seed_xero)

        # No completion re-validation: each leg above enforces its own
        # contract (xero --setup refuses unset CompanyDefaults fields,
        # create_shop_jobs raises on its own failures), and re-counting their
        # outputs here was a second implementation of those contracts.
        CompanyDefaults.set_xero_sync_enabled(enabled=True)
