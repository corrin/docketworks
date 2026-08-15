"""Seed a non-production Xero organisation from a restored database.

Run after restoring a scrubbed production dump into a dev/UAT instance and
after ``manage.py xero --setup``. It clears the production Xero ids the dump
carries, then links or creates the local records in the connected organisation
so the following ``start_xero_sync`` runs clean instead of creating duplicates.

Two v1 phases are absent: PROJECTS (Xero Projects is unported) and EMPLOYEES
(the payroll employee API is a recorded Phase 4 deferral). Asking for either
by name is an error rather than a silent skip.
"""

import logging

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.accounting.models import Invoice, Quote
from apps.core.errors import persist_app_error
from apps.core.models import CompanyDefaults
from apps.purchasing.models import Stock
from apps.xero.client import XeroQuotaFloorReached
from apps.xero.operator_guards import assert_not_production_target, assert_xero_writes_enabled
from apps.xero.payroll_sync import sync_xero_pay_items
from apps.xero.seeding import (
    clear_production_xero_ids,
    companies_needing_contacts,
    seed_accounts_from_xero,
    seed_companies_to_xero,
    seed_invoices,
    seed_quotes,
)
from apps.xero.stock_sync import sync_all_local_stock_to_xero

logger = logging.getLogger(__name__)

VALID_ENTITIES = ("accounts", "contacts", "invoices", "quotes", "stock")
# Named so the operator gets the reason, not "invalid entity".
DEFERRED_ENTITIES = {
    "projects": "Xero Projects is not ported (Phase 4); jobs carry no project id in v2.",
    "employees": (
        "The Xero payroll employee API is not ported (Phase 4). Staff are not linked to "
        "payroll employees in the target organisation, so timesheet posting stays broken "
        "against it."
    ),
}


