"""The input_data normalisation rule, factored out of 0002 so it can be tested.

It lives inside ``migrations/`` rather than in the app: a migration must not
import app code, which is free to change underneath a frozen historical record,
but a helper dedicated to one migration is as frozen as the migration itself.

``apps/quoting/tests/test_input_data_normalisation.py`` is the test net.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

#: v1's create_mapping_record keys -> the canonical keys v2 reads and writes.
LEGACY_KEY_MAP = {
    "input_product_name": "product_name",
    "input_description": "description",
    "input_specifications": "specifications",
}


def normalise_rows(model: Any) -> int:
    """Decode double-encoded input_data rows, renaming legacy keys. Returns the count fixed.

    Raises RuntimeError, naming the primary keys, if ANY row cannot be
    normalised — and writes nothing at all in that case. Skipping the row would
    report success while leaving something that 500s the product-mappings
    listing (the exact defect this exists to remove), and inventing a shape for
    it would be the read-side fallback ADR 0015 forbids.

    Every row is classified before any row is written, so a refusal leaves the
    table exactly as it was. RunPython would roll back anyway; not depending on
    that keeps the guarantee true if this is ever called outside a migration,
    and lets the error report the whole problem rather than the first row of it.
    """
    pending: list[Any] = []
    unfixable: list[tuple[str, str]] = []

    for mapping in model.objects.iterator():
        raw = mapping.input_data
        if isinstance(raw, dict):
            continue  # already canonical

        if not isinstance(raw, str):
            unfixable.append(
                (mapping.pk, f"expected dict or JSON string, found {type(raw).__name__}")
            )
            continue

        try:
            decoded = json.loads(raw)
        except ValueError as exc:
            unfixable.append((mapping.pk, f"input_data is not valid JSON: {exc}"))
            continue

        if not isinstance(decoded, dict):
            unfixable.append(
                (mapping.pk, f"decoded to {type(decoded).__name__}, expected an object")
            )
            continue

        mapping.input_data = {LEGACY_KEY_MAP.get(key, key): value for key, value in decoded.items()}
        pending.append(mapping)

    if unfixable:
        detail = "; ".join(f"pk={pk}: {why}" for pk, why in unfixable)
        raise RuntimeError(
            f"Cannot normalise ProductParsingMapping.input_data for {len(unfixable)} row(s), so "
            f"nothing was written ({len(pending)} other row(s) would have been normalised). These "
            f"rows would 500 the product-mappings listing, so this stops rather than reporting "
            f"success. Inspect and correct them, then re-run. Offending rows — {detail}"
        )

    model.objects.bulk_update(pending, ["input_data"], batch_size=500)
    logger.info("Normalised %s double-encoded input_data rows", len(pending))
    return len(pending)
