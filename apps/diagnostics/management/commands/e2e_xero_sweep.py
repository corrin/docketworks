"""Remove E2E residue the Xero organisation still holds. Development only.

``e2e_cleanup`` undoes what a run did, reading the Xero ids off the local rows
that run wrote. That is the right question for a teardown and the wrong one for
an organisation which has been accumulating test objects since before the
teardown existed, or which a hard-killed run wrote to and then lost the
database for. This command asks the other question — what does the
organisation hold that only E2E could have made — and answers it from the
organisation itself.

Recognition is the ``[TEST]`` naming convention in ``apps/core/test_data.py``,
applied to the owning contact. Documents on the standing fixture company are
residue and are removed; the fixture contact itself is seed data and is never
archived, which is why the two predicates there are separate.

Fable: everything is listed and filtered here, rather than asked for with
Xero's ``where`` / ``contact_i_ds`` / ``status`` query parameters. Those are an
undocumented vendor contract that would have to be probed against the live
organisation before anything could depend on it, and they differ per entity —
purchase orders take no contact filter at all. A demo organisation holds few
enough documents that paging the lot costs less than establishing that
contract, and one filter for four entity types is one thing to keep right.

Dry run unless ``--confirm``, like ``e2e_cleanup``. Reading is safe; the
removal is not, and it is measured in Xero's daily quota.
"""

from django.core.management.base import BaseCommand, CommandParser

from apps.core.test_data import TEST_COMPANY_NAME, is_e2e_name, is_test_company_name
from apps.diagnostics.services.e2e_xero_residue import (
    RemovalOutcome,
    XeroResidue,
    remove_residue_from_xero,
)
from apps.xero.constants import XERO_CONTACT_STATUSES
from apps.xero.e2e_artifacts import owning_company_name
from apps.xero.sync import iter_xero_entities

#: ENTITY_CONFIGS keys for the documents an E2E run raises, paired with the
#: attributes each SDK model names its own id and number with.
DOCUMENT_ENTITIES = (
    ("invoices", "invoice_id", "invoice_number"),
    ("quotes", "quote_id", "quote_number"),
    ("purchase_orders", "purchase_order_id", "purchase_order_number"),
)

#: Statuses Xero has already removed the document from. Re-deleting one is a
#: refusal, not a no-op, so a swept organisation would otherwise report the
#: same failures on every later run.
REMOVED_DOCUMENT_STATUSES = frozenset({"DELETED", "VOIDED"})


class Command(BaseCommand):
    """Report the E2E residue in the connected Xero organisation; remove it when confirmed."""

    help = (
        "Delete E2E invoices, quotes and purchase orders in Xero and archive E2E contacts, "
        "found by reading the organisation. Dry run by default; use --confirm to act."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Add the explicit destructive-operation confirmation flag."""
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually remove the residue (default is dry run)",
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Report what the organisation holds, then remove it when confirmed."""
        confirm = options["confirm"]
        if not isinstance(confirm, bool):
            raise TypeError("The confirm option must be a boolean")

        residue = self._find_residue()
        if residue.is_empty():
            self.stdout.write("\nNo E2E residue in the Xero organisation.")
            return

        if not confirm:
            self.stdout.write(f"\n=== DRY RUN — {residue.total()} objects would be removed ===")
            self.stdout.write(
                "Run with --confirm to act:\n  python manage.py e2e_xero_sweep --confirm"
            )
            return

        self._report_removal(remove_residue_from_xero(residue, "e2e_xero_sweep"))

    def _find_residue(self) -> XeroResidue:
        """Read the organisation and keep what only E2E could have created."""
        documents: dict[str, dict[str, str]] = {entity: {} for entity, _, _ in DOCUMENT_ENTITIES}
        for entity, id_attribute, number_attribute in DOCUMENT_ENTITIES:
            found = documents[entity]
            for item in iter_xero_entities(entity):
                if not is_test_company_name(owning_company_name(item)):
                    continue
                status: str | None = getattr(item, "status", None)
                if status in REMOVED_DOCUMENT_STATUSES:
                    continue
                xero_id: str | None = getattr(item, id_attribute, None)
                if xero_id is None:
                    raise ValueError(f"Xero returned a {entity} entry with no {id_attribute}")
                number: str | None = getattr(item, number_attribute, None)
                if number is None:
                    raise ValueError(f"Xero {entity} {xero_id} carries no {number_attribute}")
                found[str(xero_id)] = str(number)
            self.stdout.write(f"  {entity}: {len(found)} to remove")

        return XeroResidue(
            invoices=documents["invoices"],
            quotes=documents["quotes"],
            purchase_orders=documents["purchase_orders"],
            contacts=self._find_contacts(),
        )

    def _find_contacts(self) -> dict[str, str]:
        """Find the active E2E-named contacts, which are residue, and no others.

        ``is_e2e_name`` rather than ``is_test_company_name``: the standing
        fixture company passes the second and must never be archived, because
        every spec selects it by name on the way in.
        """
        contacts: dict[str, str] = {}
        for contact in iter_xero_entities("contacts"):
            name: str | None = getattr(contact, "name", None)
            contact_id: str | None = getattr(contact, "contact_id", None)
            if name is None or contact_id is None:
                raise ValueError(f"Xero returned a contact without a name or id: {contact}")
            status: str | None = getattr(contact, "contact_status", None)
            if status not in XERO_CONTACT_STATUSES:
                raise ValueError(f"Xero contact {contact_id} has unhandled status {status!r}")
            if status == "ACTIVE" and is_e2e_name(name):
                contacts[str(contact_id)] = name
        self.stdout.write(
            f"  contacts: {len(contacts)} to archive "
            f"({TEST_COMPANY_NAME} is seed data and is left active)"
        )
        return contacts

    def _report_removal(self, outcome: RemovalOutcome) -> None:
        """Print what Xero accepted and what it refused."""
        for kind, count in outcome.removed.items():
            self.stdout.write(self.style.SUCCESS(f"  Xero: removed {count} {kind}(s)."))
        for refusal in outcome.refused:
            # Reported, not raised: a BILLED purchase order or an ACCEPTED
            # quote is past the state Xero allows removing from, which no
            # sweep can undo, and one of them must not abort the rest.
            self.stdout.write(
                self.style.WARNING(
                    f"  Xero refused {refusal.kind} {refusal.label}: {refusal.reason}"
                )
            )
