"""Seed a non-production Xero organisation from a restored database.

Run after restoring a scrubbed production dump into a dev/UAT instance and
after ``manage.py xero --setup``. It clears the production Xero ids the dump
carries, then links or creates the local records in the connected organisation
so the following ``start_xero_sync`` runs clean instead of creating duplicates.

A shell around ``apps.xero.seeding.run_seed``: this file parses arguments,
renders output and translates refusals into ``CommandError``. Whether the clear
runs, whether the pay items need re-linking and whether the batch is finished
are all measured from the database by ``run_seed`` — they are never inferred
from which options were typed.

One v1 phase is absent: PROJECTS (Xero Projects is unported). Asking for it by
name is an error rather than a silent skip. v1 gated that phase on
``XERO_SYNC_PROJECTS``, which its own production instance sets false, so a v1
restore never ran it either.
"""

import logging

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.core.errors import persist_app_error
from apps.xero.client import XeroQuotaFloorReached
from apps.xero.seeding import SeedRunOutcome, run_seed

logger = logging.getLogger(__name__)

VALID_ENTITIES = ("accounts", "contacts", "employees", "invoices", "quotes", "stock")
# Named so the operator gets the reason, not "invalid entity".
DEFERRED_ENTITIES = {
    "projects": "Xero Projects is not ported (Phase 4); jobs carry no project id in v2.",
}


class Command(BaseCommand):
    """Re-point the local Xero mirror at the connected non-production organisation."""

    help = "Seed the connected (non-production) Xero organisation from the local database."

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the dry-run and phase-selection flags."""
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

    def handle(self, *_args: object, **options: object) -> None:
        """Run the requested phases, persisting any failure with its context."""
        try:
            self._handle(**options)
        except Exception as exc:
            persist_app_error(exc)
            raise

    def _handle(self, **options: object) -> None:
        dry_run = bool(options["dry_run"])
        entities = self._parse_entities(options["only"])

        mode = "DRY RUN - " if dry_run else ""
        self.stdout.write(f"{mode}Seeding Xero from database (phases: {sorted(entities)})")
        self.stdout.write("=" * 60)

        try:
            outcome = run_seed(entities, dry_run=dry_run, report=self.stdout.write)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        # A manual seed is not automation: the day-quota floor exists to stop
        # scheduled syncs, so translate it into an instruction rather than a
        # traceback the operator has to decode.
        except XeroQuotaFloorReached as exc:
            raise CommandError(
                f"Xero's daily API quota is at the configured floor ({exc}). Wait for the "
                f"rolling 24h window to free quota, or lower "
                f"CompanyDefaults.xero_automated_day_floor, then re-run."
            ) from exc

        self.stdout.write("=" * 60)
        self._report_outcome(outcome)

    def _report_outcome(self, outcome: SeedRunOutcome) -> None:
        """State what the mirror still owes, and whether the gate was opened."""
        remaining = outcome.convergence.remaining
        if remaining:
            self.stdout.write("Remaining work:")
            for phase, count in remaining.items():
                self.stdout.write(f"  {phase}: {count}")
            self.stdout.write(
                "Not converged - enable_xero_sync stays False. Re-run (with or without "
                "--only) until every count is zero."
            )
            return

        self.stdout.write("Remaining work: none - the mirror is fully linked to this organisation.")
        # Read off the outcome rather than re-deriving from --dry-run: in this
        # branch the run converged, so a closed gate can only be the dry run
        # that measured it, and there is one statement of that rule (run_seed).
        if not outcome.gate_opened:
            self.stdout.write("Dry run complete - no changes made")
            return

        self.stdout.write(self.style.SUCCESS("Seeding complete; enable_xero_sync is now True."))

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
