"""The delegated Gmail send, read-back and draft against the real API (ADR 0050).

Real messages and one real draft, all addressed to the delegated subject
itself so the probe stays inside the instance's own mailbox. On a dev box the dev database's
``company_email`` is a demo placeholder, so this needs ``GCP_CREDENTIALS``
and ``GCP_DELEGATED_SUBJECT`` in the environment — the builders fail loud
naming exactly what is missing.
"""

import time
from base64 import urlsafe_b64decode
from datetime import UTC, datetime, timedelta
from email import message_from_bytes
from email.policy import default as default_policy
from io import BytesIO

import pytest
from reportlab.pdfgen.canvas import Canvas

from apps.platform.integrations.google.credentials import delegated_subject
from apps.platform.integrations.google.gmail import (
    GMAIL_COMPOSE_SCOPE,
    Attachment,
    _build_gmail,
    create_draft,
    latest_message_body,
    send_company_email,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


class TestGmailSend:
    def test_a_real_send_is_accepted(self, company_email: str | None) -> None:
        recipient = delegated_subject(company_email)

        message_id = send_company_email(
            company_email=company_email,
            to=recipient,
            subject="DocketWorks integration test — please ignore",
            body=(
                "Sent by apps/platform/integrations/tests/test_gmail_integration.py to prove "
                "the delegated gmail.send path end to end."
            ),
        )

        assert message_id != ""


class TestGmailReadBack:
    """A sent message can be read back from the mailbox it lands in.

    This is the gmail.readonly grant, which the product never uses for a user:
    it exists so the E2E reset spec can follow the emailed link. Delivery is
    Gmail's clock, so the read is polled.
    """

    def test_a_sent_message_is_read_back_from_its_mailbox(self, company_email: str | None) -> None:
        mailbox = delegated_subject(company_email)
        marker = f"read-back {datetime.now(tz=UTC).isoformat()}"
        subject = "DocketWorks integration test — read back, please ignore"
        # Gmail's `after:` is whole seconds; step back so the send is inside it.
        since = datetime.now(tz=UTC) - timedelta(seconds=5)
        send_company_email(company_email=company_email, to=mailbox, subject=subject, body=marker)

        deadline = time.monotonic() + 60
        body = latest_message_body(mailbox=mailbox, to=mailbox, subject=subject, since=since)
        while body is None and time.monotonic() < deadline:
            time.sleep(3)
            body = latest_message_body(mailbox=mailbox, to=mailbox, subject=subject, since=since)

        assert body is not None, f"the message did not reach {mailbox} within 60s"
        assert marker in body


class TestGmailDraft:
    """The draft path, which carries an attachment the send path cannot.

    Read back through ``drafts.get(format="raw")`` rather than
    ``messages.get``: the production scope is gmail.compose, which reaches
    drafts and nothing else, so a test that needed messages.get would be
    proving a scope the application does not hold.
    """

    def test_a_real_draft_carries_the_pdf(self, company_email: str | None) -> None:
        subject_user = delegated_subject(company_email)
        pdf = BytesIO()
        canvas = Canvas(pdf)
        canvas.drawString(100, 750, "DocketWorks integration test")
        canvas.save()

        draft = create_draft(
            as_user=subject_user,
            to=subject_user,
            subject="DocketWorks integration test — please ignore",
            body="Created by apps/platform/integrations/tests/test_gmail_integration.py.",
            attachments=[
                Attachment(
                    filename="Purchase_Order_TEST.pdf",
                    content=pdf.getvalue(),
                    mime_type="application/pdf",
                )
            ],
        )

        gmail = _build_gmail([GMAIL_COMPOSE_SCOPE], subject_user)
        stored = gmail.users().drafts().get(userId="me", id=draft.draft_id, format="raw").execute()
        message = message_from_bytes(
            urlsafe_b64decode(stored["message"]["raw"]), policy=default_policy
        )
        attached = list(message.iter_attachments())

        assert draft.web_url.endswith(stored["message"]["id"]), "opens some other message"
        assert [part.get_filename() for part in attached] == ["Purchase_Order_TEST.pdf"]
        assert attached[0].get_content_type() == "application/pdf"
        assert attached[0].get_payload(decode=True) == pdf.getvalue(), "the PDF was mangled"

        # Deleted only once the assertions pass: a surviving draft in the
        # mailbox is the diagnostic for a failure here.
        gmail.users().drafts().delete(userId="me", id=draft.draft_id).execute()
