"""Gmail send as the instance's Workspace user, via domain-wide delegation.

The one application email sender (ADR 0039). Deliberately narrow — plain-text
send only, used today by the password-reset flow; a general email feature is a
future slice and extends this module rather than growing a sibling. Delivery
proven by the delegation probe of 2026-08-31 (gmail.send scope, service
account impersonating the Workspace user).

It also reads one message back, for the E2E proof that a sent email arrives
with a link that works (``latest_message_body``). Nothing the product does for
a user reads mail.
"""

import base64
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default as default_policy
from typing import TYPE_CHECKING

from googleapiclient.discovery import build

from apps.platform.integrations.google.credentials import delegated_credentials, delegated_subject

if TYPE_CHECKING:
    from googleapiclient._apis.gmail.v1.resources import GmailResource

logger = logging.getLogger(__name__)

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
#: drafts.create needs more than send: gmail.send is send-only by design.
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
#: Reading a mailbox back. Delegation matches scope strings literally, so the
#: Workspace grant has to name this one as well as the two above.
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def _build_gmail(scopes: list[str], subject: str) -> "GmailResource":
    """Build the one Gmail client, as a named Workspace user.

    Both arguments are required: the two callers want different scopes and
    different mailboxes, so a default would only encode one of them as the
    normal case.

    Fable: ``cache_discovery=False`` matches every other googleapiclient
    build here — the discovery cache wants oauth2client and logs a warning
    per client without it.
    """
    return build(
        "gmail",
        "v1",
        credentials=delegated_credentials(scopes, subject),
        cache_discovery=False,
    )


def send_company_email(to: str, subject: str, body: str, *, company_email: str | None) -> str:
    """Send a plain-text email from the instance's Workspace user; return the Gmail message id.

    No try/except: a failed send is the caller's operation failing (fail
    early) — let it raise and the envelope persist it. Gmail stamps the
    authenticated user as From regardless; the explicit header keeps the
    stored copy honest.
    """
    sender = delegated_subject(company_email)
    message = EmailMessage()
    message["To"] = to
    message["From"] = sender
    message["Subject"] = subject
    message.set_content(body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    gmail = _build_gmail([GMAIL_SEND_SCOPE], sender)
    result = gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
    message_id: str = result["id"]
    logger.info("EMAIL SENT - to=%s subject=%s gmail_id=%s", to, subject, message_id)
    return message_id


def latest_message_body(*, mailbox: str, to: str, subject: str, since: datetime) -> str | None:
    """Return the plain-text body of the newest matching message in ``mailbox``, or None.

    A match is addressed to ``to``, carries ``subject``, arrived at or after
    ``since`` and sits in the mailbox's INBOX. ``mailbox`` is the Workspace user
    whose mail is read: a plus-addressed recipient (``name+tag@``) lands in
    ``name@``'s mailbox, so the two differ. None means nothing has arrived yet;
    the caller polls.

    The time bound matters because the mailbox outlives every database
    restore: without it an earlier run's message, whose link is long dead,
    is the newest match.

    The INBOX bound matters because the sender and the mailbox can be the same
    Workspace user — the E2E workshop address is a plus-address of it — and
    Gmail then stores a SENT copy beside the delivered one. Reading that copy
    would prove the send, not the arrival, which is the only thing worth
    proving here.
    """
    gmail = _build_gmail([GMAIL_READONLY_SCOPE], mailbox)
    query = f'to:{to} subject:"{subject}" after:{int(since.timestamp())}'
    # Gmail lists newest first.
    listed = (
        gmail.users()
        .messages()
        .list(userId="me", q=query, labelIds=["INBOX"], maxResults=1)
        .execute()
    )
    matches = listed.get("messages", [])
    if not matches:
        return None
    fetched = gmail.users().messages().get(userId="me", id=matches[0]["id"], format="raw").execute()
    message = message_from_bytes(base64.urlsafe_b64decode(fetched["raw"]), policy=default_policy)
    body = message.get_body(preferencelist=("plain",))
    if body is None:
        raise ValueError(f"Message {matches[0]['id']} to {to} has no plain-text body")
    content: str = body.get_content()
    return content


@dataclass(frozen=True, slots=True)
class Attachment:
    """One file to hang off a message."""

    filename: str
    content: bytes
    mime_type: str


@dataclass(frozen=True, slots=True)
class GmailDraft:
    """A draft waiting in someone's mailbox, and where to open it."""

    draft_id: str
    web_url: str


def create_draft(
    *,
    as_user: str,
    to: str,
    subject: str,
    body: str,
    attachments: "Sequence[Attachment]" = (),
) -> GmailDraft:
    """Create a draft in ``as_user``'s own mailbox and return where to open it.

    A draft rather than a send: an order going to a supplier is reviewed by the
    person sending it, and this puts the message where they will look for it
    rather than in a shared mailbox they may not open.

    It also carries attachments, which is the whole reason it exists. The
    mailto: link this replaces could not — it composed a message saying "please
    find attached" and then attached nothing, leaving the operator to find the
    PDF and hang it on by hand.

    No try/except: a failed draft is the caller's operation failing (fail
    early), and the envelope persists it.
    """
    message = EmailMessage()
    message["To"] = to
    message["From"] = as_user
    message["Subject"] = subject
    message.set_content(body)
    for attachment in attachments:
        maintype, _, subtype = attachment.mime_type.partition("/")
        message.add_attachment(
            attachment.content,
            maintype=maintype,
            subtype=subtype,
            filename=attachment.filename,
        )

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    gmail = _build_gmail([GMAIL_COMPOSE_SCOPE], as_user)
    created = gmail.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()

    draft_id: str = created["id"]
    # Gmail opens a draft by its MESSAGE id, not the draft id.
    message_id: str = created["message"]["id"]
    # /u/<address>/ rather than /u/0/: the digit is the browser's account
    # INDEX, so on an operator signed into a personal account first, /u/0/
    # opens the wrong mailbox and the draft appears to be missing. Gmail
    # accepts the address in that position and selects the right session.
    logger.info(
        "EMAIL DRAFTED - as=%s to=%s subject=%s draft=%s attachments=%s",
        as_user,
        to,
        subject,
        draft_id,
        len(attachments),
    )
    return GmailDraft(
        draft_id=draft_id,
        web_url=f"https://mail.google.com/mail/u/{as_user}/#drafts?compose={message_id}",
    )
