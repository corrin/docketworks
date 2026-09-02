"""Gmail send as the instance's Workspace user, via domain-wide delegation.

The one application email sender (ADR 0039). Deliberately narrow — plain-text
send only, used today by the password-reset flow; a general email feature is a
future slice and extends this module rather than growing a sibling. Delivery
proven by the delegation probe of 2026-08-31 (gmail.send scope, service
account impersonating the Workspace user).
"""

import base64
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from typing import TYPE_CHECKING

from googleapiclient.discovery import build

from apps.core.gauth import delegated_credentials, delegated_subject

if TYPE_CHECKING:
    from googleapiclient._apis.gmail.v1.resources import GmailResource

logger = logging.getLogger(__name__)

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
#: drafts.create needs more than send: gmail.send is send-only by design.
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"


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


def send_company_email(to: str, subject: str, body: str) -> str:
    """Send a plain-text email from the instance's Workspace user; return the Gmail message id.

    No try/except: a failed send is the caller's operation failing (fail
    early) — let it raise and the envelope persist it. Gmail stamps the
    authenticated user as From regardless; the explicit header keeps the
    stored copy honest.
    """
    sender = delegated_subject()
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
