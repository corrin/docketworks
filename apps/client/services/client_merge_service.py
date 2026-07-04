"""
Reassign FK records from one Client (source) to another (destination).

The Client.merged_into pointer alone leaves historical records stranded on
the merged-from row — queries filtered by the merged-into client miss the
absorbed history. This service moves the 8 client-referencing FK fields in
a single atomic block.

Callers pick the destination explicitly:
- Xero sync paths typically pass ``source.get_final_client()`` so absorbed
  history lands on the terminal client in a merge chain (A -> B -> C).
- The local dedup command passes a hand-picked primary client.
"""

import logging

from django.db import transaction

from apps.client.models import Client, ClientContact, ClientContactMethod
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger("xero")


def _move_contact_methods(
    *,
    source_contact: ClientContact | None,
    source_client: Client | None,
    destination_contact: ClientContact | None,
    destination_client: Client | None,
) -> int:
    if source_contact is None:
        source_queryset = ClientContactMethod.objects.filter(
            client=source_client,
            contact__isnull=True,
        )
    else:
        source_queryset = ClientContactMethod.objects.filter(contact=source_contact)

    affected = 0
    for method in source_queryset.select_related("client", "contact").iterator():
        destination_filter: dict[str, str | bool | Client | ClientContact | None] = {
            "method_type": method.method_type,
            "normalized_value": method.normalized_value,
        }
        if destination_contact is None:
            destination_filter.update(
                {"client": destination_client, "contact__isnull": True}
            )
        else:
            destination_filter.update({"contact": destination_contact})

        if ClientContactMethod.objects.filter(**destination_filter).exists():
            method.delete()
            affected += 1
            continue

        method.client = destination_client
        method.contact = destination_contact
        method.save(update_fields=["client", "contact", "updated_at"])
        affected += 1
    return affected


def _move_client_contacts_and_methods(
    source: Client, destination: Client
) -> dict[str, int]:
    """Move CRM contact ownership before the source client is deleted."""

    from apps.crm.models import PhoneCallRecord

    counts = {
        "contacts": 0,
        "contact_methods": 0,
        "phone_calls": 0,
    }

    counts["contact_methods"] += _move_contact_methods(
        source_contact=None,
        source_client=source,
        destination_contact=None,
        destination_client=destination,
    )

    for contact in ClientContact.objects.filter(client=source).iterator():
        destination_contact = ClientContact.objects.filter(
            client=destination,
            name=contact.name,
        ).first()
        if destination_contact is None:
            contact.client = destination
            contact.save(update_fields=["client", "updated_at"])
            destination_contact = contact
        else:
            counts["contact_methods"] += _move_contact_methods(
                source_contact=contact,
                source_client=None,
                destination_contact=destination_contact,
                destination_client=None,
            )
            counts["phone_calls"] += PhoneCallRecord.objects.filter(
                contact=contact
            ).update(
                client=destination,
                contact=destination_contact,
            )
            contact.delete()

        counts["contacts"] += 1

    counts["phone_calls"] += PhoneCallRecord.objects.filter(client=source).update(
        client=destination
    )
    return counts


def reassign_client_fk_records(
    source: Client,
    destination: Client,
    staff,
    *,
    logger_prefix: str = "",
) -> dict[str, int]:
    """
    Move every client-referencing FK record from ``source`` to ``destination``.

    Returns a dict of per-model rowcounts, e.g. ``{"jobs": 3, ...}``.

    Job records are iterated and saved so JobEvents are generated. All other
    tables use bulk ``.update()``.

    Args:
        staff: Staff to attribute the JobEvents to. Xero-sync callers should
            pass ``Staff.get_automation_user()``.

    Raises:
        ValueError: if ``destination == source`` (the service refuses this
            no-op because it almost certainly indicates a caller bug, e.g.
            a chain-walk that terminated at a cycle).
    """
    if destination.id == source.id:
        raise ValueError(
            f"reassign_client_fk_records: source and destination are the "
            f"same client ({source.id}); refusing to run"
        )

    # Late imports to avoid circular-import at Django app-loading time.
    from apps.accounting.models import Bill, CreditNote, Invoice, Quote
    from apps.job.models import Job
    from apps.purchasing.models import PurchaseOrder
    from apps.quoting.models import ScrapeJob, SupplierPriceList, SupplierProduct

    try:
        with transaction.atomic():
            jobs_moved = 0
            for job in Job.objects.filter(client=source):
                job.client = destination
                job.save(staff=staff, update_fields=["client"])
                jobs_moved += 1

            crm_counts = _move_client_contacts_and_methods(source, destination)
            counts = {
                "jobs": jobs_moved,
                "contacts": crm_counts["contacts"],
                "contact_methods": crm_counts["contact_methods"],
                "phone_calls": crm_counts["phone_calls"],
                "invoices": Invoice.objects.filter(client=source).update(
                    client=destination
                ),
                "bills": Bill.objects.filter(client=source).update(client=destination),
                "credit_notes": CreditNote.objects.filter(client=source).update(
                    client=destination
                ),
                "quotes": Quote.objects.filter(client=source).update(
                    client=destination
                ),
                "purchase_orders": PurchaseOrder.objects.filter(supplier=source).update(
                    supplier=destination
                ),
                "supplier_products": SupplierProduct.objects.filter(
                    supplier=source
                ).update(supplier=destination),
                "supplier_price_lists": SupplierPriceList.objects.filter(
                    supplier=source
                ).update(supplier=destination),
                "scrape_jobs": ScrapeJob.objects.filter(supplier=source).update(
                    supplier=destination
                ),
            }

        logger.info(
            "%sReassigned client %s -> %s: jobs=%d contacts=%d "
            "contact_methods=%d phone_calls=%d invoices=%d bills=%d "
            "credit_notes=%d quotes=%d purchase_orders=%d supplier_products=%d "
            "supplier_price_lists=%d scrape_jobs=%d",
            logger_prefix,
            source.id,
            destination.id,
            counts["jobs"],
            counts["contacts"],
            counts["contact_methods"],
            counts["phone_calls"],
            counts["invoices"],
            counts["bills"],
            counts["credit_notes"],
            counts["quotes"],
            counts["purchase_orders"],
            counts["supplier_products"],
            counts["supplier_price_lists"],
            counts["scrape_jobs"],
        )
        return counts

    except Exception as exc:
        persist_app_error(exc)
        raise
