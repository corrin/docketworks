"""Archive the E2E-created contacts in the connected Xero organisation.

Fable: archiving rather than ignoring, because Xero contacts cannot be
deleted and the contact sync is incremental by modification time: a locally
deleted E2E company returns the next time its contact is touched in Xero,
and the sync-window filter (apps/xero/e2e_artifacts.py) only covers objects
changed inside a recorded run. Once archived, the contact mirrors back as an
archived company, which e2e_cleanup and the E2E preflight treat as the
organisation's truth rather than residue.

Dry run unless ``--confirm`` is supplied. e2e_cleanup runs it first on every
confirmed cleanup, so the production and read-only guards here trip before
any local row is deleted.
"""

from django.core.management.base import BaseCommand, CommandParser

from apps.core.test_data import is_e2e_name
from apps.xero.contacts import archive_contacts_in_xero
from apps.xero.operator_guards import assert_not_production_target, assert_xero_writes_enabled
from apps.xero.seeding import XeroContactRef, get_all_xero_contacts


def active_e2e_contacts(contacts: list[XeroContactRef]) -> list[XeroContactRef]:
    """Return the contacts still to archive: E2E residue that is not yet archived."""
    return [
        contact
        for contact in contacts
        if contact.contact_status == "ACTIVE" and is_e2e_name(contact.name)
    ]


class Command(BaseCommand):
    """Report or archive the E2E-created contacts in Xero."""

    help = "Archive E2E-created Xero contacts. Dry run by default; use --confirm to archive."

    def add_arguments(self, parser: CommandParser) -> None:
        """Add the explicit destructive-operation confirmation flag."""
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually archive the contacts (default is dry run)",
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Check the target, list the active E2E contacts, archive them when confirmed."""
        confirm = options["confirm"]
        if not isinstance(confirm, bool):
            raise TypeError("The confirm option must be a boolean")

        assert_not_production_target()
        assert_xero_writes_enabled("archive_test_contacts")

        contacts = active_e2e_contacts(get_all_xero_contacts())
        self.stdout.write(f"Active E2E contacts in Xero: {len(contacts)}")
        for contact in contacts:
            self.stdout.write(f"  - {contact.name}")
        if not contacts:
            return
        if not confirm:
            self.stdout.write("DRY RUN — run with --confirm to archive them.")
            return

        outcome = archive_contacts_in_xero([contact.contact_id for contact in contacts])
        names = {contact.contact_id: contact.name for contact in contacts}
        for contact_id, reason in outcome.refused.items():
            # Fable: reported, not raised. Xero refuses to archive a contact with
            # transactions against it, which no cleanup can change; failing here
            # would strand every E2E reset on one spec's authorised PO.
            self.stdout.write(self.style.WARNING(f"Xero refused {names[contact_id]}: {reason}"))
        self.stdout.write(self.style.SUCCESS(f"Archived {len(outcome.archived)} contacts in Xero."))
