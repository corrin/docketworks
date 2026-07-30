"""Shared ETag helpers must implement the application's HTTP contracts."""

from datetime import UTC, datetime
from uuid import uuid4

from django.test import SimpleTestCase

from apps.workflow.etag import (
    generate_updated_at_etag,
    if_match_satisfied,
    if_none_match_satisfied,
)


class UpdatedAtETagTests(SimpleTestCase):
    def setUp(self) -> None:
        self.etag = generate_updated_at_etag(
            "job",
            uuid4(),
            datetime(2026, 7, 30, 12, 0, 0, 123456, tzinfo=UTC),
        )

    def test_generates_a_strong_etag(self) -> None:
        self.assertTrue(self.etag.startswith('"job:'))
        self.assertFalse(self.etag.startswith("W/"))

    def test_if_match_accepts_the_exact_current_tag_in_a_header_list(self) -> None:
        self.assertTrue(if_match_satisfied(f'"other", {self.etag}', self.etag))

    def test_if_match_rejects_weak_wildcard_and_malformed_tags(self) -> None:
        self.assertFalse(if_match_satisfied(f"W/{self.etag}", self.etag))
        self.assertFalse(if_match_satisfied("*", self.etag))
        self.assertFalse(if_match_satisfied("not-an-etag", self.etag))

    def test_if_none_match_uses_weak_comparison_and_wildcard_semantics(self) -> None:
        self.assertTrue(if_none_match_satisfied(f"W/{self.etag}", self.etag))
        self.assertTrue(if_none_match_satisfied("*", self.etag))
