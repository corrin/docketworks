"""The archive_test_contacts command: selection, dry run, confirm, guards."""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.xero.management.commands import archive_test_contacts as command_module
from apps.xero.management.commands.archive_test_contacts import active_e2e_contacts
from apps.xero.seeding import XeroContactRef

COMMAND = "apps.xero.management.commands.archive_test_contacts"


def _ref(name: str, status: str = "ACTIVE") -> XeroContactRef:
    return XeroContactRef(name=name, contact_id=f"id-{name}", contact_status=status)


CONTACTS = [
    _ref("[TEST] Supplier 1"),
    _ref("E2E Test Client 2"),
    _ref("[TEST] Already Archived", status="ARCHIVED"),
    _ref("ABC Carpet Cleaning TEST IGNORE"),
    _ref("Real Customer Ltd"),
]


def test_selects_active_e2e_named_contacts_only() -> None:
    chosen = active_e2e_contacts(CONTACTS)

    assert [contact.name for contact in chosen] == ["[TEST] Supplier 1", "E2E Test Client 2"]


@pytest.fixture
def xero(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """A fake organisation: no guard trips, and every archive call is recorded."""
    archived: list[list[str]] = []
    monkeypatch.setattr(command_module, "get_all_xero_contacts", lambda: CONTACTS)
    monkeypatch.setattr(command_module, "assert_not_production_target", lambda: None)
    monkeypatch.setattr(command_module, "assert_xero_writes_enabled", lambda _operation: None)

    def record(contact_ids: list[str]) -> int:
        archived.append(list(contact_ids))
        return len(contact_ids)

    monkeypatch.setattr(command_module, "archive_contacts_in_xero", record)
    return archived


def _run(*args: str) -> str:
    out = StringIO()
    call_command("archive_test_contacts", *args, stdout=out)
    return out.getvalue()


def test_dry_run_reports_and_archives_nothing(xero: list[list[str]]) -> None:
    output = _run()

    assert "[TEST] Supplier 1" in output
    assert "DRY RUN" in output
    assert xero == []


def test_confirm_archives_exactly_the_selected_contacts(xero: list[list[str]]) -> None:
    output = _run("--confirm")

    assert xero == [["id-[TEST] Supplier 1", "id-E2E Test Client 2"]]
    assert "Archived 2" in output


def test_nothing_to_archive_is_a_clean_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(command_module, "get_all_xero_contacts", lambda: [_ref("Real Customer")])
    monkeypatch.setattr(command_module, "assert_not_production_target", lambda: None)
    monkeypatch.setattr(command_module, "assert_xero_writes_enabled", lambda _operation: None)

    def refuse(_ids: list[str]) -> int:
        raise AssertionError("nothing should be archived")

    monkeypatch.setattr(command_module, "archive_contacts_in_xero", refuse)

    assert "Active E2E contacts in Xero: 0" in _run("--confirm")


def test_production_target_is_refused_before_any_read(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse() -> None:
        raise ValueError("production tenant")

    monkeypatch.setattr(command_module, "assert_not_production_target", refuse)

    def unreachable() -> list[XeroContactRef]:
        raise AssertionError("the organisation must not be read on a refused target")

    monkeypatch.setattr(command_module, "get_all_xero_contacts", unreachable)

    with pytest.raises(ValueError, match="production tenant"):
        _run("--confirm")
