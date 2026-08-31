"""Celery task for password-reset email delivery.

The send is queued rather than made in the request: a synchronous Gmail round
trip runs only when the submitted address has an account, which turns both
response latency and a Gmail outage's 500 into an account-existence oracle on
an anonymous endpoint. The enqueue costs the same for every caller.
"""

import logging

from celery import shared_task

from apps.core.errors import AppErrorContext, persist_app_error
from apps.core.gmail import send_company_email

logger = logging.getLogger(__name__)


@shared_task(name="apps.accounts.tasks.send_password_reset_email_task")
def send_password_reset_email_task(recipient: str, link: str) -> None:
    """Send the reset link. Failure persists (nobody is watching a worker log)."""
    try:
        send_company_email(
            to=recipient,
            subject="Reset your DocketWorks password",
            body=(
                f"Someone asked to reset the DocketWorks password for {recipient}.\n\n"
                f"Use this link to choose a new password:\n\n{link}\n\n"
                "If you did not ask for this, you can ignore this email — your "
                "password is unchanged."
            ),
        )
    except Exception as exc:
        # A failed reset email is invisible from the fixed-200 endpoint by
        # design, so the AppError row is its only trace — and the recipient
        # is the fact an operator needs to re-send by hand (no retry here:
        # nothing else may send credential email on its own schedule).
        persist_app_error(exc, AppErrorContext(additional_context={"recipient": recipient}))
        raise
