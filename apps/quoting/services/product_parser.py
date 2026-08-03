"""LLM product parsing: supplier product text → inventory fields, memoised forever.

Ported from v1 ``apps/quoting/services/product_parser.py`` (a ``ProductParser``
class) and ``apps/quoting/utils.py`` (the two hash helpers, whose only callers
were this parser). v2 keeps them together because they are one concept: the hash
IS the mapping's identity.

The design is v1's and unchanged: every distinct product description is parsed
by the LLM at most once, and the result is stored forever as a
``ProductParsingMapping`` keyed by the SHA-256 of that description. Re-parsing
the same text therefore always yields the same structured output, and an
operator's manual correction (``/api/purchasing/product-mappings/{id}/validate/``)
sticks.

Divergences collapsed while porting (ADR 0039) — all three were siblings inside
v1's own file:

1. ``input_data`` shape. ``_save_mapping`` wrote a **dict** keyed
   ``product_name``/``description``/``specifications``; ``create_mapping_record``
   wrote a **JSON string** keyed ``input_product_name``/``input_description``/
   ``input_specifications``; ``populate_all_mappings_with_llm`` then read both
   key sets with ``or`` fallbacks. v2 writes one shape — a dict with the plain
   keys — and reads only that. The field is exposed on the wire as
   ``ProductMapping.input_data: dict``, which the JSON-string branch broke.
   Migrating a v1 database needs a one-time fix-up of
   ``quoting_productparsingmapping.input_data`` (see the port report).
2. Mapping → product back-flow. v1 wrote the same eight ``parsed_*`` columns in
   ``populate_all_mappings_with_llm`` AND in ``ProductMappingValidateView``
   (ported to ``apps/purchasing/services/supplier_pricing_service.py``). v2 has
   one ``apply_mapping_to_products``; purchasing calls it. The union of the two
   v1 bodies also stamps the parser metadata columns, which the validate path
   used to leave stale — none of them is on any wire shape.
3. Mapping → ``ParsedProduct`` hydration. v1 repeated the same ten-key dict
   literal four times (cache hit in ``parse_product``, cache hit in
   ``parse_products_batch``, and after each save). One ``_mapping_to_parsed``.

Blank-string normalisation is new and mandatory, not cosmetic: every
``mapped_*`` column carries a ``*_not_blank`` CHECK constraint, so an LLM that
answers ``""`` instead of ``null`` would raise IntegrityError on save in v1.

The LLM itself is reached only through ``apps.ai``'s gateway (ADR 0041); tests
mock that one function.
"""

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import cast

from django.db.models import Q
from django.utils import timezone

from apps.ai.services.llm_client import PARSING_PROVIDER_TYPE, chat_completion
from apps.core.errors import AppErrorContext, persist_app_error
from apps.job.enums import MetalType
from apps.quoting.models import ProductParsingMapping, SupplierProduct

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.1.0"
BATCH_SIZE = 100

#: A mapping is AUTHORITATIVE when someone has already answered for its text:
#: the parser at the CURRENT version, or an operator on the review screen.
#: Everything else is a placeholder awaiting a parse. This one predicate drives
#: both the cache lookup and the end-of-run fill's work list, so the two can
#: never disagree (ADR 0039) — and they did in v1, which is what broke the fill.
#:
#: ``parser_version`` is the marker, not v1's ``mapped_item_code__isnull``
#: (user decision 2026-08-03). It is stamped whenever the parser runs, whatever
#: the outcome, so a product the model cannot classify is "parsed, no item code
#: found" and is left alone; v1 re-parsed those rows every single week forever.
#: Matching the CURRENT version (rather than merely "not null") also makes
#: bumping ``PARSER_VERSION`` the re-run lever after a prompt change: every row
#: below the new version becomes a placeholder again.
#:
#: ``is_validated`` is here because the operator wins (user decision
#: 2026-08-03). A hand-validated mapping is the most authoritative answer there
#: is, so the fill neither re-parses it nor overwrites it — silently reverting a
#: correction would make the review screen untrustworthy.
AUTHORITATIVE_MAPPING = Q(parser_version=PARSER_VERSION) | Q(is_validated=True)


@dataclass(frozen=True, slots=True)
class ProductInput:
    """The raw supplier text handed to the parser.

    v1 passed an untyped ``dict`` and read it with ``.get(..., "N/A")``
    throughout; the fields and their defaults are the same, named (ADR 0028).
    """

    product_name: str = ""
    description: str = ""
    specifications: str = ""
    item_no: str = ""
    variant_id: str = ""
    variant_width: str = ""
    variant_length: str = ""
    variant_price: Decimal | None = None
    price_unit: str = ""

    @property
    def hash_source(self) -> str:
        """The text the mapping hash is taken over: description, else name."""
        return self.description or self.product_name


