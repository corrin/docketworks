#!/usr/bin/env python
"""Backfill geocoding for SupplierPickupAddress rows missing lat/lng.

Reuses apps/core/geocoding.py — the one Google lookup in the codebase, the
same one the address picker calls — rather than carrying a second client
(ADR 0039). Nothing geocodes on write: a row gets coordinates when a person
picks a candidate in the address modal, and this sweep is for the rows that
predate that, chiefly the addresses mirrored in from Xero.

Usage:
    uv run python -m scripts.ops.geocode_addresses              # missing lat/lng only
    uv run python -m scripts.ops.geocode_addresses --dry-run    # show what would be geocoded
    uv run python -m scripts.ops.geocode_addresses --limit 10   # only process 10 addresses
    uv run python -m scripts.ops.geocode_addresses --all        # re-geocode all active addresses
"""

import argparse
import logging
import sys
import time

from scripts.bootstrap import setup_django

setup_django()

from apps.company.models import SupplierPickupAddress  # noqa: E402 -- needs django.setup()
from apps.core.geocoding import (  # noqa: E402
    GeocodingError,
    GeocodingNotConfiguredError,
    get_api_key,
    search_places,
)

logger = logging.getLogger(__name__)

# Pause between Google API calls so a large backfill stays under rate limits.
API_PAUSE_SECONDS = 0.2


def build_freetext_address(address: SupplierPickupAddress) -> str:
    """Join the populated address components into one freetext string."""
    parts = [
        address.street,
        address.suburb,
        address.city,
        address.postal_code,
        address.country,
    ]
    return ", ".join(p for p in parts if p)


def apply_result(address: SupplierPickupAddress, freetext: str, api_key: str) -> bool:
    """Geocode one address and save the result; returns True on success."""
    # Best match only: a sweep has no operator to pick from a list, so it
    # takes what a person would have been offered first and nothing else.
    candidates = search_places(freetext, limit=1, api_key=api_key)
    if not candidates:
        logger.warning("  -> No result returned")
        return False
    result = candidates[0]

    address.latitude = result.latitude
    address.longitude = result.longitude
    address.google_place_id = result.place_id

    # Fill blanks only: the operator-entered components stay authoritative.
    if not address.suburb and result.suburb:
        address.suburb = result.suburb
    if not address.postal_code and result.postal_code:
        address.postal_code = result.postal_code
    # Newly reachable: the region was never returned by the product this
    # swept with before, so every row it has already visited has a blank one.
    if not address.state and result.region:
        address.state = result.region

    address.save()
    logger.info("  -> %s, %s", result.latitude, result.longitude)
    return True


def parse_args() -> argparse.Namespace:
    """Parse the sweep's command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be geocoded without making changes",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of addresses to process",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Re-geocode all active addresses, not just those missing lat/lng",
    )
    return parser.parse_args()


def select_addresses(args: argparse.Namespace) -> list[SupplierPickupAddress]:
    """Build the sweep's worklist from the --all/--limit options."""
    if args.all:
        queryset = SupplierPickupAddress.objects.filter(is_active=True)
    else:
        queryset = SupplierPickupAddress.objects.filter(is_active=True, latitude__isnull=True)

    if args.limit:
        queryset = queryset[: args.limit]
    return list(queryset)


def sweep(addresses: list[SupplierPickupAddress], api_key: str, dry_run: bool) -> tuple[int, int]:
    """Geocode each address in turn; returns (success_count, error_count)."""
    total = len(addresses)
    success_count = 0
    error_count = 0

    for i, address in enumerate(addresses, 1):
        freetext = build_freetext_address(address)
        logger.info("[%d/%d] %s", i, total, address.company.name)
        logger.info("  Input: %s", freetext)

        if dry_run:
            continue

        # Only GeocodingError is survivable per-address (a bad address must
        # not stop the sweep); anything else is a real bug and propagates.
        try:
            if apply_result(address, freetext, api_key):
                success_count += 1
            else:
                error_count += 1
        except GeocodingError as exc:
            # deliberate-swallow: per-address API refusal — count it, report
            # it, and keep sweeping the remaining addresses.
            logger.error("  -> Error: %s", exc)
            error_count += 1

        time.sleep(API_PAUSE_SECONDS)

    return success_count, error_count


def main() -> None:
    args = parse_args()

    try:
        api_key = get_api_key()
    except GeocodingNotConfiguredError as exc:
        # deliberate-swallow: converted to a clean exit — a missing API key is
        # the operator's config problem, not a stack trace.
        logger.error(str(exc))
        sys.exit(1)

    addresses = select_addresses(args)
    if not addresses:
        logger.info("No addresses to geocode")
        return

    logger.info("Found %d addresses to geocode", len(addresses))
    if args.dry_run:
        logger.info("DRY RUN - no changes will be made")

    success_count, error_count = sweep(addresses, api_key, args.dry_run)

    if not args.dry_run:
        logger.info("Successfully geocoded: %d", success_count)
        if error_count:
            logger.error("Errors: %d", error_count)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
