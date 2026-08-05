"""Fill a Stock row's missing metal_type/alloy/specifics from its description.

Every stock write enqueues the Celery task in ``apps/purchasing/tasks.py``;
this module performs the metadata parse on the other side of that task seam.

The value here is not the LLM call (that is shared with the supplier-product
parser); it is the **acceptance rules** that keep the model's output from
polluting inventory. Each rule addresses an observed model failure:

- ``metal_type`` must be a real ``MetalType`` value, after mapping the American
  spellings and separator variants the model likes to emit. Anything else — the
  classic being ``"plastic"`` for a nylon plug — is dropped.
- ``alloy`` must actually appear in the stock row's own text. The model happily
  invents "5005" for an aluminium sheet whose description never named a grade.
- ``specifics`` is only accepted when there is material context (a metal type or
  alloy, parsed or pre-existing), and never for the generic boilerplate that
  appears on service lines.

An operator-supplied value always wins: the parser only fills blanks. A run that
produced no accepted field still stamps ``parser_attempted_at``, which is what
stops the catch-up task re-queueing rows the model has already failed on; only a
run that accepted something stamps ``parsed_at``.
"""

import logging
import re

from django.utils import timezone

from apps.core.errors import AppErrorContext, persist_app_error
from apps.job.enums import MetalType
from apps.purchasing.models import Stock
from apps.quoting.services.product_parser import (
    ParsedProduct,
    ProductInput,
    parse_product,
    to_optional_decimal,
)

logger = logging.getLogger(__name__)

# Spellings Gemini returns that are not MetalType values (v1 METAL_TYPE_ALIASES).
METAL_TYPE_ALIASES = {
    "aluminum": MetalType.ALUMINIUM,
    "aluminium": MetalType.ALUMINIUM,
    "stainless steel": MetalType.STAINLESS_STEEL,
    "mild steel": MetalType.MILD_STEEL,
    "galvanised": MetalType.GALVANIZED,
    "galvanized": MetalType.GALVANIZED,
}

# Boilerplate that carries no inventory meaning (v1 GENERIC_SPECIFICS).
GENERIC_SPECIFICS = frozenset({"service item", "testing stock"})

MAX_SPECIFICS_LENGTH = 255


def _compact(text: str) -> str:
    """Lowercase and strip everything but letters and digits, for containment tests."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def normalise_metal_type(value: str | None) -> str | None:
    """Return a valid ``MetalType`` value, or None if the model made one up."""
    if not value:
        return None
    raw = value.strip().lower()
    if not raw:
        return None
    if raw in {choice[0] for choice in MetalType.choices}:
        return raw
    return METAL_TYPE_ALIASES.get(raw.replace("-", " ").replace("_", " "))


def normalise_alloy(value: str | None, stock: Stock) -> str | None:
    """Accept an alloy only when it appears in the stock row's own text."""
    if not value:
        return None
    alloy = value.strip().upper()
    if not alloy:
        return None
    source = " ".join([stock.description or "", stock.item_code or "", stock.specifics or ""])
    if _compact(alloy) not in _compact(source):
        return None
    return alloy


def normalise_specifics(value: str | None, *, has_material_context: bool) -> str | None:
    """Accept specifics only with material context, and never generic boilerplate."""
    if not has_material_context or not value:
        return None
    specifics = value.strip()
    if not specifics or len(specifics) > MAX_SPECIFICS_LENGTH:
        return None
    if specifics.lower() in GENERIC_SPECIFICS:
        return None
    return specifics


def _stock_input(stock: Stock) -> ProductInput:
    """Present a stock row to the shared product parser."""
    return ProductInput(
        product_name=stock.description or "",
        description=stock.description or "",
        specifications=stock.specifics or "",
        item_no=stock.item_code or "",
        variant_id=f"stock-{stock.id}",
        variant_price=stock.unit_cost,
        price_unit="each",
    )


def _accepted_updates(stock: Stock, parsed: ParsedProduct) -> dict[str, str]:
    """Return only the metadata fields the acceptance rules allow us to write."""
    metal_type = normalise_metal_type(parsed.metal_type)
    alloy = normalise_alloy(parsed.alloy, stock)

    updates: dict[str, str] = {}
    if not stock.metal_type and metal_type:
        updates["metal_type"] = metal_type
    if not stock.alloy and alloy:
        updates["alloy"] = alloy
    if not stock.specifics:
        specifics = normalise_specifics(
            parsed.specifics,
            has_material_context=bool(stock.metal_type or stock.alloy or metal_type or alloy),
        )
        if specifics:
            updates["specifics"] = specifics
    return updates


def auto_parse_stock_item(stock: Stock, *, force: bool = False) -> None:
    """Parse one stock row's description and fill in whatever metadata is missing.

    Already-parsed rows are skipped unless ``force``. Errors are persisted with
    context and re-raised: the caller (the Celery task) decides on retries, and
    a row that raised keeps ``parser_attempted_at`` NULL so the catch-up task
    will try it again — unlike a run the model simply could not answer.
    """
    if stock.parsed_at and not force:
        return

    attempted_at = timezone.now()
    try:
        parsed, was_cached = parse_product(_stock_input(stock))
    except Exception as exc:
        logger.exception("Error parsing stock item %s", stock.id)
        persist_app_error(
            exc,
            AppErrorContext(additional_context={"stock_id": str(stock.id), "force": force}),
        )
        raise

    if parsed is None:
        Stock.objects.filter(id=stock.id).update(parser_attempted_at=attempted_at)
        logger.warning("Failed to parse stock item %s", stock.id)
        return

    accepted = _accepted_updates(stock, parsed)
    updates: dict[str, object] = {
        "parser_attempted_at": attempted_at,
        "parser_version": parsed.parser_version,
        # Stock.parser_confidence is numeric(3,2).
        "parser_confidence": to_optional_decimal(parsed.confidence, max_digits=3, decimal_places=2),
        **accepted,
    }
    if accepted:
        updates["parsed_at"] = attempted_at
    Stock.objects.filter(id=stock.id).update(**updates)

    logger.info(
        "Parsed stock item %s (%s): %s",
        stock.id,
        "from cache" if was_cached else "newly parsed",
        sorted(accepted),
    )
