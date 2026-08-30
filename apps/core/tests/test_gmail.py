"""Unit tests for the Gmail sender's message construction.

The mocked googleapiclient boundary pins what this module controls — the
encoded RFC 822 message and the send wiring. Real delivery is the
integration test's job (ADR 0050): a fake here can only confirm what we
already assume about Gmail.
"""

import base64
from email import message_from_bytes

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


class FakeUsers:
    def __init__(self, raw_sink: dict[str, str]) -> None:
        self._raw_sink = raw_sink

    def messages(self) -> FakeMessages:
        return FakeMessages(self._raw_sink)


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
        monkeypatch.setattr(gmail, "_build_gmail", lambda: FakeGmail(sent))
        monkeypatch.setattr(gmail, "delegated_subject", lambda: "office@example.com")

        message_id = gmail.send_company_email(
            "person@example.com", "Reset your password", "The link is inside."
        )

        assert message_id == "gmail-message-id-1"
        assert sent["userId"] == "me"
        parsed = message_from_bytes(base64.urlsafe_b64decode(sent["raw"]))
        assert parsed["To"] == "person@example.com"
        assert parsed["From"] == "office@example.com"
        assert parsed["Subject"] == "Reset your password"
        assert "The link is inside." in parsed.get_payload()
