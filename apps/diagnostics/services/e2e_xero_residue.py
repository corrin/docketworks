"""Remove the Xero objects an E2E run leaves behind. Development only.

The suite drives the real app against a live demo organisation, so a run
creates a contact per new company, an invoice, a quote and a purchase order
there. Teardown restores the local database from a pre-run dump, which erases
the mirror rows but not the objects they mirror.

This module is the one removal routine, shared by the two commands that find
the residue different ways: ``e2e_cleanup`` reads the ids off the local rows a
run left, and ``e2e_xero_sweep`` reads them off the organisation itself.
Finding is what differs between them; removing is not, and the order it
happens in is the part that has to be right.

**Documents before contacts.** Xero refuses to archive a contact that still has
transactions against it, so archiving first is refused for exactly the contacts
a run gave work to. That refusal is why the suite's ``[TEST]`` suppliers
accumulated in the organisation while the archive step reported success every
run.

Opus: a document is set to DELETED rather than left and hidden. The rejected
alternative is ``apps/xero/e2e_artifacts.py``'s window, which only suppresses a
finished run's objects on the way back IN; the organisation still holds them,
and anyone reading it — an operator, a report, the seed's existence lookup —
sees a decade of test invoices. The window still earns its place for the span
between a document's creation and this removal, and for what Xero offers no way
to remove at all: a BILLED purchase order, an ACCEPTED quote, the payroll draft
runs of ADR 0007.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from apps.accounting.registry import get_provider
from apps.accounting.types import DocumentResult
from apps.xero.contacts import archive_contacts_in_xero
from apps.xero.operator_guards import assert_not_production_target, assert_xero_writes_enabled

logger = logging.getLogger(__name__)


class ResidueKind(StrEnum):
    """The Xero object types an E2E run creates and this module removes."""

    INVOICE = "invoice"
    QUOTE = "quote"
    PURCHASE_ORDER = "purchase order"
    CONTACT = "contact"


@dataclass(frozen=True)
class XeroResidue:
    """The Xero objects one removal covers, whatever found them.

    Each entry maps the Xero id to the name to report it by — a contact's
    company name, a document's number. Both finders know the name at the
    moment they find the id, and a refusal reported as a bare GUID is one an
    operator has to go and look up before it means anything.
    """

    invoices: dict[str, str] = field(default_factory=dict)
    quotes: dict[str, str] = field(default_factory=dict)
    purchase_orders: dict[str, str] = field(default_factory=dict)
    contacts: dict[str, str] = field(default_factory=dict)

    def is_empty(self) -> bool:
        """Report whether there is nothing to remove."""
        return not (self.invoices or self.quotes or self.purchase_orders or self.contacts)

    def total(self) -> int:
        """Count every object this removal would touch."""
        return (
            len(self.invoices) + len(self.quotes) + len(self.purchase_orders) + len(self.contacts)
        )


@dataclass(frozen=True)
class Refusal:
    """One object Xero declined to remove, and why."""

    kind: ResidueKind
    xero_id: str
    label: str
    reason: str


@dataclass(frozen=True)
class RemovalOutcome:
    """What Xero did with a removal request, object by object."""

    removed: dict[ResidueKind, int] = field(default_factory=dict)
    refused: tuple[Refusal, ...] = ()


def _refusal_reason(result: DocumentResult) -> str:
    """Xero's reason for declining a document, as one line.

    The provider reports a rejection two ways — element-level validation
    errors for a document Xero understood but would not change, and ``error``
    for everything else — and a caller reporting residue needs whichever
    arrived.
    """
    if result.validation_errors:
        return "; ".join(result.validation_errors)
    return result.error or "refused without a message"


def remove_residue_from_xero(residue: XeroResidue, operation: str) -> RemovalOutcome:
    """Delete the given documents in Xero, then archive the given contacts.

    Refusals are reported, never raised: Xero declines to remove a document
    that has moved past the state it allows removing from (a BILLED purchase
    order, an ACCEPTED quote), which no cleanup can undo, and raising would
    strand every later run on one spec's leftover. A malformed response still
    raises, from the routines below.

    Nothing to remove means nothing sent, checked BEFORE the guards rather
    than after. The guards resolve the tenant, which reads the stored token and
    rotates it against Xero's identity endpoint if it is near expiry. A
    rotation costs no API quota; what it costs is the refresh token, which Xero
    issues single-use, so the copy any other holder has just died. The E2E
    teardown goes to some length to keep exactly that from happening
    (frontend/tests/scripts/global-teardown.ts), and a run whose database names
    no Xero object should not be spending one.
    """
    if residue.is_empty():
        return RemovalOutcome()

    assert_not_production_target()
    assert_xero_writes_enabled(operation)

    provider = get_provider()
    removed: dict[ResidueKind, int] = dict.fromkeys(ResidueKind, 0)
    refused: list[Refusal] = []

    documents: tuple[
        tuple[ResidueKind, Mapping[str, str], Callable[[str], DocumentResult]], ...
    ] = (
        (ResidueKind.INVOICE, residue.invoices, provider.delete_invoice),
        (ResidueKind.QUOTE, residue.quotes, provider.delete_quote),
        (ResidueKind.PURCHASE_ORDER, residue.purchase_orders, provider.delete_purchase_order),
    )
    for kind, entries, delete in documents:
        for xero_id, label in entries.items():
            result = delete(xero_id)
            if result.success:
                removed[kind] += 1
            else:
                refused.append(
                    Refusal(kind=kind, xero_id=xero_id, label=label, reason=_refusal_reason(result))
                )

    # Only now, with the transactions gone, will Xero accept the archive.
    if residue.contacts:
        outcome = archive_contacts_in_xero(tuple(residue.contacts))
        removed[ResidueKind.CONTACT] = len(outcome.archived)
        refused.extend(
            Refusal(
                kind=ResidueKind.CONTACT,
                xero_id=contact_id,
                label=residue.contacts[contact_id],
                reason=reason,
            )
            for contact_id, reason in outcome.refused.items()
        )

    logger.info(
        "Removed %d E2E objects from Xero for %s, %d refused",
        sum(removed.values()),
        operation,
        len(refused),
    )
    return RemovalOutcome(removed=removed, refused=tuple(refused))
