"""Mint a named ServiceAPIKey and print it once.

External consumers (the chatbot MCP bridge) hold the key, so this is the one
place it is ever displayed; the row stores it but no screen re-shows it.
"""

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.core.models import ServiceAPIKey


class Command(BaseCommand):
    """Create a service API key for MCP access."""

    help = "Create a service API key for MCP access"

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the key name."""
        parser.add_argument(
            "--name",
            type=str,
            default="Chatbot Service",
            help="Name for the service API key",
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Create the key, refusing a duplicate name rather than rotating it.

        v1 printed the existing key on a name collision and exited zero. That
        re-displays a credential that was promised to be shown once, and it
        makes scripted re-runs silently reuse keys; a refusal makes rotation an
        explicit delete-then-create.
        """
        name = options["name"]
        if not isinstance(name, str):
            raise TypeError("The name option must be a string")

        if ServiceAPIKey.objects.filter(name=name).exists():
            raise CommandError(
                f'API key "{name}" already exists. Delete it first if you intend to rotate it.'
            )

        service_key = ServiceAPIKey.objects.create(name=name)

        self.stdout.write(self.style.SUCCESS(f'Created API key "{name}": {service_key.key}'))
        self.stdout.write(
            self.style.WARNING("Save this key securely - it cannot be retrieved again!")
        )
