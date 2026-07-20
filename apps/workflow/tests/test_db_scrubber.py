"""Unit tests for production database scrubbing contracts.

The full scrub runs against the ``scrub`` DB alias (a restored prod copy) and is
not exercised here; these tests pin the novel logic that keeps the scrub from
aborting on a normalized-value collision.
"""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from apps.company.models import ContactMethod
from apps.workflow.models import AppError
from apps.workflow.services.db_scrubber import (
    _PRIVATE_CONFIG_TABLES,
    _assert_private_config_removed,
    _unique_scrub_value,
    scrub,
)
from apps.workflow.services.error_persistence import persist_app_error

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


class PrivateConfigurationScrubTests(SimpleTestCase):
    def test_external_credentials_are_part_of_the_scrub_contract(self) -> None:
        self.assertEqual(
            set(_PRIVATE_CONFIG_TABLES),
            {
                "workflow_aiprovider",
                "workflow_xeroapp",
                "workflow_serviceapikey",
                "crm_phoneprovidersettings",
                "quoting_suppliercredential",
            },
        )

    @patch("apps.workflow.services.db_scrubber.connections")
    def test_private_config_postcondition_accepts_empty_tables(
        self, connections: MagicMock
    ) -> None:
        cursor = connections.__getitem__.return_value.cursor.return_value.__enter__
        cursor.return_value.fetchone.side_effect = [(0,)] * len(_PRIVATE_CONFIG_TABLES)

        _assert_private_config_removed()

    @patch("apps.workflow.services.db_scrubber.connections")
    def test_private_config_postcondition_reports_counts_not_values(
        self, connections: MagicMock
    ) -> None:
        cursor = connections.__getitem__.return_value.cursor.return_value.__enter__
        cursor.return_value.fetchone.side_effect = [
            (2,) if table == "workflow_aiprovider" else (0,)
            for table in _PRIVATE_CONFIG_TABLES
        ]

        with self.assertRaisesRegex(
            RuntimeError,
            r"workflow_aiprovider=2",
        ) as raised:
            _assert_private_config_removed()

        self.assertNotIn("api_key", str(raised.exception))


class ScrubErrorPersistenceTests(TestCase):
    @patch("apps.workflow.services.db_scrubber._assert_scrub_alias_is_safe")
    @patch("apps.workflow.services.db_scrubber.transaction.atomic")
    @patch("apps.workflow.services.db_scrubber._scrub_staff")
    @patch("apps.workflow.services.db_scrubber.persist_app_error")
    def test_new_failure_is_persisted_once_and_reraised(
        self,
        persist_app_error_mock: MagicMock,
        scrub_staff: MagicMock,
        _atomic: MagicMock,
        _assert_safe: MagicMock,
    ) -> None:
        failure = RuntimeError("scrub failed")
        scrub_staff.side_effect = failure

        with self.assertRaises(RuntimeError) as raised:
            scrub()

        self.assertIs(raised.exception, failure)
        persist_app_error_mock.assert_called_once_with(failure)

    @patch("apps.workflow.services.db_scrubber._assert_scrub_alias_is_safe")
    @patch("apps.workflow.services.db_scrubber.transaction.atomic")
    @patch("apps.workflow.services.db_scrubber._scrub_staff")
    def test_prelogged_failure_gets_no_second_app_error(
        self,
        scrub_staff: MagicMock,
        _atomic: MagicMock,
        _assert_safe: MagicMock,
    ) -> None:
        failure = RuntimeError("scrub failed")
        persist_app_error(failure)
        scrub_staff.side_effect = failure
        before = AppError.objects.count()

        with self.assertRaises(RuntimeError) as raised:
            scrub()

        self.assertIs(raised.exception, failure)
        self.assertEqual(AppError.objects.count(), before)
