"""Inspect a native Xero quote PDF for an expected text marker."""

import json
from dataclasses import asdict
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.accounting.services.quote_pdf import inspect_quote_pdf


class Command(BaseCommand):
    """Expose quote PDF inspection as a structured operational command.

    Emits exactly one JSON line on stdout — the E2E quote spec shells out to
    this command and parses the last non-empty line, so anything else written
    to stdout breaks a subprocess contract.
    """

    help = "Inspect a provider-rendered quote PDF for expected text"

    def add_arguments(self, parser: CommandParser) -> None:
        """Take the XERO quote id (not the local row id) and the marker text."""
        parser.add_argument("quote_id", type=UUID)
        parser.add_argument("--expected-text", required=True)

    def handle(self, *args: object, **options: object) -> None:  # noqa: ARG002 -- BaseCommand signature
        """Validate inputs, inspect, emit the single JSON line."""
        quote_id = options["quote_id"]
        expected_text = options["expected_text"]
        if not isinstance(quote_id, UUID):
            raise CommandError("quote_id must be a UUID")
        if not isinstance(expected_text, str) or not expected_text.strip():
            raise CommandError("--expected-text must not be empty")

        inspection = inspect_quote_pdf(quote_id, expected_text)
        self.stdout.write(json.dumps(asdict(inspection), sort_keys=True))
