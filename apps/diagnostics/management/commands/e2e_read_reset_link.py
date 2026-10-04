"""Read the password-reset link the app emailed, for the E2E reset spec.

The reset email is a real delegated Gmail send, so the only way a spec can
follow the link is to read the mailbox it landed in. This command does that
through the same Gmail module the app sends with, and prints what it found.

Lives in diagnostics with the other E2E commands: it exists for the test
harness, not for anyone using the product.
"""

import json
import re
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.core.environment import ProductionDatabaseError, assert_not_production_database
from apps.platform.integrations.google.gmail import latest_message_body

#: The subject apps/accounts/tasks.py sends the reset email under.
RESET_SUBJECT = "Reset your DocketWorks password"
_RESET_LINK = re.compile(r"https?://\S+/reset-password\?uid=\S+&token=\S+")


def reset_link_in(body: str) -> str:
    """Return the reset link in a reset email's body; the email carries exactly one."""
    links = _RESET_LINK.findall(body)
    if len(links) != 1:
        raise ValueError(f"Expected one reset link in the email, found {len(links)}")
    link: str = links[0]
    return link


class Command(BaseCommand):
    """Print the newest reset link sent to an address, or null when none has arrived.

    Emits exactly one JSON line on stdout — the E2E spec shells out to this
    command and parses the last non-empty line, polling until the link is
    there.
    """

    help = "Read the newest password-reset link emailed to an address (E2E environments only)"

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare who the email went to, whose mailbox holds it, and how new it must be."""
        parser.add_argument("--to", required=True, help="The address the reset was requested for")
        parser.add_argument(
            "--mailbox",
            required=True,
            help="The Workspace user whose mailbox receives it (the address without any +tag)",
        )
        parser.add_argument(
            "--since",
            required=True,
            type=datetime.fromisoformat,
            help="ISO timestamp with offset; older messages are a previous run's",
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Refuse a production database, then read the mailbox once."""
        try:
            assert_not_production_database("this command reads a mailbox for a test.")
        except ProductionDatabaseError as exc:
            raise CommandError(str(exc)) from exc
        to, mailbox, since = options["to"], options["mailbox"], options["since"]
        if not isinstance(to, str) or not isinstance(mailbox, str):
            raise CommandError("--to and --mailbox must be addresses")
        if not isinstance(since, datetime) or since.tzinfo is None:
            raise CommandError("--since must be an ISO timestamp with an offset")

        body = latest_message_body(mailbox=mailbox, to=to, subject=RESET_SUBJECT, since=since)
        link = None if body is None else reset_link_in(body)
        self.stdout.write(json.dumps({"link": link}))
