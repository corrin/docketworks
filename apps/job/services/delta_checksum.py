"""
Deterministic checksum utilities for job delta validation.

These helpers canonicalise the state of a set of fields so that the frontend
and backend can compute identical hashes when constructing the delta envelope.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

logger = logging.getLogger(__name__)

NULL_SENTINEL = "__NULL__"


@dataclass(frozen=True)
class ChecksumInput:
    """Container that represents the canonical payload used to build the hash."""

    job_id: str
    components: Sequence[tuple[str, str]]

    def serialise(self) -> str:
        """
        Serialise the checksum input to a deterministic string.

        Example: ``job-id|description=Cut and fold|order_number=PO-123``
        """
        parts = [self.job_id]
        for field, value in self.components:
            parts.append(f"{field}={value}")
        return "|".join(parts)


def compute_job_delta_checksum(
    job_id: UUID | str,
    field_values: Mapping[str, object],
    fields: Iterable[str] | None = None,
) -> str:
    """
    Compute a deterministic SHA-256 checksum for a subset of job fields.

    Args:
        job_id: UUID or string identifier of the job being mutated.
        field_values: Mapping containing the current values (pre-change).
        fields: Optional explicit list of fields to include. When omitted the
            keys of ``field_values`` are used.

    Returns:
        Hex digest string representing the checksum.

    Raises:
        ValueError: If ``job_id`` is falsy or a requested field is missing.
    """
    logger.debug(f"[CHECKSUM_COMPUTE] Starting checksum computation for job {job_id}")
    logger.debug(f"[CHECKSUM_COMPUTE] Input field_values: {dict(field_values)}")

    job_id_str = _normalise_job_id(job_id)
    selected_fields = _determine_fields(field_values, fields)

    logger.debug(f"[CHECKSUM_COMPUTE] Selected fields: {sorted(selected_fields)}")

    components = []

    for field in sorted(selected_fields):
        if field not in field_values:
            raise ValueError(f"Field '{field}' missing from provided values")
        value = field_values.get(field)
        normalized_value = normalise_value(value)

        logger.debug(
            f"[CHECKSUM_COMPUTE] Field '{field}': raw='{value}' (type: {type(value)})"
            f" -> normalized='{normalized_value}'"
        )

        components.append((field, normalized_value))

    payload = ChecksumInput(job_id=job_id_str, components=tuple(components))
    serialized = payload.serialise()

    logger.debug(f"[CHECKSUM_COMPUTE] Serialized payload: '{serialized}'")

    raw = serialized.encode("utf-8")
    checksum = hashlib.sha256(raw).hexdigest()

    logger.debug(f"[CHECKSUM_COMPUTE] Final checksum: {checksum}")

    return checksum


def _normalise_job_id(job_id: UUID | str) -> str:
    if isinstance(job_id, UUID):
        return str(job_id)
    job_id_str = (job_id or "").strip()
    if not job_id_str:
        raise ValueError("job_id is required to compute checksum")
    return job_id_str


def _determine_fields(
    field_values: Mapping[str, object],
    fields: Iterable[str] | None,
) -> Sequence[str]:
    if fields is None:
        return tuple(field_values.keys())
    return tuple(fields)


def normalise_value(value: object) -> str:
    if value is None:
        return NULL_SENTINEL

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, Decimal):
        normalised = value.normalize()
        return format(normalised, "f")

    if isinstance(value, (int, float)):
        return format(value, "f") if isinstance(value, float) else str(value)

    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, (list, tuple, set)):
        normalised_items = [normalise_value(item) for item in value]
        return f"[{','.join(normalised_items)}]"

    return str(value)
