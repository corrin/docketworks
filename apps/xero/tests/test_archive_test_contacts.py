"""The archive_test_contacts command and the archive seam it drives."""

from io import StringIO
from typing import ClassVar, Protocol

import pytest
from django.core.management import call_command

from apps.xero import contacts as contacts_module
from apps.xero import seeding as seeding_module
from apps.xero.constants import XERO_BATCH_SIZE
from apps.xero.contacts import ArchiveOutcome
from apps.xero.management.commands import archive_test_contacts as command_module
from apps.xero.management.commands.archive_test_contacts import active_e2e_contacts
from apps.xero.seeding import XeroContactRef, get_all_xero_contacts


def _ref(name: str, status: str = "ACTIVE") -> XeroContactRef:
    return XeroContactRef(name=name, contact_id=f"id-{name}", contact_status=status)


CONTACTS = [
    _ref("[TEST] Supplier 1"),
    _ref("E2E Test Client 2"),
    _ref("[TEST] Already Archived", status="ARCHIVED"),
    _ref("ABC Carpet Cleaning TEST IGNORE"),
    _ref("Real Customer Ltd"),
]


def test_only_active_e2e_residue_is_selected() -> None:
    """The standing company, real customers and already-archived contacts are never touched."""
    chosen = {contact.name for contact in active_e2e_contacts(CONTACTS)}

    assert chosen == {"[TEST] Supplier 1", "E2E Test Client 2"}