@dataclass(frozen=True, slots=True)
class ParsedProduct:
    """One product's inventory fields as resolved from a mapping."""

    item_code: str | None
    description: str | None
    metal_type: str | None
    alloy: str | None
    specifics: str | None
    dimensions: str | None
    unit_cost: Decimal | None
    price_unit: str | None
    confidence: Decimal | None
    parser_version: str | None


def product_mapping_hash(text: str) -> str:
    """SHA-256 of the text a mapping is keyed by (v1 calculate_product_mapping_hash)."""
    return hashlib.sha256(text.encode()).hexdigest()


def supplier_product_mapping_hash(product: SupplierProduct) -> str:
    """Return a stored supplier product's mapping hash (v1 calculate_supplier_product_hash)."""
    return product_mapping_hash(product.description or product.product_name or "")


def blank_to_none(value: object) -> str | None:
    """Normalise an LLM string field: strip, and treat empty as unset.

    Required by the ``*_not_blank`` CHECK constraints on every ``mapped_*``
    column — an LLM answering ``""`` must persist as NULL, not raise.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def to_optional_decimal(value: object, *, max_digits: int, decimal_places: int) -> Decimal | None:
    """Coerce an LLM scalar to Decimal, or None when its column cannot hold it.

    v1 had this three times (``_save_mapping`` for confidence, again for
    unit_cost, and ``stock_parser._normalise_confidence``); one implementation.

    ``Decimal`` parses ``"NaN"``, ``"Infinity"`` and ``float('nan')`` happily,
    and psycopg stores them in ``numeric`` columns — where they then poison
    every comparison downstream (``NaN > x`` is false, ``NaN != NaN`` is true).
    A model that answers "NaN" has not given us a price, so it is None.

    Magnitude is bounded by the caller's column, not left to the database: a
    model answering ``"confidence": 95`` (percent, not 0-1) overflows
    ``numeric(3,2)`` at save time, and that ``DataError`` used to abort not
    just the row but its whole batch and every batch after it — the v1
    "0 of 7,614 enriched" outage. An unstorable number is the same non-answer
    as NaN: None.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        number = value
    else:
        try:
            number = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None
    if not number.is_finite():
        return None
    if abs(number) >= Decimal(10) ** (max_digits - decimal_places):
        return None
    return number


TRAINING_EXAMPLES = """
TRAINING EXAMPLES:

Example 1:
INPUT: Product Name: 30mm x 10mm 304 HRAP Stainless Steel Flat Bar ASTM A276
       Description: 30mm x 10mm 304 HRAP Stainless Steel Flat Bar ASTM A276
       Price: 45.20 per metre
OUTPUT: {
    "item_code": "FB-3010-304HRAP",
    "description": "30mm x 10mm 304 HRAP Stainless Steel Flat Bar",
    "metal_type": "stainless_steel",
    "alloy": "304",
    "specifics": "HRAP finish, ASTM A276",
    "dimensions": "30x10mm",
    "unit_cost": 45.20,
    "price_unit": "per metre",
    "confidence": 0.95
}

Example 2:
INPUT: Product Name: 6061 T6 Aluminium Round Bar 25mm Diameter
       Description: 6061 T6 Aluminium Round Bar 25mm Diameter
       Price: 12.50 each
OUTPUT: {
    "item_code": "RB-25-6061T6",
    "description": "25mm Diameter 6061 T6 Aluminium Round Bar",
    "metal_type": "aluminium",
    "alloy": "6061",
    "specifics": "T6 temper",
    "dimensions": "25mm diameter",
    "unit_cost": 12.50,
    "price_unit": "each",
    "confidence": 0.92
}

Example 3:
INPUT: Product Name: Mild Steel Plate 10mm x 2400mm x 1200mm
       Description: Mild Steel Plate 10mm thick
       Price: 285.00 per sheet
OUTPUT: {
    "item_code": "PL-10-MS-2400x1200",
    "description": "10mm Mild Steel Plate 2400x1200mm",
    "metal_type": "mild_steel",
    "alloy": null,
    "specifics": "Hot rolled plate",
    "dimensions": "2400x1200x10mm",
    "unit_cost": 285.00,
    "price_unit": "per sheet",
    "confidence": 0.88
}

Example 4:
INPUT: Product Name: PVC Pipe 90mm x 6m
       Description: PVC Pipe 90mm diameter 6 metre length
       Price: 45.00 each
OUTPUT: {
    "item_code": "PIPE-90-PVC-6M",
    "description": "90mm PVC Pipe 6m length",
    "metal_type": null,
    "alloy": null,
    "specifics": "PVC pipe",
    "dimensions": "90mm diameter x 6m",
    "unit_cost": 45.00,
    "price_unit": "each",
    "confidence": 0.90
}
"""


