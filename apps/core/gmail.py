"""Gmail send as the instance's Workspace user, via domain-wide delegation.

The one application email sender (ADR 0039). Deliberately narrow — plain-text
send only, used today by the password-reset flow; a general email feature is a
future slice and extends this module rather than growing a sibling. Delivery
proven by the delegation probe of 2026-08-31 (gmail.send scope, service
account impersonating the Workspace user).
"""

import base64
import logging
from email.message import EmailMessage
from typing import TYPE_CHECKING

from googleapiclient.discovery import build

from apps.core.gauth import delegated_credentials, delegated_subject

if TYPE_CHECKING:
    from googleapiclient._apis.gmail.v1.resources import GmailResource

logger = logging.getLogger(__name__)

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


def _build_gmail() -> "GmailResource":
    """Build the one Gmail client.

    Fable: ``cache_discovery=False`` matches every other googleapiclient
    build here — the discovery cache wants oauth2client and logs a warning
    per client without it.
    """
    return build(
        "gmail", "v1", credentials=delegated_credentials([GMAIL_SEND_SCOPE]), cache_discovery=False
    )


def send_company_email(to: str, subject: str, body: str) -> str:
    """Send a plain-text email from the instance's Workspace user; return the Gmail message id.

    No try/except: a failed send is the caller's operation failing (fail
    early) — let it raise and the envelope persist it. Gmail stamps the
    authenticated user as From regardless; the explicit header keeps the
    stored copy honest.
    """
    message = EmailMessage()
    message["To"] = to
    message["From"] = delegated_subject()
    message["Subject"] = subject
    message.set_content(body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    result = _build_gmail().users().messages().send(userId="me", body={"raw": raw}).execute()
    message_id: str = result["id"]
    logger.info("EMAIL SENT - to=%s subject=%s gmail_id=%s", to, subject, message_id)
    return message_id