class Command(BaseCommand):
    """Re-point the local Xero mirror at the connected non-production organisation."""

    help = "Seed the connected (non-production) Xero organisation from the local database."

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the dry-run, phase-selection and re-run flags."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be seeded without calling Xero or writing locally",
        )
        parser.add_argument(
            "--only",
            type=str,
            help=f"Comma-separated phases to run. Valid: {','.join(VALID_ENTITIES)}",
        )
        parser.add_argument(
            "--skip-clear",
            action="store_true",
            help="Skip clearing production Xero ids (for re-running after a partial failure)",
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Run the requested phases, persisting any failure with its context."""
        try:
            self._handle(**options)
        except Exception as exc:
            persist_app_error(exc)
            raise

    def _handle(self, **options: object) -> None:  # noqa: C901 -- the phase ladder is this command's contract
        dry_run = bool(options["dry_run"])
        skip_clear = bool(options["skip_clear"])
        only_option = options["only"]

        assert_xero_writes_enabled("manage.py seed_xero_from_database")
        entities = self._parse_entities(only_option)

        # Checked before ANY phase, not only inside the clear phase: with
        # --skip-clear v1 never reached its production check and would have
        # pushed fabricated data into the live organisation.
        try:
            assert_not_production_target()
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        mode = "DRY RUN - " if dry_run else ""
        self.stdout.write(f"{mode}Seeding Xero from database (phases: {sorted(entities)})")
        self.stdout.write("=" * 60)

        cleared = False
        if skip_clear:
            self.stdout.write("Skipping the clear phase (--skip-clear)")
        elif dry_run:
            self.stdout.write("Would clear production Xero ids")
        else:
            self.stdout.write("Clearing production Xero ids...")
            result = clear_production_xero_ids()
            for column, count in result.cleared.items():
                self.stdout.write(f"  {column}: {count}")
            self.stdout.write("  staff.xero_user_id: preserved (crash-recovery marker)")
            cleared = True

        if "accounts" in entities:
            self._seed_accounts(dry_run=dry_run)

        if "contacts" in entities:
            self._seed_contacts(dry_run=dry_run)

        # The clear phase nulled every XeroPayItem xero_id, and job/cost-line
        # rows reference those pay items. Re-syncing here (not in the deferred
        # employees phase, where v1 had it) is what re-points them; its own
        # referential check fails the run if any referenced item is unmatched.
        if cleared:
            self.stdout.write("Re-syncing pay items against the target organisation...")
            pay_items = sync_xero_pay_items()
            self.stdout.write(f"  pay items touched: {pay_items['records_updated']}")

        if "invoices" in entities:
            self._seed_invoices(dry_run=dry_run)

        if "quotes" in entities:
            self._seed_quotes(dry_run=dry_run)

        if "stock" in entities:
            self._seed_stock(dry_run=dry_run)

        self.stdout.write("=" * 60)
        if dry_run:
            self.stdout.write("Dry run complete - no changes made")
            return
        self._finish(partial=only_option is not None)

    def _finish(self, *, partial: bool) -> None:
        """Close the batch: only a FULL successful run re-opens the sync gate.

        The seed is a batch process — syncing may exist only after the whole
        batch reports success. A partial (--only) run leaves the gate as it
        found it: re-enabling here re-opened beat syncs and webhook echoes
        mid-batch, which is how the 2026-08-14 duplicate contacts happened.
        """
        if partial:
            self.stdout.write(
                self.style.SUCCESS(
                    "Partial seed complete; enable_xero_sync left unchanged — "
                    "only a full seed re-opens the sync gate."
                )
            )
            return

        CompanyDefaults.set_xero_sync_enabled(enabled=True)
        self.stdout.write(self.style.SUCCESS("Seeding complete; enable_xero_sync is now True."))
        self.stdout.write(
            self.style.WARNING(
                "Payroll employees were NOT seeded: the Xero payroll employee API is a "
                "Phase 4 deferral. Staff have no employee link in this organisation, so "
                "timesheet posting against it will fail until that ports."
            )
        )

    def _parse_entities(self, only_option: object) -> set[str]:
        """Resolve --only into the phases to run, naming what is unported."""
        if only_option is None:
            return set(VALID_ENTITIES)
        if not isinstance(only_option, str):
            raise TypeError("The --only option must be a string")

        requested = {entity.strip().lower() for entity in only_option.split(",") if entity.strip()}
        if not requested:
            raise CommandError("--only was given with no phases.")

        deferred = requested & DEFERRED_ENTITIES.keys()
        if deferred:
            reasons = "; ".join(f"{name}: {DEFERRED_ENTITIES[name]}" for name in sorted(deferred))
            raise CommandError(f"Requested phase(s) are not ported - {reasons}")

        invalid = requested - set(VALID_ENTITIES)
        if invalid:
            raise CommandError(
                f"Unknown phase(s): {sorted(invalid)}. Valid: {','.join(VALID_ENTITIES)}"
            )
        return requested

    def _seed_accounts(self, *, dry_run: bool) -> None:
        self.stdout.write("Syncing the chart of accounts...")
        if dry_run:
            self.stdout.write("  would re-point local XeroAccount rows by account name")
            return
        result = seed_accounts_from_xero()
        self.stdout.write(f"  accounts: {result.updated} updated, {result.created} created")

    def _seed_contacts(self, *, dry_run: bool) -> None:
        self.stdout.write("Syncing contacts...")
        try:
            companies = companies_needing_contacts()
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"  {len(companies)} companies need a Xero contact id")
        if dry_run:
            for company in companies[:10]:
                self.stdout.write(f"  would process: {company.name}")
            if len(companies) > 10:
                self.stdout.write(f"  ... and {len(companies) - 10} more")
            return
        if not companies:
            return
        result = seed_companies_to_xero(companies)
        self.stdout.write(f"  contacts: {result.linked} linked, {result.created} created")

    def _seed_invoices(self, *, dry_run: bool) -> None:
        self.stdout.write("Syncing invoices...")
        if dry_run:
            orphans = Invoice.objects.filter(job__isnull=True).count()
            seedable = Invoice.objects.filter(job__isnull=False).count()
            self.stdout.write(f"  would delete {orphans} orphaned invoices")
            self.stdout.write(f"  would link or create {seedable} job-linked invoices")
            return
        result = seed_invoices()
        self.stdout.write(
            f"  invoices: {result.created} created, {result.linked} linked, "
            f"{result.orphans_deleted} orphans deleted, "
            f"{result.skipped_no_contact} skipped (company not linked)"
        )

    def _seed_quotes(self, *, dry_run: bool) -> None:
        self.stdout.write("Syncing quotes...")
        if dry_run:
            orphans = Quote.objects.filter(job__isnull=True).count()
            seedable = Quote.objects.filter(job__isnull=False).count()
            self.stdout.write(f"  would delete {orphans} orphaned quotes")
            self.stdout.write(f"  would link or create {seedable} job-linked quotes")
            return
        result = seed_quotes()
        self.stdout.write(
            f"  quotes: {result.created} created, {result.linked} linked, "
            f"{result.orphans_deleted} orphans deleted, "
            f"{result.skipped_no_contact} skipped (company not linked)"
        )

    def _seed_stock(self, *, dry_run: bool) -> None:
        self.stdout.write("Syncing stock items...")
        if dry_run:
            pending = Stock.objects.filter(xero_id__isnull=True, is_active=True).count()
            self.stdout.write(f"  would sync {pending} stock items")
            return
        try:
            result = sync_all_local_stock_to_xero(limit=None)
        # A manual seed is not automation: the day-quota floor exists to stop
        # scheduled syncs, so translate it into an instruction rather than a
        # traceback the operator has to decode.
        except XeroQuotaFloorReached as exc:
            raise CommandError(
                f"Xero's daily API quota is at the configured floor ({exc}). Wait for the "
                f"rolling 24h window to free quota, or lower "
                f"CompanyDefaults.xero_automated_day_floor, then re-run with --skip-clear."
            ) from exc
        self.stdout.write(
            f"  stock: {result['synced_count']} synced, {result['failed_count']} failed"
        )
        for item in result["failed_items"][:5]:
            self.stdout.write(f"    failed: {item['description']} - {item['reason']}")
