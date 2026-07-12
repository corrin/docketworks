#!/usr/bin/env python
"""
Analyze company/person links for duplicate and empty person names.

Usage:
    python scripts/analyze_company_people.py
    python scripts/analyze_company_people.py --verbose
"""

import argparse
import logging
import os
from uuid import UUID

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from django.db.models import Count, Q

from apps.company.models import Company, CompanyPersonLink
from apps.job.models import Job


def analyze_empty_names(verbose: bool) -> int:
    """Analyze linked Person records with empty/whitespace names."""
    logging.info("1. EMPTY PERSON NAME ANALYSIS")

    empty_name_links = CompanyPersonLink.objects.filter(
        Q(person__name="") | Q(person__name__regex=r"^\s+$")
    )
    count = empty_name_links.count()

    logging.info("Total company/person links with empty person names: %d", count)

    if count > 0 and verbose:
        logging.info("Sample records (first 10):")
        for link in empty_name_links.select_related("company", "person")[:10]:
            logging.info("  - Link ID: %s", link.id)
            logging.info("    Person ID: %s", link.person_id)
            logging.info("    Company: %s", link.company.name)
            logging.info(
                "    Name: '%s' (length: %d)", link.person.name, len(link.person.name)
            )
            logging.info("    Email: %s", link.person.email or "None")

            job_count = Job.objects.filter(
                company=link.company,
                person=link.person,
            ).count()
            if job_count > 0:
                logging.warning("    Referenced by %d jobs at this company", job_count)

    return count


def flagged_link_ids() -> set[UUID]:
    """Return company/person link IDs that need manual review."""
    empty_name_ids = set(
        CompanyPersonLink.objects.filter(
            Q(person__name="") | Q(person__name__regex=r"^\s+$")
        ).values_list("id", flat=True)
    )

    duplicate_groups = (
        CompanyPersonLink.objects.values("company", "person__name")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
    )
    duplicate_ids: set[UUID] = set()
    for duplicate in duplicate_groups:
        duplicate_ids.update(
            CompanyPersonLink.objects.filter(
                company_id=duplicate["company"],
                person__name=duplicate["person__name"],
            ).values_list("id", flat=True)
        )

    return empty_name_ids | duplicate_ids


def analyze_duplicates(verbose: bool) -> int:
    """Analyze duplicate person names linked to the same company."""
    logging.info("2. DUPLICATE PERSON NAME ANALYSIS")

    duplicates = (
        CompanyPersonLink.objects.values("company", "person__name")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
        .order_by("-count")
    )

    total_duplicate_groups = duplicates.count()
    logging.info(
        "Total duplicate (company, person name) combinations: %d",
        total_duplicate_groups,
    )

    if total_duplicate_groups == 0:
        logging.info("No duplicates found")
        return 0

    total_duplicate_links = sum(duplicate["count"] - 1 for duplicate in duplicates)
    logging.info("Total duplicate links to review: %d", total_duplicate_links)

    if verbose:
        logging.info("Top 10 duplicate groups:")
        for index, duplicate in enumerate(duplicates[:10], 1):
            company = Company.objects.get(id=duplicate["company"])
            person_name = duplicate["person__name"]
            logging.info(
                "%d. Company: %s - Person: '%s' - %d links",
                index,
                company.name,
                person_name,
                duplicate["count"],
            )

            links = (
                CompanyPersonLink.objects.select_related("person")
                .filter(company_id=duplicate["company"], person__name=person_name)
                .order_by("-created_at")
            )

            for link in links[:5]:
                job_count = Job.objects.filter(
                    company_id=duplicate["company"],
                    person=link.person,
                ).count()
                jobs_text = f" ({job_count} jobs)" if job_count > 0 else ""
                logging.info(
                    "     Link ID: %s  Person ID: %s  Email: %s  Created: %s%s",
                    link.id,
                    link.person_id,
                    link.person.email or "None",
                    link.created_at,
                    jobs_text,
                )

    return total_duplicate_links


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed information about each duplicate group",
    )
    args = parser.parse_args()

    logging.info("Company/Person Link State Analysis")
    empty_count = analyze_empty_names(args.verbose)
    duplicate_count = analyze_duplicates(args.verbose)

    logging.info("--- SUMMARY ---")
    logging.info("Empty/whitespace person-name links: %d", empty_count)
    logging.info("Duplicate company/person-name links to review: %d", duplicate_count)
    logging.info("Total company/person links: %d", CompanyPersonLink.objects.count())
    logging.info(
        "Unique company/person links flagged for review: %d",
        len(flagged_link_ids()),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
