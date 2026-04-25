import datetime
import json
import os
import subprocess
import uuid
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.workflow.services import db_scrubber
from apps.workflow.services.error_persistence import persist_app_error


class Command(BaseCommand):
    help = (
        "Produces a scrubbed pg_dump of prod for dev refresh. "
        "Raw prod data never leaves the prod host."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--analyze-fields",
            action="store_true",
            help="Show field samples to help identify PII (legacy diagnostic tool)",
        )
        parser.add_argument("--sample-size", type=int, default=50)
        parser.add_argument("--model-filter", type=str)
        parser.add_argument(
            "--rclone-target",
            type=str,
            default=os.getenv("BACKPORT_RCLONE_TARGET", "gdrive:dw_backups"),
            help="rclone target for the scrubbed dump",
        )

    def handle(self, *args, **options):
        if options.get("analyze_fields"):
            return self.analyze_fields(
                sample_size=options["sample_size"],
                model_filter=options.get("model_filter"),
            )

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        env_name = "dev" if settings.DEBUG else "prod"
        backup_dir = os.path.join(settings.BASE_DIR, "restore")
        os.makedirs(backup_dir, exist_ok=True)

        raw_dump = f"/tmp/raw_{ts}.dump"
        scrubbed_dump = os.path.join(backup_dir, f"scrubbed_{env_name}_{ts}.dump")

        default_db = settings.DATABASES["default"]
        scrub_db = settings.DATABASES["scrub"]
        env = os.environ.copy()
        env["PGPASSWORD"] = default_db["PASSWORD"]

        try:
            self.stdout.write(f"pg_dump {default_db['NAME']} -> {raw_dump}")
            self._run(
                [
                    "pg_dump",
                    "-Fc",
                    "-h",
                    default_db["HOST"],
                    "-U",
                    default_db["USER"],
                    "-d",
                    default_db["NAME"],
                    "-f",
                    raw_dump,
                ],
                env=env,
            )

            self.stdout.write(f"drop/recreate public schema on {scrub_db['NAME']}")
            self._run(
                [
                    "psql",
                    "-h",
                    scrub_db["HOST"],
                    "-U",
                    scrub_db["USER"],
                    "-d",
                    scrub_db["NAME"],
                    "-c",
                    "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
                ],
                env=env,
            )

            self.stdout.write(f"pg_restore -> {scrub_db['NAME']}")
            self._run(
                [
                    "pg_restore",
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    "-h",
                    scrub_db["HOST"],
                    "-U",
                    scrub_db["USER"],
                    "-d",
                    scrub_db["NAME"],
                    raw_dump,
                ],
                env=env,
            )

            self.stdout.write("db_scrubber.scrub()")
            db_scrubber.scrub()

            self.stdout.write(f"pg_dump {scrub_db['NAME']} -> {scrubbed_dump}")
            self._run(
                [
                    "pg_dump",
                    "-Fc",
                    "-h",
                    scrub_db["HOST"],
                    "-U",
                    scrub_db["USER"],
                    "-d",
                    scrub_db["NAME"],
                    "-f",
                    scrubbed_dump,
                ],
                env=env,
            )

            self.stdout.write(f"drop/recreate public schema on {scrub_db['NAME']}")
            self._run(
                [
                    "psql",
                    "-h",
                    scrub_db["HOST"],
                    "-U",
                    scrub_db["USER"],
                    "-d",
                    scrub_db["NAME"],
                    "-c",
                    "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
                ],
                env=env,
            )

            os.remove(raw_dump)

            self.stdout.write(
                f"rclone copy {scrubbed_dump} -> {options['rclone_target']}"
            )
            self._run(["rclone", "copy", scrubbed_dump, options["rclone_target"]])

            self.stdout.write(
                self.style.SUCCESS(f"Scrubbed dump written: {scrubbed_dump}")
            )
        except Exception as exc:
            persist_app_error(exc)
            # Raw dump may contain unscrubbed PII — ensure it's gone on any failure.
            if os.path.exists(raw_dump):
                os.remove(raw_dump)
            raise

    def _run(self, cmd, env=None):
        subprocess.run(cmd, check=True, env=env, capture_output=True, text=True)

    def analyze_fields(self, sample_size, model_filter):
        """Show field samples to help identify PII"""

        self.stdout.write(self.style.SUCCESS("Showing field samples..."))
        self.stdout.write(f"Sample size: {sample_size}")
        if model_filter:
            self.stdout.write(f"Filtering to model: {model_filter}")
        self.stdout.write("")

        # Models to analyze
        # Use dumpdata to get all backed-up models (or filter to one)
        cmd = ["python", "manage.py", "dumpdata", "--indent", "2"]
        if model_filter:
            cmd += [model_filter]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)

        # Group by model and field
        field_samples = defaultdict(lambda: defaultdict(list))

        for item in data:
            model = item["model"]
            fields = item["fields"]
            self.collect_field_samples(fields, model, field_samples, "", sample_size)

        # Display samples
        for model in sorted(field_samples.keys()):
            self.stdout.write(self.style.SUCCESS(f"\n{'='*60}"))
            self.stdout.write(self.style.SUCCESS(f"Model: {model}"))
            self.stdout.write(self.style.SUCCESS(f"{'='*60}"))

            for field_path in sorted(field_samples[model].keys()):
                samples = field_samples[model][field_path]

                # Skip if no non-empty samples
                if not any(samples):
                    continue

                # Check if field cannot be PII
                if samples and self.cannot_be_pii(samples):
                    self.stdout.write(f"\n  {model}.{field_path} - not PII")
                    continue

                # Calculate distinct values
                non_none_samples = [s for s in samples if s is not None]
                distinct_values = list(set(str(s) for s in non_none_samples))
                distinct_count = len(distinct_values)

                # Display field with distinct count
                self.stdout.write(
                    f"\n  {model}.{field_path} ({distinct_count} distinct):"
                )

                # Show up to 10 unique values if there are few distinct values
                if distinct_count <= 10:
                    for value in sorted(distinct_values)[:10]:
                        display = value[:100]
                        if len(value) > 100:
                            display += "..."
                        self.stdout.write(f"    - {display}")
                else:
                    # Show samples up to sample_size
                    for i, sample in enumerate(non_none_samples[:sample_size]):
                        if sample is not None:
                            display = str(sample)[:100]
                            if len(str(sample)) > 100:
                                display += "..."
                            self.stdout.write(f"    [{i+1}] {display}")

    def is_uuid_string(self, value):
        """Check if a string is a UUID"""
        if not isinstance(value, str):
            return False
        try:
            uuid.UUID(value)
            return True
        except (ValueError, AttributeError):
            return False

    def cannot_be_pii(self, samples):
        """Check if field cannot possibly contain PII"""
        for sample in samples:
            if sample is None:
                continue
            # Check for boolean
            if type(sample) is bool:
                continue
            # Check for UUID string
            if self.is_uuid_string(sample):
                continue
            # Found something that's not UUID/boolean/None
            return False
        return True  # All samples were UUID/boolean/None

    def collect_field_samples(self, data, model, field_samples, prefix, sample_size):
        """Recursively collect field samples from nested structures"""
        if isinstance(data, dict):
            for key, value in data.items():
                field_path = f"{prefix}.{key}" if prefix else key

                if isinstance(value, dict):
                    # Nested object
                    self.collect_field_samples(
                        value, model, field_samples, field_path, sample_size
                    )
                elif isinstance(value, list) and value and isinstance(value[0], dict):
                    # Array of objects
                    for item in value[:sample_size]:
                        self.collect_field_samples(
                            item, model, field_samples, f"{field_path}[]", sample_size
                        )
                else:
                    # Leaf value
                    if len(field_samples[model][field_path]) < sample_size:
                        field_samples[model][field_path].append(value)
