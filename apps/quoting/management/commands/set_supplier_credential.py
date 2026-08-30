"""Re-enter a supplier credential's secret material.

Fable: the one surface for writing SupplierCredential secrets — v2 ships no
django.contrib.admin and no API touches the model, yet the cutover migration
deliberately clears the formerly-Fernet columns, so without this command the
checklist's "re-enter supplier credentials" step had nowhere to happen short
of hand-written SQL. Secrets are prompted, never taken as arguments: argv is
visible to every local user while the process runs (the same reason the
fixture renderers are being moved off sed arguments).
"""

from getpass import getpass
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.quoting.models import SupplierCredential


class Command(BaseCommand):
    """Prompt for and store one credential row's secret material."""

    help = (
        "Re-enter the secret material for a SupplierCredential row "
        "(prompted, never argv). Selects by supplier name and label."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Identify the row; the secrets themselves are prompted."""
        parser.add_argument("supplier", help="Supplier company name (exact match).")
        parser.add_argument("label", help="The credential row's label (exact match).")

    def handle(self, *_args: Any, **options: Any) -> None:
        """Prompt per the row's credential_type and save via full_clean."""
        supplier = str(options["supplier"])
        label = str(options["label"])
        credential = SupplierCredential.objects.filter(supplier__name=supplier, label=label).first()
        if credential is None:
            rows = ", ".join(
                f"{c.supplier.name} - {c.label}"
                for c in SupplierCredential.objects.select_related("supplier")
            )
            raise CommandError(
                f"No SupplierCredential for supplier {supplier!r} label {label!r}. "
                f"Existing rows: {rows or '(none)'}"
            )

        kind = credential.credential_type
        if kind == SupplierCredential.CredentialType.USERNAME_PASSWORD:
            username = input("Username: ").strip()
            password = getpass("Password: ")
            if not username or not password:
                raise CommandError("Both username and password are required.")
            credential.username = username
            credential.password = password
        elif kind in (
            SupplierCredential.CredentialType.API_KEY,
            SupplierCredential.CredentialType.API_KEY_HEADER,
        ):
            api_key = getpass("API key: ")
            if not api_key:
                raise CommandError("An API key is required.")
            credential.api_key = api_key
        else:
            raise CommandError(
                f"Credential type {kind!r} stores its material in extra_config; "
                "this command covers the migration-cleared secret columns only."
            )

        credential.full_clean()
        credential.save()
        self.stdout.write(f"Stored {kind} material for {credential.supplier.name} - {label}.")
