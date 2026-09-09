"""Contracts of the backup verifier's migration-ledger acceptance.

Pure-function tests: rows are the tab-separated COPY lines pg_restore emits
for django_migrations (id, app, name, applied).
"""

import pytest

from scripts.ops.verify_scrubbed_backup import (
    _assert_ledger_is_this_codebase,
    distinct_usable_hashes,
)


def _row(app: str, migration: str, row_id: int = 1) -> str:
    return f"{row_id}\t{app}\t{migration}\t2026-08-01 00:00:00+00"


class TestLedgerAcceptance:
    def test_current_archive_is_accepted(self) -> None:
        _assert_ledger_is_this_codebase(
            [
                _row("company", "0001_initial"),
                _row("operations", "0001_initial", 2),
                _row("accounts", "0001_initial", 3),
            ]
        )

    def test_ledger_carrying_the_workflow_app_is_refused(self) -> None:
        # The restore is a plain pg_restore into an emptied database, so a
        # ledger from the pre-split app layout has no load path here.
        with pytest.raises(RuntimeError, match="not one this codebase can restore"):
            _assert_ledger_is_this_codebase(
                [_row("company", "0001_initial"), _row("workflow", "0001_initial", 2)]
            )

    def test_ledger_without_company_initial_is_refused(self) -> None:
        with pytest.raises(RuntimeError, match="not one this codebase can restore"):
            _assert_ledger_is_this_codebase([_row("company", "0001_baseline")])

    def test_obsolete_client_label_is_refused(self) -> None:
        with pytest.raises(RuntimeError, match="not one this codebase can restore"):
            _assert_ledger_is_this_codebase([_row("client", "0001_baseline")])


class TestPasswordScrubCheck:
    """The archive is the artefact that travels, so it is what gets checked."""

    @staticmethod
    def _passwords(*values: str) -> list[str]:
        return list(values)

    def test_one_shared_hash_is_clean(self) -> None:
        # The scrub hashes the public nonprod password once and shares it, so
        # a scrubbed archive holds a single distinct usable value.
        shared = "pbkdf2_sha256$1$abc"
        assert distinct_usable_hashes(self._passwords(shared, shared)) == 1

    def test_unusable_passwords_do_not_count(self) -> None:
        assert distinct_usable_hashes(self._passwords("!xyz", "!abc", "pbkdf2_sha256$1$abc")) == 1

    def test_per_row_production_hashes_are_many(self) -> None:
        # Production hashes are salted per row, which is exactly what makes
        # them detectable without needing Django to verify them.
        assert distinct_usable_hashes(self._passwords("pbkdf2$a", "pbkdf2$b", "pbkdf2$c")) == 3
