"""The delegated Gmail send and draft against the real API (ADR 0050).

One real message and one real draft, both addressed to the delegated subject
itself so the probe stays inside the instance's own mailbox. On a dev box the dev database's
``company_email`` is a demo placeholder, so this needs ``GCP_CREDENTIALS``
and ``GCP_DELEGATED_SUBJECT`` in the environment — the builders fail loud
naming exactly what is missing.
"""

from base64 import urlsafe_b64decode
from email import message_from_bytes
from email.policy import default as default_policy
from io import BytesIO

import pytest
from reportlab.pdfgen.canvas import Canvas

from apps.core.gauth import delegated_subject
from apps.core.gmail import (
    GMAIL_COMPOSE_SCOPE,
    Attachment,
    _build_gmail,
    create_draft,
    send_company_email,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


class TestGmailSend:
    def test_a_real_send_is_accepted(self) -> None:
        recipient = delegated_subject()

        message_id = send_company_email(
            to=recipient,
            subject="DocketWorks integration test — please ignore",
            body=(
                "Sent by apps/core/tests/test_gmail_integration.py to prove "
                "the delegated gmail.send path end to end."
            ),
        )

        assert message_id != ""


class TestGmailDraft:
    """The draft path, which carries an attachment the send path cannot.

    Read back through ``drafts.get(format="raw")`` rather than
    ``messages.get``: the production scope is gmail.compose, which reaches
    drafts and nothing else, so a test that needed messages.get would be
    proving a scope the application does not hold.
    """

    def test_a_real_draft_carries_the_pdf(self) -> None:
        subject_user = delegated_subject()
        pdf = BytesIO()
        canvas = Canvas(pdf)
        canvas.drawString(100, 750, "DocketWorks integration test")
        canvas.save()

        draft = create_draft(
            as_user=subject_user,
            to=subject_user,
            subject="DocketWorks integration test — please ignore",
            body="Created by apps/core/tests/test_gmail_integration.py.",
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
