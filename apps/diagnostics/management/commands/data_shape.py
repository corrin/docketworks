"""Report how many rows each model holds, as the committed production shape.

A list screen only misbehaves at volume: it clips at the fold, it pages, its
query count multiplies per row, its response crosses a wire limit. None of that
appears against a handful of fixture rows, so a test written on a thin corpus
passes and the defect ships. This command records the volume the production
instance actually carries, so a shape can be compared against it and a test can
be built to it (ADR 0054).

Counts only. No column values leave the instance, so the output is safe to
commit and to read in a review — which is the point of committing it rather
than querying production whenever a test wants a number.
"""

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone


class Command(BaseCommand):
    """Emit `model: rows` for every model this project defines."""

    help = "Report row counts for every project model, as committed-shape YAML."

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the instance name, which the output records."""
        parser.add_argument(
            "--instance",
            required=True,
            help="Name of the instance being measured, recorded in the output (e.g. msm-prod).",
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Count every project model and print the shape."""
        instance = options["instance"]
        # Opus: Narrowed rather than annotated: BaseCommand hands options through as
        # object, and asserting a type here would be a claim about argparse
        # rather than a check of it.
        if not isinstance(instance, str):
            raise CommandError("--instance must be a name")

        counts: dict[str, int] = {}
        for model in apps.get_models():
            # Opus: Project models only: Django's own auth/contenttypes/sessions
            # tables say nothing about the business data a screen renders.
            if not model._meta.app_config.name.startswith("apps."):
                continue
            label = f"{model._meta.app_label}.{model.__name__}"
            counts[label] = model._default_manager.count()

        self.stdout.write("# Row counts from a production instance, captured by")
        self.stdout.write("# `manage.py data_shape --instance <name>`. Counts only — no")
        self.stdout.write("# column values, so this is safe to commit and to read in review.")
        self.stdout.write("#")
        self.stdout.write("# Tests are built to these numbers rather than to whatever the local")
        self.stdout.write("# corpus happens to hold; `scripts/checks/data_shape_gap.py` reports")
        self.stdout.write("# where the two disagree. See ADR 0054.")
        self.stdout.write(f"captured_at: {timezone.localdate().isoformat()}")
        self.stdout.write(f"instance: {instance}")
        self.stdout.write("counts:")
        for label, rows in sorted(counts.items()):
            self.stdout.write(f"  {label}: {rows}")
