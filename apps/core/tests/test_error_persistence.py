"""One failure is one AppError row (ADR 0001), no matter how many handlers catch it.

Business risk covered: duplicate rows would wreck "how often does this fail?"
queries (ADR 0019), and a lost marker would strand a response without its
``error_id`` cross-reference (ADR 0013).
"""

from uuid import uuid4

import pytest

from apps.core.errors import AppErrorContext, app_error_for, persist_app_error
from apps.core.models import AppError


@pytest.mark.django_db
class TestPersistAppErrorIdempotency:
    def test_persisting_twice_returns_the_same_row(self) -> None:
        try:
            raise ValueError("boom")
        except ValueError as exc:
            first = persist_app_error(exc)
            second = persist_app_error(exc)

        assert first.id == second.id
        assert AppError.objects.count() == 1

    def test_every_layer_persisting_yields_one_row(self) -> None:
        """Integration -> service -> view: each layer calls persist_app_error."""
        try:
            raise RuntimeError("deep failure")
        except RuntimeError as exc:
            for _ in range(4):
                persist_app_error(exc)

        assert AppError.objects.count() == 1

    def test_chained_conversion_keeps_one_row(self) -> None:
        """``raise ... from exc`` links the converted exception to the original row."""
        try:
            try:
                raise KeyError("inner")
            except KeyError as inner:
                persist_app_error(inner)
                raise ValueError("converted") from inner
        except ValueError as outer:
            row = persist_app_error(outer)

        assert AppError.objects.count() == 1
        # The first (richer-context) write wins: the row is the inner failure's.
        assert row.message == "'inner'"

    def test_unchained_conversion_creates_a_second_row(self) -> None:
        """Without ``from exc`` the link is severed — this is why W0707 is mandatory."""
        try:
            try:
                raise KeyError("inner")
            except KeyError as inner:
                persist_app_error(inner)
                raise ValueError("converted without chaining")  # noqa: B904
        except ValueError as outer:
            persist_app_error(outer)

        assert AppError.objects.count() == 2

    def test_app_error_for_finds_the_row_through_the_cause_chain(self) -> None:
        try:
            try:
                raise KeyError("inner")
            except KeyError as inner:
                persisted = persist_app_error(inner)
                raise ValueError("converted") from inner
        except ValueError as outer:
            found = app_error_for(outer)

        assert found is not None
        assert found.id == persisted.id

    def test_app_error_for_returns_none_when_never_persisted(self) -> None:
        exc = ValueError("never persisted")
        assert app_error_for(exc) is None


@pytest.mark.django_db
class TestPersistAppErrorContext:
    def test_caller_context_is_auto_extracted(self) -> None:
        try:
            raise ValueError("context probe")
        except ValueError as exc:
            row = persist_app_error(exc)

        assert row.app == "core"
        assert row.file == "core/tests/test_error_persistence.py"
        assert row.function == "test_caller_context_is_auto_extracted"

    def test_explicit_location_overrides_auto_extraction(self) -> None:
        try:
            raise ValueError("override probe")
        except ValueError as exc:
            row = persist_app_error(
                exc, AppErrorContext(app="quoting", file="quoting/x.py", function="do_x")
            )

        assert (row.app, row.file, row.function) == ("quoting", "quoting/x.py", "do_x")

    def test_traceback_and_additional_context_are_stored(self) -> None:
        marker = uuid4()
        try:
            raise ValueError("data probe")
        except ValueError as exc:
            row = persist_app_error(exc, AppErrorContext(additional_context={"entity_id": marker}))

        assert row.data is not None
        assert "ValueError: data probe" in str(row.data["trace"])
        # UUIDs are converted to strings so the JSON column can hold them.
        assert row.data["entity_id"] == str(marker)

    def test_business_ids_are_stored_on_dedicated_columns(self) -> None:
        job_id = uuid4()
        user_id = uuid4()
        try:
            raise ValueError("id probe")
        except ValueError as exc:
            row = persist_app_error(exc, AppErrorContext(job_id=job_id, user_id=str(user_id)))

        row.refresh_from_db()  # normalises str-typed ids to UUID
        assert row.job_id == job_id
        assert row.user_id == user_id

    def test_invalid_session_replay_id_is_flagged_not_stored(self) -> None:
        try:
            raise ValueError("replay probe")
        except ValueError as exc:
            row = persist_app_error(exc, AppErrorContext(session_replay_id="not-a-uuid"))

        assert row.session_replay_id is None
        assert row.data is not None
        assert row.data["invalid_session_replay_id"] == "not-a-uuid"

    def test_unlinked_session_replay_id_is_flagged_not_stored(self) -> None:
        """A well-formed UUID with no matching recording must NOT hit the FK.

        Regression: AppError.session_replay is a live DB foreign key; without
        the v1 existence check, an unlinked id raises IntegrityError inside the
        error-persistence path and destroys the original error's envelope.
        """
        ghost = uuid4()
        try:
            raise ValueError("unlinked replay probe")
        except ValueError as exc:
            row = persist_app_error(exc, AppErrorContext(session_replay_id=ghost))

        assert row.session_replay_id is None
        assert row.data is not None
        assert row.data["unlinked_session_replay_id"] == str(ghost)
