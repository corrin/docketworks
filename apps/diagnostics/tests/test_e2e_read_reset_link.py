"""The reset-link reader is a subprocess contract: one JSON line the spec parses."""

import json
from datetime import datetime
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import CommandError, call_command

from apps.accounts.tasks import RESET_EMAIL_SUBJECT
from apps.diagnostics.management.commands import e2e_read_reset_link
from apps.diagnostics.management.commands.e2e_read_reset_link import reset_link_in

pytestmark = pytest.mark.django_db

LINK = "https://app.example/reset-password?uid=abc&token=def-123"
BODY = (
    "Someone asked to reset the DocketWorks password for person+e2e@example.com.\n\n"
    f"Use this link to choose a new password:\n\n{LINK}\n\n"
    "If you did not ask for this, you can ignore this email.\n"
)


def _run(
    monkeypatch: pytest.MonkeyPatch,
    body: str | None,
    *,
    since: str,
    arrives_on_read: int = 1,
    wait: int = 0,
) -> str:
    asked: dict[str, object] = {}
    reads = 0
    clock = 0.0

    def fake_read(*, mailbox: str, to: str, subject: str, since: datetime) -> str | None:
        nonlocal reads
        reads += 1
        asked.update(mailbox=mailbox, to=to, subject=subject, since=since)
        return body if reads >= arrives_on_read else None

    def fake_sleep(seconds: float) -> None:
        nonlocal clock
        clock += seconds

    monkeypatch.setattr(e2e_read_reset_link, "latest_message_body", fake_read)
    monkeypatch.setattr(
        e2e_read_reset_link, "time", SimpleNamespace(sleep=fake_sleep, monotonic=lambda: clock)
    )
    out = StringIO()
    call_command(
        "e2e_read_reset_link",
        "--to=person+e2e@example.com",
        "--mailbox=person@example.com",
        f"--since={since}",
        f"--wait={wait}",
        stdout=out,
    )
    # The subject the email is sent under, not a second copy of it.
    assert asked["subject"] == RESET_EMAIL_SUBJECT
    return out.getvalue()


def test_prints_the_link_from_the_email_as_one_json_line(monkeypatch: pytest.MonkeyPatch) -> None:
    output = _run(monkeypatch, BODY, since="2026-10-05T14:00:00+13:00")

    assert json.loads(output.strip().splitlines()[-1]) == {"link": LINK}


def test_prints_null_while_the_email_has_not_arrived(monkeypatch: pytest.MonkeyPatch) -> None:
    output = _run(monkeypatch, None, since="2026-10-05T14:00:00+13:00")

    assert json.loads(output.strip().splitlines()[-1]) == {"link": None}


def test_waiting_reads_again_until_the_email_arrives(monkeypatch: pytest.MonkeyPatch) -> None:
    # One process polls: the spec paid Django's start-up on every read.
    output = _run(monkeypatch, BODY, since="2026-10-05T14:00:00+13:00", arrives_on_read=3, wait=90)

    assert json.loads(output.strip().splitlines()[-1]) == {"link": LINK}


def test_waiting_gives_up_with_null_when_the_wait_is_over(monkeypatch: pytest.MonkeyPatch) -> None:
    output = _run(monkeypatch, None, since="2026-10-05T14:00:00+13:00", wait=10)

    assert json.loads(output.strip().splitlines()[-1]) == {"link": None}


def test_refuses_a_timestamp_with_no_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    # A naive time would be read in the server's zone and could admit a
    # previous run's email.
    with pytest.raises(CommandError, match="offset"):
        _run(monkeypatch, BODY, since="2026-10-05T14:00:00")


def test_an_email_without_exactly_one_link_is_an_error() -> None:
    with pytest.raises(ValueError, match="found 0"):
        reset_link_in("No link here.")
    with pytest.raises(ValueError, match="found 2"):
        reset_link_in(f"{LINK}\n{LINK}")
