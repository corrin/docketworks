"""Inspect a native Xero quote PDF for an expected text marker."""

from __future__ import annotations

import json
from argparse import ArgumentParser
from dataclasses import asdict
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.workflow.accounting.quote_pdf_service import inspect_quote_pdf


class Command(BaseCommand):
    """Expose quote PDF inspection as a structured operational command."""

    help = "Inspect a provider-rendered quote PDF for expected text"

    def add_arguments(self, parser: ArgumentParser | CommandParser) -> None:
        parser.add_argument("quote_id", type=UUID)
        parser.add_argument("--expected-text", required=True)

    def handle(self, *args: object, **options: object) -> None:
        quote_id = options["quote_id"]
        expected_text = options["expected_text"]
        if not isinstance(quote_id, UUID):
            raise CommandError("quote_id must be a UUID")
        if not isinstance(expected_text, str) or not expected_text.strip():
            raise CommandError("--expected-text must not be empty")

        inspection = inspect_quote_pdf(quote_id, expected_text)
        self.stdout.write(json.dumps(asdict(inspection), sort_keys=True))
