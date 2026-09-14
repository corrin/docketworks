"""Fill the fake Xero's store from the mirror, so a fake run starts from "Xero as of now".

``run_e2e.sh --use-fake-xero`` runs this before the pre-run backup, so the
seeded store is inside the dump the teardown restores: a run's writes
vanish with the restore and the next run seeds afresh. Refuses a
non-empty store without ``--replace`` and refuses a production database.
"""

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.core.models import CompanyDefaults
from apps.xero.fake.rest_client import assert_fake_permitted
from apps.xero.fake.seed import SeedError, empty, held_objects, seed_everything


class Command(BaseCommand):
    """Seed the fake Xero from the mirror."""

    help = "Render every mirrored Xero object into the fake Xero's store (ADR 0060)."

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare --replace."""
        parser.add_argument(
            "--replace",
            action="store_true",
            help="empty the store first; without it a non-empty store is refused",
        )

    def handle(self, *args: object, **options: object) -> None:
        """Seed, reporting a count per kind."""
        del args
        company = CompanyDefaults.get_solo()
        tenant_id = company.xero_tenant_id
        if not tenant_id:
            raise CommandError(
                "CompanyDefaults.xero_tenant_id is unset; bind the installation first"
            )
        assert_fake_permitted()
        existing = held_objects(tenant_id)
        if existing and not options["replace"]:
            raise CommandError(
                f"the fake already holds {existing} objects for {tenant_id}; "
                "pass --replace to seed over them"
            )
        empty(tenant_id)
        try:
            counts = seed_everything(tenant_id, organisation_name=company.company_name)
        except SeedError as exc:
            raise CommandError(str(exc)) from exc
        for kind, count in counts.items():
            self.stdout.write(f"  {kind:16s} {count}")
        self.stdout.write(self.style.SUCCESS(f"Seeded the fake Xero for {tenant_id}"))
