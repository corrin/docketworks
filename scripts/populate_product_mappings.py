#!/usr/bin/env python
"""
Populate ProductParsingMapping from existing SupplierProduct records.

Uses the ProductParser to parse supplier products in batches with rate limiting.

Usage:
    python scripts/populate_product_mappings.py
    python scripts/populate_product_mappings.py --dry-run
    python scripts/populate_product_mappings.py --batch-size 100 --delay 3.0
    python scripts/populate_product_mappings.py --max-products 50
"""

import argparse
import logging
import os
import time
from typing import Set

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from django.db import transaction
from django.utils import timezone

from apps.quoting.models import ProductParsingMapping, SupplierProduct
from apps.quoting.services.product_parser import ProductParser

logger = logging.getLogger(__name__)


def get_processed_hashes() -> Set[str]:
    """Get set of input hashes that have already been processed."""
    return set(ProductParsingMapping.objects.values_list("input_hash", flat=True))


def get_unprocessed_products(processed_hashes: Set[str]) -> list:
    """Get list of SupplierProduct records that haven't been processed yet."""
    parser = ProductParser()
    unprocessed = []

    logging.info("Checking which products need processing...")

    all_products = SupplierProduct.objects.all()
    checked_count = 0
    for product in all_products:
        product_data = {
            "description": product.description,
            "product_name": product.product_name,
            "specifications": product.specifications,
            "item_no": product.item_no,
            "variant_id": product.variant_id,
            "variant_width": product.variant_width,
            "variant_length": product.variant_length,
            "variant_price": product.variant_price,
            "price_unit": product.price_unit,
            "supplier_name": product.supplier.name,
        }
        input_hash = parser._calculate_input_hash(product_data)

        if input_hash not in processed_hashes:
            unprocessed.append(product)

        checked_count += 1
        if checked_count % 1000 == 0:
            logging.info(
                "  Checked %d/%d products...", checked_count, all_products.count()
            )

    return unprocessed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of products to process per batch (default: 50)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Delay in seconds between API calls (default: 2.0)",
    )
    parser.add_argument(
        "--max-products",
        type=int,
        help="Maximum number of products to process",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without making API calls",
    )
    args = parser.parse_args()

    logging.info("Starting ProductParsingMapping population")
    logging.info("Batch size: %d", args.batch_size)
    logging.info("Delay between batches: %.1fs", args.delay)
    if args.max_products:
        logging.info("Max products to process: %d", args.max_products)
    if args.dry_run:
        logging.info("DRY RUN MODE - No API calls will be made")

    total_supplier_products = SupplierProduct.objects.count()
    existing_mappings = ProductParsingMapping.objects.count()

    logging.info("Total SupplierProduct records: %d", total_supplier_products)
    logging.info("Existing ProductParsingMapping records: %d", existing_mappings)

    processed_hashes = get_processed_hashes()
    unprocessed_products = get_unprocessed_products(processed_hashes)

    if args.max_products:
        unprocessed_products = unprocessed_products[: args.max_products]

    total_to_process = len(unprocessed_products)
    logging.info("Products needing processing: %d", total_to_process)

    if total_to_process == 0:
        logging.info("All products already processed!")
        return

    if args.dry_run:
        logging.info("Dry run complete. Products that would be processed:")
        for i, product in enumerate(unprocessed_products[:10]):
            logging.info("  %d. %s...", i + 1, product.product_name[:50])
        if total_to_process > 10:
            logging.info("  ... and %d more", total_to_process - 10)
        return

    product_parser = ProductParser()

    processed_count = 0
    failed_count = 0
    start_time = timezone.now()

    for i in range(0, total_to_process, args.batch_size):
        batch = unprocessed_products[i : i + args.batch_size]
        batch_num = (i // args.batch_size) + 1
        total_batches = (total_to_process + args.batch_size - 1) // args.batch_size

        logging.info(
            "Processing batch %d/%d (%d products)...",
            batch_num,
            total_batches,
            len(batch),
        )

        product_data_list = []
        for product in batch:
            product_data_list.append(
                {
                    "description": product.description,
                    "product_name": product.product_name,
                    "specifications": product.specifications,
                    "item_no": product.item_no,
                    "variant_id": product.variant_id,
                    "variant_width": product.variant_width,
                    "variant_length": product.variant_length,
                    "variant_price": product.variant_price,
                    "price_unit": product.price_unit,
                    "supplier_name": product.supplier.name,
                }
            )

        try:
            with transaction.atomic():
                results = product_parser.parse_products_batch(product_data_list)
                successful_results = [r for r in results if r and len(r) == 2]
                processed_count += len(successful_results)
                failed_count += len(batch) - len(successful_results)

                logging.info(
                    "  Batch %d complete: %d/%d successful",
                    batch_num,
                    len(successful_results),
                    len(batch),
                )

        except Exception as e:
            failed_count += len(batch)
            logging.error("  Batch %d failed: %s", batch_num, e)

        total_processed_so_far = processed_count + failed_count
        progress_pct = (total_processed_so_far / total_to_process) * 100
        elapsed = timezone.now() - start_time

        if total_processed_so_far > 0:
            estimated_total_time = elapsed * (total_to_process / total_processed_so_far)
            remaining_time = estimated_total_time - elapsed
            logging.info(
                "Progress: %d/%d (%.1f%%) - ETA: %s",
                total_processed_so_far,
                total_to_process,
                progress_pct,
                remaining_time,
            )

        if i + args.batch_size < total_to_process:
            logging.info("  Waiting %.1fs before next batch...", args.delay)
            time.sleep(args.delay)

    logging.info("=== FINAL RESULTS ===")
    logging.info("Total products processed: %d", processed_count)
    logging.info("Total products failed: %d", failed_count)
    logging.info("Success rate: %.1f%%", processed_count / total_to_process * 100)
    logging.info("Total time: %s", timezone.now() - start_time)

    new_mapping_count = ProductParsingMapping.objects.count()
    logging.info(
        "ProductParsingMapping records: %d -> %d", existing_mappings, new_mapping_count
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