def build_parsing_prompt(products: Sequence[ProductInput]) -> str:
    """Render v1's few-shot parsing prompt for one or more products."""
    metal_types = ", ".join(choice[0] for choice in MetalType.choices)
    prompt = f"""
Parse the following supplier product data and extract structured information for
inventory management.
{TRAINING_EXAMPLES}
RULES:
- Be optimistic - make reasonable inferences from available data
- Standardize formats (dimensions, units, descriptions)
- If metal type is unclear, set to null rather than guessing
- Create meaningful item codes if none provided
- Keep descriptions concise but informative
- Ensure all dimensions follow consistent format
- Extract numeric price only (remove currency symbols, "from", etc.)
- Metal types must be one of: {metal_types} or null

OUTPUT FORMAT:
Return a JSON array with one object per input product. Each object should have
these fields:
{{
    "item_code": "Standardized item code for inventory",
    "description": "Clean, standardized description (max 255 chars)",
    "metal_type": "One of the valid metal types or null",
    "alloy": "Alloy specification or null",
    "specifics": "Specific details (max 255 chars)",
    "dimensions": "Standardized dimensions format or null",
    "unit_cost": "Numeric price value only",
    "price_unit": "Standardized unit",
    "confidence": "Your confidence (0.0 to 1.0)"
}}

INPUT DATA TO PARSE:
"""
    for index, product in enumerate(products, 1):
        prompt += f"""
Product {index}:
Product Name: {product.product_name or "N/A"}
Description: {product.description or "N/A"}
Specifications: {product.specifications or "N/A"}
Item Number: {product.item_no or "N/A"}
Variant Info: {product.variant_id or "N/A"}
Dimensions: {product.variant_width or "N/A"} x {product.variant_length or "N/A"}
Price: {product.variant_price if product.variant_price is not None else "N/A"} \
{product.price_unit or "N/A"}
"""
    return prompt


class LLMResponseError(ValueError):
    """The model's reply did not contain the JSON array the prompt asked for."""


def extract_json_objects(text: str) -> list[dict[str, object]]:
    """Pull the JSON array (or lone object) out of a model reply.

    v1 hunted for the first ``[`` or ``{`` and the last matching bracket, which
    survives the markdown fences and prose models like to add. Same scan here,
    but a miss raises instead of returning a ``success: False`` dict that every
    caller then had to re-check (ADR 0038).
    """
    stripped = text.strip()
    start = stripped.find("[")
    if start == -1:
        start = stripped.find("{")
    if start == -1:
        raise LLMResponseError("No JSON found in LLM response")
    end = stripped.rfind("]") + 1 if stripped[start] == "[" else stripped.rfind("}") + 1
    if end <= start:
        raise LLMResponseError("Unterminated JSON in LLM response")

    payload = json.loads(stripped[start:end])
    if isinstance(payload, dict):
        return [cast("dict[str, object]", payload)]
    if isinstance(payload, list):
        rows = cast("list[object]", payload)
        if not all(isinstance(row, dict) for row in rows):
            raise LLMResponseError("LLM response array contained a non-object element")
        return cast("list[dict[str, object]]", rows)
    raise LLMResponseError(f"LLM response was {type(payload).__name__}, expected array or object")


def _mapping_to_parsed(mapping: ProductParsingMapping) -> ParsedProduct:
    """Hydrate a stored mapping into the parser's result shape."""
    return ParsedProduct(
        item_code=mapping.mapped_item_code,
        description=mapping.mapped_description,
        metal_type=mapping.mapped_metal_type,
        alloy=mapping.mapped_alloy,
        specifics=mapping.mapped_specifics,
        dimensions=mapping.mapped_dimensions,
        unit_cost=mapping.mapped_unit_cost,
        price_unit=mapping.mapped_price_unit,
        confidence=mapping.parser_confidence,
        parser_version=mapping.parser_version,
    )


