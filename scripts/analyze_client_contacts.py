#!/usr/bin/env python
"""
Analyze ClientContact records for duplicates and empty names.

Usage:
    python scripts/analyze_client_contacts.py
    python scripts/analyze_client_contacts.py --verbose
"""

import argparse
import logging
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from django.db.models import Count

from apps.client.models import Client, ClientContact
from apps.job.models import Job


def analyze_empty_names(verbose: bool) -> None:
    """Analyze ClientContact records with empty/whitespace names."""
    logging.info("1. EMPTY NAME ANALYSIS")

    empty_name_contacts = ClientContact.objects.filter(
        name=""
    ) | ClientContact.objects.filter(name__regex=r"^\s+$")
    count = empty_name_contacts.count()

    logging.info("Total contacts with empty/whitespace names: %d", count)

    if count > 0 and verbose:
        logging.info("Sample records (first 10):")
        for contact in empty_name_contacts[:10]:
            logging.info("  - ID: %s", contact.id)
            logging.info("    Client: %s", contact.client.name)
            logging.info("    Name: '%s' (length: %d)", contact.name, len(contact.name))
            logging.info("    Email: %s", contact.email or "None")

            job_count = Job.objects.filter(contact=contact).count()
            if job_count > 0:
                logging.warning("    Referenced by %d jobs", job_count)


def analyze_duplicates(verbose: bool) -> None:
    """Analyze duplicate ClientContact records (same client + name)."""
    logging.info("2. DUPLICATE CONTACT ANALYSIS")

    duplicates = (
        ClientContact.objects.values("client", "name")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
        .order_by("-count")
    )

    total_duplicate_groups = duplicates.count()
    logging.info(
        "Total duplicate (client, name) combinations: %d", total_duplicate_groups
    )

    if total_duplicate_groups == 0:
        logging.info("No duplicates found")
        return

    total_duplicate_records = sum(d["count"] - 1 for d in duplicates)
    logging.info("Total duplicate records to be merged: %d", total_duplicate_records)

    if verbose:
        logging.info("Top 10 duplicate groups:")
        for i, dup in enumerate(duplicates[:10], 1):
            client = Client.objects.get(id=dup["client"])
            logging.info(
                "%d. Client: %s — Contact: '%s' — %d copies",
                i,
                client.name,
                dup["name"],
                dup["count"],
            )

            contacts = ClientContact.objects.filter(
                client_id=dup["client"], name=dup["name"]
            ).order_by("-created_at")

            for contact in contacts[:5]:
                job_count = Job.objects.filter(contact=contact).count()
                jobs_str = f" ({job_count} jobs)" if job_count > 0 else ""
                logging.info(
                    "     ID: %s  Email: %s  Created: %s%s",
                    contact.id,
                    contact.email or "None",
                    contact.created_at,
                    jobs_str,
                )

    # Summary
    empty_count = (
        ClientContact.objects.filter(name="")
        | ClientContact.objects.filter(name__regex=r"^\s+$")
    ).count()

    logging.info("--- SUMMARY ---")
    logging.info("Empty/whitespace name contacts: %d", empty_count)
    logging.info("Duplicate (client, name) combinations: %d", total_duplicate_groups)
    logging.info("Total duplicate records to be removed: %d", total_duplicate_records)
    logging.info(
        "Total records after cleanup: %d",
        ClientContact.objects.count() - empty_count - total_duplicate_records,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed information about each duplicate group",
    )
    args = parser.parse_args()

    logging.info("ClientContact State Analysis")
    analyze_empty_names(args.verbose)
    analyze_duplicates(args.verbose)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
