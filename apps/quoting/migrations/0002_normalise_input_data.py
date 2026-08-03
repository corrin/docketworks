"""Normalise ProductParsingMapping.input_data to the one canonical dict shape.

v1 wrote this JSONField two ways from the same file: ``_save_mapping`` stored a
dict keyed ``product_name``/``description``/``specifications``, while
``create_mapping_record`` stored a *JSON string* keyed ``input_product_name``/
``input_description``/``input_specifications`` — double-encoded, so the column
holds a JSON string rather than a JSON object. The 2026-08-01 production
restore carries both: 644 object rows and 559 string rows.

v2 writes one shape and the API declares ``input_data: dict``, so the string
rows fail response validation and 500 the product-mappings listing. ADR 0015
says fix the data rather than soften the consumer, so this migration decodes
the string rows and maps the ``input_*`` keys onto the canonical ones. Rows
that are already dicts are untouched; anything undecodable is left alone and
logged, since inventing a shape for it would be the fallback ADR 0015 forbids.

Found by running the app against migrated production data (the endpoint 500'd),
not by any test — the synthetic fixtures only ever produced the good shape.
"""

import json
import logging

from django.db import migrations

logger = logging.getLogger(__name__)

#: v1's create_mapping_record keys -> the canonical keys v2 reads and writes.
_LEGACY_KEY_MAP = {
    "input_product_name": "product_name",
    "input_description": "description",
    "input_specifications": "specifications",
}


def normalise_input_data(apps, schema_editor):
    """Decode double-encoded input_data rows and rename their legacy keys."""
    ProductParsingMapping = apps.get_model("quoting", "ProductParsingMapping")
    fixed = 0
    skipped = 0

    for mapping in ProductParsingMapping.objects.exclude(input_data=None).iterator():
        raw = mapping.input_data
        if isinstance(raw, dict):
            continue  # already canonical

        if not isinstance(raw, str):
            skipped += 1
            continue

        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            skipped += 1
            logger.warning("ProductParsingMapping %s: input_data is not decodable", mapping.pk)
            continue

        if not isinstance(decoded, dict):
            skipped += 1
            continue

        mapping.input_data = {_LEGACY_KEY_MAP.get(key, key): value for key, value in decoded.items()}
        mapping.save(update_fields=["input_data"])
        fixed += 1

    logger.info("Normalised %s input_data rows (%s left as-is)", fixed, skipped)


def reverse_noop(apps, schema_editor):
    """Irreversible by design: the legacy shape is the defect being removed."""


class Migration(migrations.Migration):
    dependencies = [
        ("quoting", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(normalise_input_data, reverse_noop),
    ]
