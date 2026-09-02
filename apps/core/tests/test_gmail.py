"""Unit tests for the Gmail sender's message construction.

The mocked googleapiclient boundary pins what this module controls — the
encoded RFC 822 message and the send wiring. Real delivery is the
integration test's job (ADR 0050): a fake here can only confirm what we
already assume about Gmail.
"""

import base64
from email import message_from_bytes
from email.policy import default as default_policy

import pytest

from apps.core import gmail


class FakeSend:
    def __init__(self, raw_sink: dict[str, str]) -> None:
        self._raw_sink = raw_sink

    def execute(self) -> dict[str, str]:
        return {"id": "gmail-message-id-1"}


class FakeMessages:
    def __init__(self, raw_sink: dict[str, str]) -> None:
        self._raw_sink = raw_sink

    def send(self, userId: str, body: dict[str, str]) -> FakeSend:  # noqa: N803 - Google's casing
        self._raw_sink["userId"] = userId
        self._raw_sink["raw"] = body["raw"]
        return FakeSend(self._raw_sink)


class FakeDraftCreate:
    def execute(self) -> dict[str, str | dict[str, str]]:
        return {"id": "draft-id-1", "message": {"id": "gmail-message-id-1"}}


class FakeDrafts:
    def __init__(self, raw_sink: dict[str, str]) -> None:
        self._raw_sink = raw_sink

    def create(
        self,
        userId: str,  # noqa: N803 - Google's casing
        body: dict[str, dict[str, str]],
    ) -> FakeDraftCreate:
        self._raw_sink["userId"] = userId
        self._raw_sink["raw"] = body["message"]["raw"]
        return FakeDraftCreate()


class FakeUsers:
    def __init__(self, raw_sink: dict[str, str]) -> None:
        self._raw_sink = raw_sink

    def messages(self) -> FakeMessages:
        return FakeMessages(self._raw_sink)

    def drafts(self) -> FakeDrafts:
        return FakeDrafts(self._raw_sink)


class FakeGmail:
    def __init__(self, raw_sink: dict[str, str]) -> None:
        self._raw_sink = raw_sink

    def users(self) -> FakeUsers:
        return FakeUsers(self._raw_sink)


class TestSendCompanyEmail:
    def test_sends_the_encoded_message_as_the_delegated_subject(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent: dict[str, str] = {}
        built: list[tuple[list[str], str]] = []

        def fake_build(scopes: list[str], subject: str) -> FakeGmail:
            built.append((scopes, subject))
            return FakeGmail(sent)

        monkeypatch.setattr(gmail, "_build_gmail", fake_build)
        monkeypatch.setattr(gmail, "delegated_subject", lambda: "office@example.com")

        message_id = gmail.send_company_email(
            "person@example.com", "Reset your password", "The link is inside."
        )

        assert message_id == "gmail-message-id-1"
        # The builder takes no defaults, so what a caller asks for is a contract
        # worth asserting: send-only scope, the company mailbox.
        assert built == [([gmail.GMAIL_SEND_SCOPE], "office@example.com")]
        assert sent["userId"] == "me"
        parsed = message_from_bytes(base64.urlsafe_b64decode(sent["raw"]))
        assert parsed["To"] == "person@example.com"
        assert parsed["From"] == "office@example.com"
        assert parsed["Subject"] == "Reset your password"
        assert "The link is inside." in parsed.get_payload()


class TestCreateDraft:
    """What the draft is made of, which CI can check without a network.

    The integration test proves Gmail accepts it; nothing in CI ran against
    this module until a required-argument change to ``_build_gmail`` broke the
    send test and revealed the draft path had no unit guard at all.
    """

    def test_the_draft_carries_the_attachment_and_opens_at_the_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent: dict[str, str] = {}
        built: list[tuple[list[str], str]] = []

        def fake_build(scopes: list[str], subject: str) -> FakeGmail:
            built.append((scopes, subject))
            return FakeGmail(sent)

        monkeypatch.setattr(gmail, "_build_gmail", fake_build)

        draft = gmail.create_draft(
            as_user="olive@example.com",
            to="sales@supplier.example",
            subject="Purchase Order PO-1234",
            body="Order attached.",
            attachments=[
                gmail.Attachment(
                    filename="Purchase_Order_PO-1234.pdf",
                    content=b"%PDF-1.4 not really",
                    mime_type="application/pdf",
                )
            ],
        )

        # gmail.send cannot reach drafts, and the mailbox is the operator's own
        # rather than the company's — both are the point of this path.
        assert built == [([gmail.GMAIL_COMPOSE_SCOPE], "olive@example.com")]
        assert draft.draft_id == "draft-id-1"
        assert draft.web_url.endswith("gmail-message-id-1"), "opens some other message"
        # The account selector is an index unless it is given an address, and
        # index 0 is whichever account the operator signed into first.
        assert "/mail/u/olive@example.com/" in draft.web_url, "opens some other mailbox"

        parsed = message_from_bytes(base64.urlsafe_b64decode(sent["raw"]), policy=default_policy)
        assert parsed["To"] == "sales@supplier.example"
        assert parsed["From"] == "olive@example.com"
        attached = list(parsed.iter_attachments())
        assert [part.get_filename() for part in attached] == ["Purchase_Order_PO-1234.pdf"]
        assert attached[0].get_payload(decode=True) == b"%PDF-1.4 not really"
