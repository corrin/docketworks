"""ETag computation and comparison semantics (ADR 0003).

Business risk covered: a drifting ETag format or comparison rule breaks
optimistic concurrency — stale writes stop being rejected with 412, or every
write starts failing. The value format is a wire contract with the frontend.
"""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from apps.core.etag import (
    generate_updated_at_etag,
    if_match_satisfied,
    if_none_match_satisfied,
    updated_at_etag_value,
)

RESOURCE_ID = UUID("12345678-1234-5678-1234-567812345678")
UPDATED_AT = datetime(2026, 3, 4, 5, 6, 7, 123456, tzinfo=UTC)


class TestUpdatedAtEtagValue:
    def test_value_is_resource_id_and_full_precision_utc_timestamp(self) -> None:
        value = updated_at_etag_value("job", RESOURCE_ID, UPDATED_AT)
        assert value == f"job:{RESOURCE_ID}:2026-03-04T05:06:07.123456Z"

    def test_non_utc_timestamps_are_normalised_to_utc(self) -> None:
        nz = timezone(timedelta(hours=13))
        local = UPDATED_AT.astimezone(nz)
        assert updated_at_etag_value("po", RESOURCE_ID, local) == updated_at_etag_value(
            "po", RESOURCE_ID, UPDATED_AT
        )

    def test_naive_timestamps_are_rejected(self) -> None:
        naive = datetime(2026, 3, 4, 5, 6, 7, 123456)  # deliberately naive
        with pytest.raises(ValueError, match="timezone-aware"):
            updated_at_etag_value("job", RESOURCE_ID, naive)

    def test_microsecond_changes_produce_different_values(self) -> None:
        before = updated_at_etag_value("job", RESOURCE_ID, UPDATED_AT)
        after = updated_at_etag_value("job", RESOURCE_ID, UPDATED_AT + timedelta(microseconds=1))
        assert before != after


class TestGenerateUpdatedAtEtag:
    def test_etag_is_the_quoted_strong_form_of_the_value(self) -> None:
        etag = generate_updated_at_etag("job", RESOURCE_ID, UPDATED_AT)
        assert etag == f'"{updated_at_etag_value("job", RESOURCE_ID, UPDATED_AT)}"'
        assert not etag.startswith("W/")


class TestIfMatch:
    def test_exact_current_version_satisfies(self) -> None:
        etag = generate_updated_at_etag("job", RESOURCE_ID, UPDATED_AT)
        assert if_match_satisfied(etag, etag)

    def test_stale_version_does_not_satisfy(self) -> None:
        current = generate_updated_at_etag("job", RESOURCE_ID, UPDATED_AT)
        stale = generate_updated_at_etag("job", RESOURCE_ID, UPDATED_AT - timedelta(seconds=1))
        assert not if_match_satisfied(stale, current)

    def test_any_member_of_a_list_may_match(self) -> None:
        current = generate_updated_at_etag("job", RESOURCE_ID, UPDATED_AT)
        header = f'"something-else", {current}'
        assert if_match_satisfied(header, current)


class TestIfNoneMatch:
    def test_star_matches_anything(self) -> None:
        current = generate_updated_at_etag("job", RESOURCE_ID, UPDATED_AT)
        assert if_none_match_satisfied("*", current)

    def test_weak_comparison_ignores_weak_prefixes(self) -> None:
        current = generate_updated_at_etag("job", RESOURCE_ID, UPDATED_AT)
        assert if_none_match_satisfied(f"W/{current}", current)

    def test_different_version_does_not_match(self) -> None:
        current = generate_updated_at_etag("job", RESOURCE_ID, UPDATED_AT)
        other = generate_updated_at_etag("job", RESOURCE_ID, UPDATED_AT + timedelta(seconds=1))
        assert not if_none_match_satisfied(other, current)
