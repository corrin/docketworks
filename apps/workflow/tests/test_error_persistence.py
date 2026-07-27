"""Unit tests for idempotent error persistence.

The system guarantee is one AppError row per failure. That guarantee is
enforced by persist_app_error itself — it marks the exception it persists
and returns the existing row on any subsequent call — rather than by every
handler in the codebase remembering a two-arm ritual.

The propagation test is the regression that motivates the design: an
exception persisted deep in a service and re-raised through intermediate
handlers up to the DRF boundary must still produce exactly one row.
"""

from apps.testing import BaseTestCase
from apps.workflow.models import AppError
from apps.workflow.services.error_persistence import (
    app_error_for,
    persist_app_error,
)


class PersistAppErrorIdempotencyTests(BaseTestCase):
    def test_persisting_twice_creates_one_row(self) -> None:
        exc = ValueError("boom")

        first = persist_app_error(exc)
        second = persist_app_error(exc)

        self.assertEqual(AppError.objects.count(), 1)
        self.assertEqual(first.id, second.id)

    def test_distinct_exceptions_each_get_a_row(self) -> None:
        persist_app_error(ValueError("one"))
        persist_app_error(ValueError("two"))

        self.assertEqual(AppError.objects.count(), 2)

    def test_survives_propagation_through_nested_handlers(self) -> None:
        """A failure persisted in a service and re-raised through two
        intermediate handlers to the boundary yields one row, not three."""

        def service() -> None:
            raise ValueError("deep failure")

        def middle() -> None:
            try:
                service()
            except Exception as exc:
                persist_app_error(exc)
                raise

        def boundary() -> None:
            try:
                middle()
            except Exception as exc:
                persist_app_error(exc)
                raise

        with self.assertRaises(ValueError):
            try:
                boundary()
            except Exception as exc:
                persist_app_error(exc)
                raise

        self.assertEqual(AppError.objects.count(), 1)

    def test_conversion_with_from_exc_does_not_earn_a_second_row(self) -> None:
        """A handler that converts the exception type still represents one
        failure. `raise ... from exc` links them, so persistence follows the
        cause chain rather than counting objects."""
        original = KeyError("missing")
        persist_app_error(original)

        try:
            raise ValueError("Job not found") from original
        except ValueError as converted:
            persist_app_error(converted)

        self.assertEqual(AppError.objects.count(), 1)

    def test_unchained_conversion_is_a_separate_failure(self) -> None:
        """Without `from exc` there is no link, so the new exception is a
        genuinely separate record — the cost of severing the chain."""
        persist_app_error(KeyError("missing"))

        try:
            raise ValueError("Job not found")
        except ValueError as converted:
            persist_app_error(converted)

        self.assertEqual(AppError.objects.count(), 2)

    def test_context_from_the_first_persist_is_kept(self) -> None:
        """The innermost handler has the richest context (it knows the job),
        so the first write wins and later calls must not overwrite it."""
        exc = ValueError("boom")

        persist_app_error(exc, app="inner", additional_context={"detail": "rich"})
        persist_app_error(exc, app="outer")

        stored = AppError.objects.get()
        self.assertEqual(stored.app, "inner")
        stored_data = stored.data
        assert stored_data is not None  # narrows for mypy
        self.assertEqual(stored_data["detail"], "rich")


class AppErrorForTests(BaseTestCase):
    def test_returns_the_row_for_a_persisted_exception(self) -> None:
        exc = ValueError("boom")
        err = persist_app_error(exc)

        found = app_error_for(exc)
        self.assertIsNotNone(found)
        assert found is not None  # narrows for mypy
        self.assertEqual(found.id, err.id)

    def test_returns_none_for_an_unpersisted_exception(self) -> None:
        self.assertIsNone(app_error_for(ValueError("never persisted")))
