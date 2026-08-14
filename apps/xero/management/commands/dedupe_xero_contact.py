"""Archive spurious duplicate Xero contacts sharing one name.

An aborted seed run can create the same contact twice in a concurrent-batch
race — the Xero API permits duplicate active names though the UI refuses
them — after which ``start_xero_sync`` aborts on its same-name guard
(``Name '<x>' already linked to Xero ID <a>, cannot link to <b>``). Xero
has no hard delete for contacts, so archiving the spurious copies IS the
garbage collection.

The command archives only contacts that are provably spurious: ACTIVE,
carrying exactly the given name, and referenced by no local Company row.
The one contact the local mirror references is never touched, and the
command refuses entirely when the local linkage is absent or ambiguous —
resolving THAT needs a human decision, not a tool guessing. Dry-run by
default, like the timesheet repair commands; ``--apply`` writes.
"""

from django.core.management.base import BaseCommand, CommandError, CommandParser
from xero_python.accounting import AccountingApi, Contact, Contacts

from apps.company.models import Company
from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.operator_guards import (
    assert_not_production_target,
    assert_xero_writes_enabled,
)


class Command(BaseCommand):
    """Archive unreferenced ACTIVE duplicates of one contact name."""

    help = (
        "Archive spurious duplicate Xero contacts for --name: ACTIVE, same "
        "name, referenced by no local company. Dry-run unless --apply."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the target name and the write flag."""
        parser.add_argument(
            "--name",
            required=True,
            help="The exact contact name the sync reported as conflicted.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Archive the spurious duplicates (default is a dry-run report).",
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Refuse unsafe targets, identify the spurious copies, archive them."""
        name = options["name"]
        if not isinstance(name, str) or not name:
            raise CommandError("--name must be a non-empty string")
        apply_changes = bool(options["apply"])

        assert_xero_writes_enabled("dedupe_xero_contact")
        assert_not_production_target()

        local = list(
            Company.objects.filter(name=name)
            .exclude(xero_contact_id__isnull=True)
            .values_list("xero_contact_id", flat=True)
        )
        if len(local) != 1:
            raise CommandError(
                f"{len(local)} local companies named {name!r} carry a Xero link; "
                "this tool resolves exactly one linked row against its "
                "duplicates. Resolve the local rows first."
            )
        linked_id = str(local[0])

        api = AccountingApi(get_api_client())
        tenant_id = get_tenant_id()
        response = api.get_contacts(tenant_id, where=f'Name="{name}"')
        matches = [
            contact
            for contact in (response.contacts or [])
            if contact.name == name and contact.contact_status == "ACTIVE"
        ]
        if not any(str(contact.contact_id) == linked_id for contact in matches):
            raise CommandError(
                f"The locally linked contact {linked_id} is not among the ACTIVE "
                f"contacts named {name!r} in this organisation — this is not the "
                "duplicate-pair shape; do not archive anything."
            )
        spurious = [contact for contact in matches if str(contact.contact_id) != linked_id]
        if not spurious:
            raise CommandError(
                f"No spurious ACTIVE duplicate named {name!r}: the only active "
                f"contact is the one the local mirror references ({linked_id})."
            )

        referenced = {
            str(cid)
            for cid in Company.objects.exclude(xero_contact_id__isnull=True)
            .filter(xero_contact_id__in=[str(c.contact_id) for c in spurious])
            .values_list("xero_contact_id", flat=True)
        }
        if referenced:
            raise CommandError(
                f"Refusing: duplicate contact(s) {sorted(referenced)} are "
                "referenced by other local companies — that is cross-linked "
                "data, not a spurious copy."
            )

        self.stdout.write(f"Locally linked (kept): {linked_id}")
        for contact in spurious:
            # Archiving by status alone is rejected: Xero validates name
            # uniqueness across active contacts on EVERY update, including
            # the archiving one, so the duplicate must be renamed out of the
            # collision in the same update that archives it.
            tombstone = f"{name} (duplicate {str(contact.contact_id)[:8]})"
            if apply_changes:
                api.update_contact(
                    tenant_id,
                    str(contact.contact_id),
                    Contacts(
                        contacts=[
                            Contact(
                                contact_id=contact.contact_id,
                                name=tombstone,
                                contact_status="ARCHIVED",
                            )
                        ]
                    ),
                )
                self.stdout.write(
                    f"Archived spurious duplicate {contact.contact_id} as {tombstone!r}"
                )
            else:
                self.stdout.write(
                    f"[DRY-RUN] would archive spurious duplicate {contact.contact_id} "
                    f"as {tombstone!r}"
                )
        if not apply_changes:
            self.stdout.write("Re-run with --apply to archive.")
