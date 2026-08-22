"""archive_contacts_in_xero: batching, per-element refusals, malformed answers, status contract."""

from typing import ClassVar, Protocol

import pytest

from apps.xero import contacts as contacts_module
from apps.xero import seeding as seeding_module
from apps.xero.constants import XERO_BATCH_SIZE
from apps.xero.seeding import get_all_xero_contacts


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
