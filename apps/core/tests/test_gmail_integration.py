"""The delegated Gmail send against the real API (ADR 0050).

One real message, addressed to the delegated subject itself so the probe
stays inside the instance's own inbox. On a dev box the dev database's
``company_email`` is a demo placeholder, so this needs ``GCP_CREDENTIALS``
and ``GCP_DELEGATED_SUBJECT`` in the environment — the builders fail loud
naming exactly what is missing.
"""

import pytest

from apps.core.gauth import delegated_subject
from apps.core.gmail import send_company_email

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
