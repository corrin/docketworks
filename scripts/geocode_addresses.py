#!/usr/bin/env python
"""
Geocode SupplierPickupAddress records using Google Address Validation API.

Usage:
    python scripts/geocode_addresses.py              # Geocode addresses missing lat/lng
    python scripts/geocode_addresses.py --dry-run    # Show what would be geocoded
    python scripts/geocode_addresses.py --limit 10   # Only process 10 addresses
    python scripts/geocode_addresses.py --all        # Re-geocode all addresses
"""

import argparse
import logging
import os
import sys
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from apps.client.models import SupplierPickupAddress
from apps.client.services.geocoding_service import (
    GeocodingError,
    GeocodingNotConfiguredError,
    geocode_address,
    get_api_key,
)

logger = logging.getLogger(__name__)


def build_freetext_address(address: SupplierPickupAddress) -> str:
    """Build a freetext address string from address components."""
    parts = [
        address.street,
        address.suburb,
        address.city,
        address.postal_code,
        address.country,
    ]
    return ", ".join(p for p in parts if p)


def main() -> None:
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
        help="Re-geocode all addresses, not just those missing lat/lng",
    )
    args = parser.parse_args()

    # Check API key upfront
    try:
        api_key = get_api_key()
    except GeocodingNotConfiguredError as exc:
        logging.error(str(exc))
        sys.exit(1)

    # Build queryset
    if args.all:
        queryset = SupplierPickupAddress.objects.filter(is_active=True)
    else:
        queryset = SupplierPickupAddress.objects.filter(
            is_active=True,
            latitude__isnull=True,
        )

    if args.limit:
        queryset = queryset[: args.limit]

    addresses = list(queryset)
    total = len(addresses)

    if total == 0:
        logging.info("No addresses to geocode")
        return

    logging.info("Found %d addresses to geocode", total)
    if args.dry_run:
        logging.info("DRY RUN - no changes will be made")

    success_count = 0
    error_count = 0

    for i, address in enumerate(addresses, 1):
        freetext = build_freetext_address(address)
        logging.info("[%d/%d] %s", i, total, address.client.name)
        logging.info("  Input: %s", freetext)

        if args.dry_run:
            continue

        try:
            result = geocode_address(freetext, api_key)
            if result:
                address.latitude = result.latitude
                address.longitude = result.longitude
                address.google_place_id = result.google_place_id

                if not address.suburb and result.suburb:
                    address.suburb = result.suburb
                if not address.postal_code and result.postal_code:
                    address.postal_code = result.postal_code

                address.save()
                logging.info("  -> %s, %s", result.latitude, result.longitude)
                success_count += 1
            else:
                logging.warning("  -> No result returned")
                error_count += 1

            # Rate limiting
            time.sleep(0.2)

        except GeocodingError as exc:
            logging.error("  -> Error: %s", exc)
            error_count += 1
        except Exception as exc:
            logging.error("  -> Unexpected error: %s", exc)
            error_count += 1
            logger.exception("Failed to geocode address %s", address.id)

    if not args.dry_run:
        logging.info("Successfully geocoded: %d", success_count)
        if error_count:
            logging.error("Errors: %d", error_count)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