@pytest.fixture
def xero(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """A fake organisation: no guard trips, and every archive call is recorded."""
    archived: list[list[str]] = []
    monkeypatch.setattr(command_module, "get_all_xero_contacts", lambda: CONTACTS)
    monkeypatch.setattr(command_module, "assert_not_production_target", lambda: None)
    monkeypatch.setattr(command_module, "assert_xero_writes_enabled", lambda _operation: None)

    def record(contact_ids: list[str]) -> ArchiveOutcome:
        archived.append(list(contact_ids))
        return ArchiveOutcome(archived=tuple(contact_ids), refused={})

    monkeypatch.setattr(command_module, "archive_contacts_in_xero", record)
    return archived


def _run(*args: str) -> str:
    out = StringIO()
    call_command("archive_test_contacts", *args, stdout=out)
    return out.getvalue()


def test_dry_run_archives_nothing(xero: list[list[str]]) -> None:
    """An inspection without --confirm must never become a write to the organisation."""
    _run()

    assert xero == []


def test_confirm_archives_exactly_the_residue(xero: list[list[str]]) -> None:
    """Everything selected is archived, and nothing else is."""
    _run("--confirm")

    assert xero == [["id-[TEST] Supplier 1", "id-E2E Test Client 2"]]


def test_a_refusal_is_reported_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator learns which contact Xero would not archive, and why."""
    monkeypatch.setattr(command_module, "get_all_xero_contacts", lambda: CONTACTS)
    monkeypatch.setattr(command_module, "assert_not_production_target", lambda: None)
    monkeypatch.setattr(command_module, "assert_xero_writes_enabled", lambda _operation: None)
    monkeypatch.setattr(
        command_module,
        "archive_contacts_in_xero",
        lambda ids: ArchiveOutcome(
            archived=(ids[0],), refused={ids[1]: "Contact has outstanding transactions"}
        ),
    )

    output = _run("--confirm")

    assert "E2E Test Client 2: Contact has outstanding transactions" in output


def test_production_target_is_refused_before_the_organisation_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard runs first, so a production tenant is never even listed."""

    def refuse() -> None:
        raise ValueError("production tenant")

    monkeypatch.setattr(command_module, "assert_not_production_target", refuse)

    def unreachable() -> list[XeroContactRef]:
        raise AssertionError("the organisation must not be read on a refused target")

    monkeypatch.setattr(command_module, "get_all_xero_contacts", unreachable)

    with pytest.raises(ValueError, match="production tenant"):
        _run("--confirm")


class _ContactLike(Protocol):
    contact_id: str
    contact_status: str


class _Message:
    def __init__(self, message: str) -> None:
        self.message = message


class _ReturnedContact:
    """The per-element answer Xero gives with summarize_errors off."""

    def __init__(self, contact_id: str, status: str, refusal: str | None = None) -> None:
        self.contact_id = contact_id
        self.contact_status = status
        self.has_validation_errors = refusal is not None
        self.validation_errors = [_Message(refusal)] if refusal is not None else []


class _Response:
    def __init__(self, contacts: list[_ContactLike]) -> None:
        self.contacts = contacts


class _FakeAccountingApi:
    """Answers update_or_create_contacts the way the test configures it."""

    calls: ClassVar[list[list[str]]] = []
    answer_status: ClassVar[str] = "ARCHIVED"
    refuse_ids: ClassVar[dict[str, str]] = {}
    summarize_errors_seen: ClassVar[list[object]] = []

    def __init__(self, _client: object) -> None:
        pass

    def update_or_create_contacts(
        self, _tenant_id: str, contacts: dict[str, list[_ContactLike]], **kwargs: object
    ) -> _Response:
        ids = [contact.contact_id for contact in contacts["contacts"]]
        _FakeAccountingApi.calls.append(ids)
        _FakeAccountingApi.summarize_errors_seen.append(kwargs.get("summarize_errors"))
        return _Response(
            [
                _ReturnedContact(contact_id, self.answer_status, self.refuse_ids.get(contact_id))
                for contact_id in ids
            ]
        )


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> type[_FakeAccountingApi]:
    _FakeAccountingApi.calls = []
    _FakeAccountingApi.answer_status = "ARCHIVED"
    _FakeAccountingApi.refuse_ids = {}
    _FakeAccountingApi.summarize_errors_seen = []
    monkeypatch.setattr(contacts_module, "AccountingApi", _FakeAccountingApi)
    monkeypatch.setattr(contacts_module, "get_api_client", object)
    monkeypatch.setattr(contacts_module, "get_tenant_id", lambda: "tenant")
    return _FakeAccountingApi


def test_archive_batches_at_xeros_limit(fake_api: type[_FakeAccountingApi]) -> None:
    """One more id than a batch holds costs exactly one more request."""
    ids = [f"id-{n}" for n in range(XERO_BATCH_SIZE + 1)]

    outcome = contacts_module.archive_contacts_in_xero(ids)

    assert len(outcome.archived) == XERO_BATCH_SIZE + 1
    assert [len(call) for call in fake_api.calls] == [XERO_BATCH_SIZE, 1]


def test_a_refused_contact_does_not_poison_its_batch(fake_api: type[_FakeAccountingApi]) -> None:
    """Errors are asked for per element, so one contact with transactions costs only itself."""
    fake_api.refuse_ids = {"id-2": "Contact has outstanding transactions"}

    outcome = contacts_module.archive_contacts_in_xero(["id-1", "id-2", "id-3"])

    assert outcome.archived == ("id-1", "id-3")
    assert outcome.refused == {"id-2": "Contact has outstanding transactions"}
    assert fake_api.summarize_errors_seen == [False]


def test_archive_refuses_a_malformed_answer(fake_api: type[_FakeAccountingApi]) -> None:
    """A contact Xero neither archived nor refused is not a success."""
    fake_api.answer_status = "ACTIVE"

    with pytest.raises(ValueError, match="neither archived nor refused"):
        contacts_module.archive_contacts_in_xero(["id-1"])


def test_listing_refuses_a_contact_status_xero_does_not_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A status outside ACTIVE/ARCHIVED (GDPRREQUEST) is refused, never silently skipped."""

    class _Contact:
        name = "[TEST] Erased"
        contact_id = "id-erased"
        contact_status = "GDPRREQUEST"

    class _Api:
        def __init__(self, _client: object) -> None:
            pass

        def get_contacts(self, _tenant_id: str, **_kwargs: object) -> _Response:
            return _Response([_Contact()])

    monkeypatch.setattr(seeding_module, "AccountingApi", _Api)
    monkeypatch.setattr(seeding_module, "get_api_client", object)
    monkeypatch.setattr(seeding_module, "get_tenant_id", lambda: "tenant")

    with pytest.raises(ValueError, match="GDPRREQUEST"):
        get_all_xero_contacts()
