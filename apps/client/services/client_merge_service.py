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

from apps.client.models import Client
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger("xero")


def reassign_client_fk_records(
    source: Client,
    destination: Client,
    *,
    logger_prefix: str = "",
) -> dict[str, int]:
    """
    Move every client-referencing FK record from ``source`` to ``destination``.

    Returns a dict of per-model rowcounts, e.g. ``{"jobs": 3, ...}``.

    Job records are iterated and saved so SimpleHistory entries are generated
    (Job is the only affected model with an audit trail). All other tables
    use bulk ``.update()``.

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
                job.save(update_fields=["client"])
                jobs_moved += 1

            counts = {
                "jobs": jobs_moved,
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
            "%sReassigned client %s -> %s: jobs=%d invoices=%d bills=%d "
            "credit_notes=%d quotes=%d purchase_orders=%d supplier_products=%d "
            "supplier_price_lists=%d scrape_jobs=%d",
            logger_prefix,
            source.id,
            destination.id,
            counts["jobs"],
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
