"""
Reassign FK records from one Company (source) to another (destination).

The Company.merged_into pointer alone leaves historical records stranded on
the merged-from row — queries filtered by the merged-into company miss the
absorbed history. This service moves the 8 company-referencing FK fields in
a single atomic block.

Callers pick the destination explicitly:
- Xero sync paths typically pass ``source.get_final_company()`` so absorbed
  history lands on the terminal company in a merge chain (A -> B -> C).
- The local dedup command passes a hand-picked primary company.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.company.models import Company, CompanyPersonLink, ContactMethod
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger("xero")


def _move_company_contact_methods(source: Company, destination: Company) -> int:
    """Move only company-owned methods during a company merge."""

    source_queryset = ContactMethod.objects.filter(company=source)
    destination_queryset = ContactMethod.objects.filter(company=destination)

    affected = 0

    # Drop source methods the destination already owns (same method_type +
    # normalized_value), respecting the per-owner unique constraints.
    destination_pairs = set(
        destination_queryset.values_list("method_type", "normalized_value")
    )
    duplicate_ids = [
        method_id
        for method_id, method_type, normalized_value in source_queryset.values_list(
            "id", "method_type", "normalized_value"
        )
        if (method_type, normalized_value) in destination_pairs
    ]
    if duplicate_ids:
        ContactMethod.objects.filter(id__in=duplicate_ids).delete()
        affected += len(duplicate_ids)

    # A moving primary method wins over the destination's existing primary of
    # the same method_type (mirrors ContactMethod.save()'s demotion),
    # keeping the partial unique constraints on (owner, method_type, is_primary)
    # satisfied.
    moving_primary_types = list(
        source_queryset.filter(is_primary=True).values_list("method_type", flat=True)
    )
    if moving_primary_types:
        destination_queryset.filter(
            method_type__in=moving_primary_types,
            is_primary=True,
        ).update(is_primary=False)

    # queryset.update() bypasses ContactMethod.save()'s
    # one-number-one-company guard DELIBERATELY: a merge moves ALL of the
    # source's methods to the destination, so any cross-company sharing the
    # guard would flag (e.g. the company-level/contact-level twins migration
    # 0023 created) already existed before the merge — the move creates no
    # new conflicting ownership.
    affected += source_queryset.update(
        company=destination,
        updated_at=timezone.now(),
    )
    return affected


def _move_company_contacts_and_methods(
    source: Company, destination: Company
) -> dict[str, int]:
    """Move CRM contact ownership before the source company is deleted."""

    from apps.crm.models import PhoneCallRecord

    counts = {
        "contacts": 0,
        "contact_methods": 0,
        "phone_calls": 0,
    }

    counts["contact_methods"] += _move_company_contact_methods(source, destination)

    destination_links_by_person = {
        existing.person_id: existing
        for existing in CompanyPersonLink.objects.filter(company=destination)
    }
    for link in CompanyPersonLink.objects.filter(company=source).iterator():
        destination_link = destination_links_by_person.get(link.person_id)
        if destination_link is None:
            if (
                link.xero_name is not None
                and CompanyPersonLink.objects.filter(
                    company=destination,
                    xero_name=link.xero_name,
                ).exists()
            ):
                link.xero_name = None
            link.company = destination
            link.save(update_fields=["company", "xero_name", "updated_at"])
            destination_links_by_person[link.person_id] = link
        else:
            counts["phone_calls"] += PhoneCallRecord.objects.filter(
                person=link.person,
                company=source,
            ).update(
                company=destination,
            )
            link.delete()

        counts["contacts"] += 1

    counts["phone_calls"] += PhoneCallRecord.objects.filter(company=source).update(
        company=destination
    )
    return counts


def reassign_company_fk_records(
    source: Company,
    destination: Company,
    staff,
    *,
    logger_prefix: str = "",
) -> dict[str, int]:
    """
    Move every company-referencing FK record from ``source`` to ``destination``.

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
            f"reassign_company_fk_records: source and destination are the "
            f"same company ({source.id}); refusing to run"
        )

    # Late imports to avoid circular-import at Django app-loading time.
    from apps.accounting.models import Bill, CreditNote, Invoice, Quote
    from apps.job.models import Job
    from apps.purchasing.models import PurchaseOrder
    from apps.quoting.models import ScrapeJob, SupplierPriceList, SupplierProduct

    try:
        with transaction.atomic():
            jobs_moved = 0
            for job in Job.objects.filter(company=source):
                job.company = destination
                job.save(staff=staff, update_fields=["company"])
                jobs_moved += 1

            crm_counts = _move_company_contacts_and_methods(source, destination)
            counts = {
                "jobs": jobs_moved,
                "contacts": crm_counts["contacts"],
                "contact_methods": crm_counts["contact_methods"],
                "phone_calls": crm_counts["phone_calls"],
                "invoices": Invoice.objects.filter(company=source).update(
                    company=destination
                ),
                "bills": Bill.objects.filter(company=source).update(
                    company=destination
                ),
                "credit_notes": CreditNote.objects.filter(company=source).update(
                    company=destination
                ),
                "quotes": Quote.objects.filter(company=source).update(
                    company=destination
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
            "%sReassigned company %s -> %s: jobs=%d contacts=%d "
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
