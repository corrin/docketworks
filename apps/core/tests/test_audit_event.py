"""The shared audit base's snapshot diff, which every recorder stores as ``detail.changes``.

The rendering order (builder, changes, label, sentinel) is asserted where a
subtype exists to render through: ``apps/process/tests/test_process_events.py``.
"""

from decimal import Decimal

from apps.core.audit import snapshot_changes


class TestSnapshotChanges:
    """``snapshot_changes``: the diff a recorder stores as ``detail.changes``."""

    def test_only_keys_whose_value_differs_are_reported(self) -> None:
        # Reporting every key would make a one-field edit read as a dozen.
        before = {"hours": Decimal("2.00"), "desc": "weld", "job": "#10"}
        after = {"hours": Decimal("3.00"), "desc": "weld", "job": "#10"}
        assert snapshot_changes(before, after) == [
            {"field_name": "hours", "old_value": "2.00", "new_value": "3.00"}
        ]

    def test_a_missing_side_is_an_empty_value_not_a_crash(self) -> None:
        # A creation has no before and a deletion no after; both still diff.
        assert snapshot_changes(None, {"hours": 1}) == [
            {"field_name": "hours", "old_value": "", "new_value": "1"}
        ]
        assert snapshot_changes({"hours": 1}, None) == [
            {"field_name": "hours", "old_value": "1", "new_value": ""}
        ]
