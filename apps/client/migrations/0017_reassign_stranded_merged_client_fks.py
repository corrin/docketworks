"""
Backfill migration: move stranded FK records off merged-from clients.

Before this migration, Xero sync correctly set ``Client.merged_into`` when a
contact was merged in Xero, but FK-referencing rows (Jobs, Invoices, Bills,
Credit Notes, Quotes, Purchase Orders, Supplier Products, Supplier Price
Lists, Scrape Jobs) stayed attached to the merged-from client. A query like
"all jobs for Client B" missed the absorbed history from the merged-from
Client A.

The service ``apps.client.services.client_merge_service`` now reassigns FKs
at merge-detection time. This migration fixes the historical backlog.

Jobs are moved via bulk ``.update()`` rather than iterate-and-save, so they
do not generate SimpleHistory audit entries. The trade-off is deliberate:
the stranded state was a bug, not a legitimate historical position, so an
audit trail of "moved during repair" adds noise without value.

Reverse is a no-op. The reassigned state is correct; rolling back would
re-create the bug.
"""

import logging

from django.db import migrations, models

logger = logging.getLogger("xero")


def _walk_merge_chain(client, Client):
    """
    Follow ``merged_into`` from ``client`` until we reach a client whose
    ``merged_into_id`` is NULL, or we detect a cycle.

    Returns the terminal client (may be ``client`` itself if the chain loops
    back before reaching a non-merged node).

    Historical models do not carry the ``get_final_client`` method, so we
    re-implement the walk here with the same cycle guard used at
    ``apps/client/models.py``.
    """
    seen = {client.id}
    current = client
    while current.merged_into_id is not None:
        nxt = Client.objects.filter(pk=current.merged_into_id).first()
        if nxt is None:
            break
        if nxt.id in seen:
            logger.warning(
                "Migration 0017: circular merge chain detected for client %s",
                client.id,
            )
            break
        seen.add(nxt.id)
        current = nxt
    return current


def reassign_stranded_fks(apps, schema_editor):
    Client = apps.get_model("client", "Client")
    Job = apps.get_model("job", "Job")
    Invoice = apps.get_model("accounting", "Invoice")
    Bill = apps.get_model("accounting", "Bill")
    CreditNote = apps.get_model("accounting", "CreditNote")
    Quote = apps.get_model("accounting", "Quote")
    PurchaseOrder = apps.get_model("purchasing", "PurchaseOrder")
    SupplierProduct = apps.get_model("quoting", "SupplierProduct")
    SupplierPriceList = apps.get_model("quoting", "SupplierPriceList")
    ScrapeJob = apps.get_model("quoting", "ScrapeJob")

    merged_clients = Client.objects.filter(merged_into__isnull=False)
    client_count = merged_clients.count()

    totals = {
        "clients_processed": 0,
        "clients_skipped_no_destination": 0,
        "jobs": 0,
        "invoices": 0,
        "bills": 0,
        "credit_notes": 0,
        "quotes": 0,
        "purchase_orders": 0,
        "supplier_products": 0,
        "supplier_price_lists": 0,
        "scrape_jobs": 0,
    }

    for client in merged_clients:
        destination = _walk_merge_chain(client, Client)
        if destination.id == client.id:
            totals["clients_skipped_no_destination"] += 1
            logger.warning(
                "Migration 0017: chain-walk for client %s returned self; "
                "skipping (likely circular or missing destination)",
                client.id,
            )
            continue

        # Bind to the base QuerySet.update() so this works regardless of
        # which Job manager is attached: the live JobQuerySet raises on
        # tracked-field updates, and the historical-registry manager has no
        # `untracked_update` escape hatch. The base method does the bulk
        # write either way.
        totals["jobs"] += models.QuerySet.update(
            Job.objects.filter(client=client), client=destination
        )
        totals["invoices"] += Invoice.objects.filter(client=client).update(
            client=destination
        )
        totals["bills"] += Bill.objects.filter(client=client).update(client=destination)
        totals["credit_notes"] += CreditNote.objects.filter(client=client).update(
            client=destination
        )
        totals["quotes"] += Quote.objects.filter(client=client).update(
            client=destination
        )
        totals["purchase_orders"] += PurchaseOrder.objects.filter(
            supplier=client
        ).update(supplier=destination)
        totals["supplier_products"] += SupplierProduct.objects.filter(
            supplier=client
        ).update(supplier=destination)
        totals["supplier_price_lists"] += SupplierPriceList.objects.filter(
            supplier=client
        ).update(supplier=destination)
        totals["scrape_jobs"] += ScrapeJob.objects.filter(supplier=client).update(
            supplier=destination
        )
        totals["clients_processed"] += 1

    logger.info(
        "Migration 0017: reassigned stranded FKs across %d merged clients "
        "(skipped %d); totals: %s",
        totals["clients_processed"],
        totals["clients_skipped_no_destination"],
        {
            k: v
            for k, v in totals.items()
            if k
            not in (
                "clients_processed",
                "clients_skipped_no_destination",
            )
        },
    )
    logger.info("Migration 0017: scanned %d merged clients total", client_count)


class Migration(migrations.Migration):

    dependencies = [
        ("client", "0016_alter_client_table_alter_clientcontact_table_and_more"),
        ("job", "0074_jobdeltarejection_resolved_and_more"),
        ("accounting", "0006_alter_bill_table_alter_billlineitem_table_and_more"),
        ("purchasing", "0029_alter_purchaseorder_table_and_more"),
        ("quoting", "0018_mark_404_products_as_discontinued"),
    ]

    operations = [
        migrations.RunPython(
            reassign_stranded_fks,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
