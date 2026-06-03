import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from apps.job.services.delta_checksum import compute_job_delta_checksum


def test_checksum_is_deterministic_with_sorted_fields():
    """Field-order differences must not cause false delta conflicts.

    This catches checksum code that preserves dict insertion order, because the
    frontend and backend may build the same delta envelope in different orders.
    """
    job_id = uuid.uuid4()
    values = {"description": "Cut and fold", "order_number": "PO-123"}

    checksum_a = compute_job_delta_checksum(job_id, values)
    checksum_b = compute_job_delta_checksum(job_id, dict(reversed(values.items())))

    assert checksum_a == checksum_b


def test_checksum_trims_strings_and_normalises_null():
    """Equivalent form values must hash the same after canonicalisation.

    This catches regressions where harmless input padding creates a false
    conflict, while unset nullable fields still have a stable representation.
    """
    job_id = "job-123"
    values = {"description": "  padded  ", "notes": None}

    checksum = compute_job_delta_checksum(job_id, values)
    assert checksum == compute_job_delta_checksum(
        job_id, {"description": "padded", "notes": None}
    )


def test_checksum_handles_decimal_and_boolean_and_numbers():
    """Numeric representation differences must not break optimistic locking.

    This catches checksum changes that treat ``5.10`` and ``5.100`` as
    different job state even though they represent the same persisted value.
    """
    job_id = "job-123"
    values = {
        "charge_out_rate": Decimal("5.10"),
        "priority": 3,
        "flagged": True,
    }

    checksum = compute_job_delta_checksum(job_id, values)
    assert checksum == compute_job_delta_checksum(
        job_id,
        {"charge_out_rate": Decimal("5.100"), "priority": 3, "flagged": True},
    )


def test_checksum_handles_datetimes_and_dates():
    """Timezone representation differences must not create false conflicts.

    This catches UTC-aware and naive-UTC datetimes hashing differently when
    they refer to the same stored job timestamp.
    """
    job_id = "job-123"
    dt = datetime(2025, 10, 7, 8, 7, 11, 251000, tzinfo=timezone.utc)
    d = date(2025, 10, 7)

    checksum = compute_job_delta_checksum(job_id, {"updated_at": dt, "delivery": d})

    naive_dt = dt.replace(tzinfo=None)
    assert checksum == compute_job_delta_checksum(
        job_id, {"updated_at": naive_dt, "delivery": d}
    )


def test_checksum_respects_explicit_field_subset():
    """Partial deltas must lock only the fields they are changing.

    This catches checksum code that ignores the requested field subset and
    would reject a valid edit because unrelated job fields changed meanwhile.
    """
    job_id = "job-123"
    values = {
        "name": "Part A",
        "description": "Cut and fold",
        "notes": "Internal",
    }

    checksum_all = compute_job_delta_checksum(job_id, values)
    checksum_subset = compute_job_delta_checksum(job_id, values, fields=["description"])

    assert checksum_all != checksum_subset


def test_checksum_raises_when_job_id_missing():
    """A delta without a job identity must not produce a reusable checksum.

    This catches callers accidentally hashing orphaned field values and then
    sending a checksum that cannot protect a specific job row.
    """
    with pytest.raises(ValueError):
        compute_job_delta_checksum("", {"name": "Part A"})


def test_checksum_raises_for_missing_field_in_subset():
    """Requested fields missing from the snapshot must fail before mutation.

    This catches envelope-building bugs where the checksum omits a field the
    client claims to protect, which would weaken conflict detection.
    """
    with pytest.raises(ValueError):
        compute_job_delta_checksum("job-1", {"name": "Part A"}, fields=["description"])
