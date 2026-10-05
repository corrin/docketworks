"""Unit tests for the Gmail sender's message construction.

The mocked googleapiclient boundary pins what this module controls — the
encoded RFC 822 message and the send wiring. Real delivery is the
integration test's job (ADR 0050): a fake here can only confirm what we
already assume about Gmail.
"""

import base64
from datetime import UTC, datetime
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default as default_policy

import pytest

from apps.platform.integrations.google import gmail


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
        monkeypatch.delenv("GCP_DELEGATED_SUBJECT", raising=False)

        message_id = gmail.send_company_email(
            "person@example.com",
            "Reset your password",
            "The link is inside.",
            company_email="office@example.com",
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


class FakeExecute[T]:
    def __init__(self, result: T) -> None:
        self._result = result

    def execute(self) -> T:
        return self._result


class FakeReadMessages:
    """A mailbox holding the messages it was given, newest first, as Gmail lists them."""

    def __init__(self, stored: dict[str, bytes], calls: dict[str, str]) -> None:
        self._stored = stored
        self._calls = calls

    def list(
        self,
        userId: str,  # noqa: N803 - Google's casing
        q: str,
        maxResults: int,  # noqa: N803 - Google's casing
    ) -> FakeExecute[dict[str, list[dict[str, str]]]]:
        self._calls["list_user"] = userId
        self._calls["query"] = q
        ids = [{"id": message_id} for message_id in self._stored][:maxResults]
        return FakeExecute({"messages": ids} if ids else {})

    def get(
        self,
        userId: str,  # noqa: N803 - Google's casing
        id: str,
        format: str,
    ) -> FakeExecute[dict[str, str]]:
        self._calls["get_user"] = userId
        self._calls["format"] = format
        return FakeExecute({"raw": base64.urlsafe_b64encode(self._stored[id]).decode()})


class FakeReadUsers:
    def __init__(self, messages: FakeReadMessages) -> None:
        self._messages = messages

    def messages(self) -> FakeReadMessages:
        return self._messages


class FakeReadGmail:
    def __init__(self, messages: FakeReadMessages) -> None:
        self._messages = messages

    def users(self) -> FakeReadUsers:
        return FakeReadUsers(self._messages)


def _plain_email(body: str) -> bytes:
    message = EmailMessage()
    message["To"] = "person+e2e@example.com"
    message["Subject"] = "Reset your password"
    message.set_content(body)
    return message.as_bytes()


class TestLatestMessageBody:
    def _read(
        self, monkeypatch: pytest.MonkeyPatch, stored: dict[str, bytes]
    ) -> tuple[str | None, dict[str, str], list[tuple[list[str], str]]]:
        calls: dict[str, str] = {}
        built: list[tuple[list[str], str]] = []

        def fake_build(scopes: list[str], subject: str) -> FakeReadGmail:
            built.append((scopes, subject))
            return FakeReadGmail(FakeReadMessages(stored, calls))

        monkeypatch.setattr(gmail, "_build_gmail", fake_build)
        body = gmail.latest_message_body(
            mailbox="person@example.com",
            to="person+e2e@example.com",
            subject="Reset your password",
            since=datetime(2026, 10, 5, 1, 0, tzinfo=UTC),
        )
        return body, calls, built

    def test_reads_the_newest_match_from_the_mailbox_owner_s_mail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stored = {
            "newest": _plain_email("Use this link: https://app.example/reset"),
            "older": _plain_email("An earlier run's link"),
        }

        body, calls, built = self._read(monkeypatch, stored)

        assert body is not None and "https://app.example/reset" in body
        # Read-only scope, as the mailbox's owner: a plus-addressed recipient
        # is not a Workspace user and cannot be impersonated.
        assert built == [([gmail.GMAIL_READONLY_SCOPE], "person@example.com")]
        assert (calls["list_user"], calls["get_user"], calls["format"]) == ("me", "me", "raw")
        # The time bound is what keeps a previous run's dead link out.
        assert calls["query"] == (
            'to:person+e2e@example.com subject:"Reset your password" after:1791162000'
        )

    def test_is_none_until_a_message_arrives(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body, _calls, _built = self._read(monkeypatch, {})

        assert body is None