def _input_data(product: ProductInput) -> dict[str, object]:
    """Build the canonical ``ProductParsingMapping.input_data`` payload (see docstring)."""
    return {
        "product_name": product.product_name,
        "description": product.description,
        "specifications": product.specifications,
        "item_no": product.item_no,
        "variant_id": product.variant_id,
        "variant_width": product.variant_width,
        "variant_length": product.variant_length,
        "variant_price": str(product.variant_price) if product.variant_price is not None else None,
        "price_unit": product.price_unit,
    }


def input_from_mapping(mapping: ProductParsingMapping) -> ProductInput:
    """Rebuild the parser input from a stored mapping's ``input_data``."""
    stored = mapping.input_data
    if not isinstance(stored, dict):
        raise TypeError(
            f"ProductParsingMapping {mapping.input_hash[:8]} has input_data of type "
            f"{type(stored).__name__}; v2 stores a dict (see product_parser docstring "
            f"for the v1 data fix-up)."
        )
    data = cast("dict[str, object]", stored)

    def text(key: str) -> str:
        value = data.get(key)
        return value if isinstance(value, str) else ""

    return ProductInput(
        product_name=text("product_name"),
        description=text("description"),
        specifications=text("specifications"),
        item_no=text("item_no"),
        variant_id=text("variant_id"),
        variant_width=text("variant_width"),
        variant_length=text("variant_length"),
        # SupplierProduct.variant_price is numeric(10,2).
        variant_price=to_optional_decimal(
            data.get("variant_price"), max_digits=10, decimal_places=2
        ),
        price_unit=text("price_unit"),
    )


def _parsed_columns(
    parsed: dict[str, object], llm_response: list[dict[str, object]]
) -> dict[str, object]:
    """Return the eleven mapping columns one LLM result fills.

    THE one place the parser's output columns are listed for writing (ADR
    0039). v1 had this list three times — in ``_save_mapping``'s ``defaults``,
    in ``populate_all_mappings_with_llm``, and again in the validate view — and
    they had already drifted apart.
    """
    return {
        "mapped_item_code": blank_to_none(parsed.get("item_code")),
        "mapped_description": blank_to_none(parsed.get("description")),
        "mapped_metal_type": blank_to_none(parsed.get("metal_type")),
        "mapped_alloy": blank_to_none(parsed.get("alloy")),
        "mapped_specifics": blank_to_none(parsed.get("specifics")),
        "mapped_dimensions": blank_to_none(parsed.get("dimensions")),
        # Bounds are the columns': mapped_unit_cost numeric(10,2),
        # parser_confidence numeric(3,2).
        "mapped_unit_cost": to_optional_decimal(
            parsed.get("unit_cost"), max_digits=10, decimal_places=2
        ),
        "mapped_price_unit": blank_to_none(parsed.get("price_unit")),
        "parser_version": PARSER_VERSION,
        "parser_confidence": to_optional_decimal(
            parsed.get("confidence"), max_digits=3, decimal_places=2
        ),
        "llm_response": llm_response,
    }


def _save_mapping(
    *,
    input_hash: str,
    product: ProductInput,
    parsed: dict[str, object],
    llm_response: list[dict[str, object]],
) -> ProductParsingMapping:
    """Persist one LLM result into this hash's mapping row.

    The row may already exist: ``create_mapping_record`` RESERVES an empty
    placeholder for every scraped product, and a concurrent parse of the same
    text may have beaten us to it. v1 used a bare ``get_or_create`` here, which
    returns an existing row WITHOUT applying ``defaults`` — so the model's
    answer was silently discarded and every scraper-created placeholder stayed
    empty forever. A placeholder is now filled in; an authoritative row is left
    exactly as it is.

    The write is scoped with ``update_fields`` so it can never touch the
    validation columns: a fill running while an operator validates the same
    mapping must not revert them (user decision 2026-08-03).
    """
    values = _parsed_columns(parsed, llm_response)
    mapping, created = ProductParsingMapping.objects.get_or_create(
        input_hash=input_hash, defaults={"input_data": _input_data(product), **values}
    )
    if created:
        return mapping
    if mapping.is_validated:
        logger.info("Mapping %s was validated by an operator; keeping their values", input_hash[:8])
        return mapping
    if mapping.parser_version == PARSER_VERSION:
        logger.info("Mapping %s already parsed at %s", input_hash[:8], PARSER_VERSION)
        return mapping

    for field, value in values.items():
        setattr(mapping, field, value)
    mapping.save(update_fields=list(values))
    logger.info("Filled reserved mapping %s with the parser result", input_hash[:8])
    return mapping


