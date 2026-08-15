"""Contracts of the backup verifier's migration-ledger acceptance.

Pure-function tests: rows are the tab-separated COPY lines pg_restore emits
for django_migrations (id, app, name, applied).
"""

import pytest

from scripts.ops.verify_scrubbed_backup import (
    _assert_squashed_baseline,
    distinct_usable_hashes,
)


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
