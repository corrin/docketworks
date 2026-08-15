"""Contracts of the backup verifier's migration-ledger acceptance.

Pure-function tests: rows are the tab-separated COPY lines pg_restore emits
for django_migrations (id, app, name, applied).
"""

import pytest

from scripts.ops.verify_scrubbed_backup import _assert_squashed_baseline


def _row(app: str, migration: str, row_id: int = 1) -> str:
    return f"{row_id}\t{app}\t{migration}\t2026-08-01 00:00:00+00"


class TestSquashedBaseline:
    def test_v1_squashed_archive_is_accepted(self) -> None:
        _assert_squashed_baseline(
            [_row("company", "0001_baseline"), _row("workflow", "0001_baseline", 2)]
        )

    def test_v2_produced_archive_is_accepted(self) -> None:
        # Post-cutover the producer is v2's own backport_data_backup: its
        # ledger holds company/0001_initial and no workflow app at all, and
        # the verifier must not reject the first pull after the flip.
        _assert_squashed_baseline(
            [
                _row("company", "0001_initial"),
                _row("operations", "0001_initial", 2),
                _row("accounts", "0001_initial", 3),
            ]
        )

    def test_pre_squash_v1_archive_is_refused(self) -> None:
        # A workflow entry with no baseline is the pre-squash v1 signature.
        with pytest.raises(RuntimeError, match="predates the July migration squash"):
            _assert_squashed_baseline(
                [_row("company", "0001_initial"), _row("workflow", "0001_initial", 2)]
            )

    def test_obsolete_client_label_is_refused(self) -> None:
        with pytest.raises(RuntimeError, match="obsolete client migration label"):
            _assert_squashed_baseline([_row("client", "0001_baseline")])

    def test_mixed_labels_are_refused(self) -> None:
        with pytest.raises(RuntimeError, match="mixed client/company"):
            _assert_squashed_baseline(
                [_row("client", "0001_baseline"), _row("company", "0001_baseline", 2)]
            )