def _call_llm(products: Sequence[ProductInput]) -> list[dict[str, object]] | None:
    """Run one LLM round-trip, or return None when the reply was unusable.

    A malformed reply is a routine outcome the callers already handle (the stock
    parser records the attempt and stops retrying), so it is persisted as an
    AppError and reported as None. Configuration failures — no provider, no API
    key, no litellm — propagate: those must not look like "the model had nothing
    to say" (ADR 0015).
    """
    reply = chat_completion(build_parsing_prompt(products), provider_type=PARSING_PROVIDER_TYPE)
    try:
        return extract_json_objects(reply)
    except (LLMResponseError, json.JSONDecodeError) as exc:
        persist_app_error(
            exc,
            AppErrorContext(additional_context={"products": len(products), "reply": reply[:2000]}),
        )
        logger.error("LLM product parsing returned unusable JSON: %s", exc)
        return None


def _authoritative_mapping(input_hash: str) -> ProductParsingMapping | None:
    """Return this hash's mapping only when it already carries a real answer.

    THE cache lookup (ADR 0039). v1 looked mappings up by ``input_hash`` alone,
    so the empty placeholder ``create_mapping_record`` reserves answered its own
    lookup: the caller got a "cache hit" whose every field was NULL and the LLM
    was never called. See ``AUTHORITATIVE_MAPPING``.
    """
    return ProductParsingMapping.objects.filter(
        Q(input_hash=input_hash) & AUTHORITATIVE_MAPPING
    ).first()


def parse_product(product: ProductInput) -> tuple[ParsedProduct | None, bool]:
    """Parse one product. Returns ``(result, was_cached)``; result is None on failure."""
    input_hash = product_mapping_hash(product.hash_source)
    cached = _authoritative_mapping(input_hash)
    if cached is not None:
        logger.info("Using cached mapping for hash %s", input_hash[:8])
        return _mapping_to_parsed(cached), True

    logger.info("Parsing new product data with LLM (hash %s)", input_hash[:8])
    rows = _call_llm([product])
    if not rows:
        return None, False

    mapping = _save_mapping(
        input_hash=input_hash, product=product, parsed=rows[0], llm_response=rows
    )
    logger.info("Created new mapping for hash %s", input_hash[:8])
    return _mapping_to_parsed(mapping), False


def parse_products_batch(
    products: Sequence[ProductInput],
) -> list[tuple[ParsedProduct | None, bool]]:
    """Parse many products in one LLM round-trip, reusing cached mappings.

    v1 fell back to one call per product when the batch reply had the wrong
    length; kept, because a short reply otherwise silently mis-aligns results
    with inputs.
    """
    if not products:
        return []

    results: list[tuple[ParsedProduct | None, bool] | None] = [None] * len(products)
    pending: list[tuple[int, ProductInput]] = []
    for index, product in enumerate(products):
        cached = _authoritative_mapping(product_mapping_hash(product.hash_source))
        if cached is None:
            pending.append((index, product))
        else:
            results[index] = (_mapping_to_parsed(cached), True)

    if pending:
        logger.info("Batch parsing %s products with LLM", len(pending))
        rows = _call_llm([product for _, product in pending])
        if rows is not None and len(rows) == len(pending):
            for (index, product), parsed in zip(pending, rows, strict=True):
                mapping = _save_mapping(
                    input_hash=product_mapping_hash(product.hash_source),
                    product=product,
                    parsed=parsed,
                    llm_response=rows,
                )
                results[index] = (_mapping_to_parsed(mapping), False)
        else:
            logger.error("Batch parsing failed or returned the wrong number of results")
            for index, product in pending:
                results[index] = parse_product(product)

    return [result if result is not None else (None, False) for result in results]


def create_mapping_record(product: SupplierProduct) -> ProductParsingMapping:
    """Stamp a supplier product with its mapping hash and reserve the mapping row.

    Called on every scraped/imported product. The mapping starts empty; the LLM
    fills it in later, in bulk, via ``populate_all_mappings_with_llm``.
    """
    mapping_hash = supplier_product_mapping_hash(product)
    SupplierProduct.objects.filter(id=product.id).update(mapping_hash=mapping_hash)
    product.mapping_hash = mapping_hash

    mapping, created = ProductParsingMapping.objects.get_or_create(
        input_hash=mapping_hash,
        defaults={
            "input_data": _input_data(
                ProductInput(
                    product_name=product.product_name,
                    description=product.description or "",
                    specifications=product.specifications or "",
                    item_no=product.item_no,
                    variant_id=product.variant_id,
                    variant_width=product.variant_width or "",
                    variant_length=product.variant_length or "",
                    variant_price=product.variant_price,
                    price_unit=product.price_unit or "",
                )
            )
        },
    )
    logger.info(
        "%s mapping %s for supplier product %s",
        "Created" if created else "Reused",
        mapping_hash[:8],
        product.id,
    )
    return mapping


