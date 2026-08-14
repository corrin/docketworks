"""Refuse Django's built-in flush; the sanctioned wipe is reset_public_schema.

``manage.py flush --noinput`` deletes every row in every table with no
production refusal and no recovery path — the exact careless-wipe shape
ADR 0048 exists to close. App commands shadow built-ins in Django's command
registry, so this refusal replaces the built-in everywhere, including on
instances. There is deliberately no bypass flag: the deliberate operation
flush performs (empty the data, keep the schema) is a subset of what
``reset_public_schema`` + ``migrate`` provides, with refusals and a
snapshot.
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    """Blocked; use reset_public_schema."""

    help = "Refused (ADR 0048). Use reset_public_schema + migrate instead."

    def handle(self, *_args: object, **_options: object) -> None:
        """Refuse unconditionally."""
        raise CommandError(
            "flush is refused (ADR 0048): it empties every table with no "
            "refusals and no snapshot. Use "
            "'manage.py reset_public_schema --database <DB_NAME>' followed by "
            "'manage.py migrate' — same end state, recoverable and guarded."
        )
