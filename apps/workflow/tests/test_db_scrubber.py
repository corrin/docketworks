"""Unit tests for db_scrubber collision-safe value generation.

The full scrub runs against the ``scrub`` DB alias (a restored prod copy) and is
not exercised here; these tests pin the novel logic that keeps the scrub from
aborting on a normalized-value collision.
"""

from django.test import SimpleTestCase

from apps.company.models import ContactMethod
from apps.workflow.services.db_scrubber import _unique_scrub_value

PHONE = ContactMethod.MethodType.PHONE


class UniqueScrubValueTests(SimpleTestCase):
    def test_returns_value_and_normalized_and_records_it(self) -> None:
        used: set[tuple[str, str]] = set()
        value, normalized = _unique_scrub_value(lambda: "021 111 111", PHONE, used)

        self.assertEqual(value, "021 111 111")
        self.assertEqual(normalized, ContactMethod.normalize_phone("021 111 111"))
        self.assertIn((PHONE, normalized), used)

    def test_skips_values_that_normalize_to_an_already_used_number(self) -> None:
        used: set[tuple[str, str]] = set()
        _unique_scrub_value(lambda: "021 111 111", PHONE, used)  # seed `used`
        # "+64 21 111 111" normalizes to the same number as the seed, so it must
        # be skipped; only the fresh third draw is acceptable.
        draws = iter(["021 111 111", "+64 21 111 111", "021 333 333"])
        value, _ = _unique_scrub_value(lambda: next(draws), PHONE, used)

        self.assertEqual(value, "021 333 333")

    def test_raises_when_every_attempt_collides(self) -> None:
        used: set[tuple[str, str]] = set()
        _unique_scrub_value(lambda: "021 111 111", PHONE, used)  # seed `used`
        with self.assertRaises(RuntimeError):
            _unique_scrub_value(lambda: "021 111 111", PHONE, used)