def apply_mapping_to_products(mapping: ProductParsingMapping) -> int:
    """Back-flow a mapping's values onto every product that shares its hash.

    THE one implementation of mapping → ``SupplierProduct.parsed_*`` (ADR 0039);
    ``apps.purchasing.services.supplier_pricing_service.validate_product_mapping``
    calls this rather than repeating the column list. Returns the row count.
    """
    updated = SupplierProduct.objects.filter(mapping_hash=mapping.input_hash).update(
        parsed_item_code=mapping.mapped_item_code,
        parsed_description=mapping.mapped_description,
        parsed_metal_type=mapping.mapped_metal_type,
        parsed_alloy=mapping.mapped_alloy,
        parsed_specifics=mapping.mapped_specifics,
        parsed_dimensions=mapping.mapped_dimensions,
        parsed_unit_cost=mapping.mapped_unit_cost,
        parsed_price_unit=mapping.mapped_price_unit,
        parsed_at=timezone.now(),
        parser_version=mapping.parser_version,
        parser_confidence=mapping.parser_confidence,
    )
    logger.info("Mapping %s back-flowed to %s products", mapping.input_hash[:8], updated)
    return updated


def _hash_matches_stored_input(mapping: ProductParsingMapping) -> bool:
    """Check a stored mapping still hashes to its own key before parsing it.

    The whole cache rests on this invariant, so it is verified rather than
    assumed (ADR 0015/0028). A row whose ``input_data`` lost the text it was
    keyed by would otherwise be parsed as the EMPTY string: the result would be
    saved under ``sha256("")``, creating a stray mapping, while this row stayed
    a placeholder and its products were back-flowed with someone else's values.
    """
    rebuilt = input_from_mapping(mapping)
    if product_mapping_hash(rebuilt.hash_source) == mapping.input_hash:
        return True
    persist_app_error(
        ValueError(
            f"ProductParsingMapping {mapping.input_hash[:8]} no longer hashes to its own "
            f"input_data; it names no description or product_name and cannot be re-parsed. "
            f"Fix the row (see the product_parser docstring), do not re-key it."
        ),
        AppErrorContext(additional_context={"input_hash": mapping.input_hash}),
    )
    logger.error("Mapping %s does not hash to its own input_data; skipped", mapping.input_hash[:8])
    return False


def populate_all_mappings_with_llm() -> int:
    """Fill every placeholder mapping via the LLM and back-flow the results.

    Run at the end of a scrape. Returns the number of mappings populated.

    The work list is the exact complement of the cache lookup — everything NOT
    ``AUTHORITATIVE_MAPPING`` — so a row is either served from the cache or
    queued for a parse, never both and never neither. v1 asked two different
    questions here (``mapped_item_code__isnull`` for the work list, bare
    ``input_hash`` for the cache) and the fill consequently did nothing at all.
    """
    placeholders = list(ProductParsingMapping.objects.exclude(AUTHORITATIVE_MAPPING))
    if not placeholders:
        logger.info("No unpopulated mappings to process")
        return 0

    logger.info("Processing %s unpopulated mappings with LLM", len(placeholders))
    populated = 0
    for start in range(0, len(placeholders), BATCH_SIZE):
        batch = [
            mapping
            for mapping in placeholders[start : start + BATCH_SIZE]
            if _hash_matches_stored_input(mapping)
        ]
        results = parse_products_batch([input_from_mapping(mapping) for mapping in batch])
        for mapping, (parsed, _was_cached) in zip(batch, results, strict=True):
            if parsed is None:
                logger.warning("Mapping %s could not be parsed", mapping.input_hash[:8])
                continue
            # _save_mapping has already written this row; re-read it rather than
            # pushing a snapshot taken before the LLM round-trip back over it.
            mapping.refresh_from_db()
            apply_mapping_to_products(mapping)
            populated += 1
            logger.info("Processed mapping %s", mapping.input_hash[:8])

    logger.info("Completed batch processing of %s mappings", populated)
    return populated
