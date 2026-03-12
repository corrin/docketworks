import datetime
import gzip
import json
import os
import subprocess
import uuid
import zipfile
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from faker import Faker

from apps.accounts.staff_anonymization import create_staff_profile
from apps.workflow.models import CompanyDefaults


class Command(BaseCommand):
    help = "Backs up necessary production data, excluding Xero-related models."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Track unique values to avoid duplicates
        self._used_company_names = set()
        self._used_staff_emails = set()
        self._used_staff_preferred_names = set()

    def add_arguments(self, parser):
        parser.add_argument(
            "--analyze-fields",
            action="store_true",
            help="Analyze all fields in the database to identify potential PII",
        )
        parser.add_argument(
            "--sample-size",
            type=int,
            default=50,
            help="Number of samples to show per field (default: 50)",
        )
        parser.add_argument(
            "--model-filter",
            type=str,
            help='Only analyze specific model (e.g., "job.Job")',
        )

        # Configuration: model -> field -> replacement type
        # Replacement types: "name", "email", "phone", "text", "number", "date", "address"
        # Note: accounts.staff is handled separately in _anonymize_staff() for coherent profiles
        self.PII_CONFIG = {
            "client.client": {
                "name": "company",
                "primary_contact_name": "name",
                "primary_contact_email": "email",
                "email": "email",
                "phone": "phone",
                "raw_json._name": "name",
                "raw_json._email_address": "email",
                "raw_json._bank_account_details": "iban",
                "raw_json._phones[]._phone_number": "phone",
                "raw_json._batch_payments._bank_account_number": "iban",
                "raw_json._batch_payments._bank_account_name": "name",
            },
            "client.clientcontact": {
                "name": "name",
                "email": "email",
                "phone": "phone",
            },
        }

    def handle(self, *args, **options):
        # Check if we're in analysis mode
        if options.get("analyze_fields"):
            return self.analyze_fields(
                sample_size=options["sample_size"],
                model_filter=options.get("model_filter"),
            )

        self.stdout.write(self.style.SUCCESS("Starting data backup..."))

        # Define models to include
        INCLUDE_MODELS = [
            "job.Job",
            "job.CostSet",
            "job.CostLine",
            "job.JobEvent",
            "job.JobFile",
            "job.JobQuoteChat",
            "job.QuoteSpreadsheet",
            "accounts.Staff",
            "client.Client",
            "client.ClientContact",
            "client.SupplierPickupAddress",
            "purchasing.PurchaseOrder",  # Include production POs for restore to UAT
            "purchasing.PurchaseOrderLine",  # Include PO lines with material details
            "purchasing.Stock",  # Include stock items - will be synced to Xero after restore
            "quoting.SupplierPriceList",
            "quoting.SupplierProduct",
            "quoting.ScrapeJob",
            "contenttypes",  # Django internal - needed for migrations
        ]

        # Define the output directory and filename
        backup_dir = os.path.join(settings.BASE_DIR, "restore")
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        env_name = "dev" if settings.DEBUG else "prod"
        output_filename = f"{env_name}_backup_{timestamp}.json.gz"
        output_path = os.path.join(backup_dir, output_filename)

        self.stdout.write(f"Backup will be saved to: {output_path}")
        self.stdout.write(f"Models to be backed up: {', '.join(INCLUDE_MODELS)}")

        try:
            # Step 1: Use Django's dumpdata for clean serialization
            cmd = ["python", "manage.py", "dumpdata"] + INCLUDE_MODELS
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)

            # Step 2: Add migrations data manually
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, app, name, applied FROM django_migrations ORDER BY id"
                )
                migrations_rows = cursor.fetchall()

            # Convert migrations to Django fixture format
            migrations_data = []
            for row in migrations_rows:
                migrations_data.append(
                    {
                        "model": "migrations.migration",
                        "pk": row[0],
                        "fields": {
                            "app": row[1],
                            "name": row[2],
                            "applied": row[3].isoformat() if row[3] else None,
                        },
                    }
                )

            # Step 3: Parse and combine data
            data = json.loads(result.stdout)
            data.extend(migrations_data)
            fake = Faker()

            # Get preserved client names from CompanyDefaults
            preserved_client_names = self._get_preserved_client_names()
            self.stdout.write(f"Preserving client names: {preserved_client_names}")

            self.stdout.write(
                f"Anonymizing {len(data)} records "
                f"(including {len(migrations_data)} migrations)..."
            )

            for item in data:
                self.anonymize_item(item, fake, preserved_client_names)

            # Step 3: Write anonymized data (compressed)
            with gzip.open(output_path, "wt", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            self.stdout.write(
                self.style.SUCCESS(
                    f"Data backup completed successfully to {output_path}"
                )
            )

            # Step 4: Create schema-only backup using mysqldump
            schema_path = self.create_schema_backup(backup_dir, timestamp, env_name)

            # Step 5: Create combined zip file in /tmp
            self.create_combined_zip(output_path, schema_path, timestamp, env_name)

        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f"dumpdata failed: {e.stderr}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error during data backup: {e}"))
            if os.path.exists(output_path):
                os.remove(output_path)

    def _get_preserved_client_names(self):
        """Get the list of client names that should not be anonymized."""
        preserved_names = set()
        company_defaults = CompanyDefaults.get_solo()
        if company_defaults.shop_client_name:
            preserved_names.add(company_defaults.shop_client_name)
        if company_defaults.test_client_name:
            preserved_names.add(company_defaults.test_client_name)

        # Preserve names of scraper suppliers (declared on each scraper class)
        from apps.quoting.management.commands.run_scrapers import Command as ScraperCmd

        for scraper_info in ScraperCmd().get_available_scrapers():
            supplier_name = getattr(scraper_info["class_obj"], "SUPPLIER_NAME", None)
            if supplier_name:
                preserved_names.add(supplier_name)

        return preserved_names

    def anonymize_item(self, item, fake, preserved_client_names=None):
        """Anonymize PII fields in the serialized item using configuration"""
        if preserved_client_names is None:
            preserved_client_names = set()

        model = item["model"]
        fields = item["fields"]

        # Special case: preserve shop and test clients by name
        if model == "client.client" and fields.get("name") in preserved_client_names:
            # Skip anonymization entirely for preserved clients
            return

        # Special case: staff uses coherent profiles (preferred_name matches first_name)
        if model == "accounts.staff":
            self._anonymize_staff(fields)
            return

        if model not in self.PII_CONFIG:
            return  # No PII configuration for this model

        # Process each field path in the configuration
        for field_path, replacement_type in self.PII_CONFIG[model].items():
            value = self._get_replacement_value(replacement_type, fake)
            self._set_field_by_path(fields, field_path, value)

    def _anonymize_staff(self, fields):
        """Anonymize staff with coherent profile (preferred_name/email match first_name)."""
        profile = create_staff_profile()
        fields["first_name"] = profile["first_name"]
        fields["last_name"] = profile["last_name"]
        fields["preferred_name"] = profile["preferred_name"]
        fields["email"] = profile["email"]

    def _get_replacement_value(self, replacement_type, fake):
        """Get replacement value based on type"""
        if replacement_type == "first_name":
            return fake.first_name()
        elif replacement_type == "last_name":
            return fake.last_name()
        elif replacement_type == "name":
            return fake.name()
        elif replacement_type == "email":
            return fake.email()
        elif replacement_type == "phone":
            return fake.phone_number()
        elif replacement_type == "company":
            # Ensure unique company names - FAIL EARLY if can't find unique
            max_attempts = 1000
            for _ in range(max_attempts):
                company_name = fake.company()
                if company_name not in self._used_company_names:
                    self._used_company_names.add(company_name)
                    return company_name
            # FAIL EARLY - couldn't generate unique name
            raise ValueError(
                f"Failed to generate unique company name after {max_attempts} attempts. "
                f"Already used {len(self._used_company_names)} company names."
            )
        elif replacement_type == "address":
            return fake.street_address()
        elif replacement_type == "city":
            return fake.city()
        elif replacement_type == "postcode":
            return fake.postcode()
        elif replacement_type == "iban":
            return fake.iban()
        elif replacement_type == "number":
            return str(fake.random_int(min=10000000, max=99999999))
        elif replacement_type == "date":
            return fake.date_between(start_date="-30y", end_date="today").isoformat()
        else:
            return fake.text(max_nb_chars=100)

    def _set_field_by_path(self, data, path, value):
        """Set a value in nested data structure using dot notation path"""
        parts = path.split(".")

        # Handle simple top-level field
        if len(parts) == 1:
            if parts[0] in data:
                data[parts[0]] = value
            return

        # Handle nested path
        current = data
        for i, part in enumerate(parts[:-1]):
            # Handle array notation like "_phones[]"
            if "[]" in part:
                field_name = part.replace("[]", "")
                if field_name in current and current[field_name]:
                    # Apply to all items in array
                    for item in current[field_name]:
                        self._set_field_by_path(item, ".".join(parts[i + 1 :]), value)
                return
            else:
                # Navigate to nested object
                if part in current and current[part]:
                    current = current[part]
                else:
                    return  # Path doesn't exist

        # Set the final field
        final_field = parts[-1]
        if final_field in current:
            current[final_field] = value

    def create_schema_backup(self, backup_dir, timestamp, env_name):
        """Create a schema-only backup using mysqldump"""
        try:
            # Get database configuration from Django settings
            db_config = settings.DATABASES["default"]

            # Build mysqldump command for schema only (no data)
            schema_filename = f"{env_name}_backup_{timestamp}.schema.sql"
            schema_path = os.path.join(backup_dir, schema_filename)

            # Build the mysqldump command
            cmd = [
                "mysqldump",
                "--no-data",  # Schema only, no data
                "--routines",  # Include stored procedures and functions
                "--triggers",  # Include triggers
                "--events",  # Include events
                f'--host={db_config["HOST"]}',
                f'--port={db_config.get("PORT", "3306")}',
                f'--user={db_config["USER"]}',
                db_config["NAME"],
            ]

            # Set password via environment variable for security
            env = os.environ.copy()
            env["MYSQL_PWD"] = db_config["PASSWORD"]

            self.stdout.write(f"Creating schema backup to: {schema_path}")

            # Execute mysqldump and write to file
            with open(schema_path, "w") as f:
                result = subprocess.run(
                    cmd,
                    stdout=f,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                    check=True,
                )

            # Check for any warnings in stderr
            if result.stderr:
                self.stdout.write(
                    self.style.WARNING(f"mysqldump warnings: {result.stderr}")
                )

            self.stdout.write(
                self.style.SUCCESS(
                    f"Schema backup completed successfully to {schema_path}"
                )
            )
            return schema_path

        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f"mysqldump failed: {e.stderr}"))
            raise
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error during schema backup: {e}"))
            raise

    def create_combined_zip(self, data_path, schema_path, timestamp, env_name):
        """Create a combined zip file containing both data and schema backups in /tmp"""
        # Check for failures first
        if not os.path.exists(data_path):
            raise FileNotFoundError(f"Data backup file not found: {data_path}")

        if not os.path.exists(schema_path):
            raise FileNotFoundError(f"Schema backup file not found: {schema_path}")

        # Create zip file in /tmp
        zip_filename = f"{env_name}_backup_{timestamp}_complete.zip"
        zip_path = os.path.join("/tmp", zip_filename)

        self.stdout.write(f"Creating combined zip file: {zip_path}")

        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                # Add data backup
                zipf.write(data_path, os.path.basename(data_path))

                # Add schema backup
                zipf.write(schema_path, os.path.basename(schema_path))

            self.stdout.write(
                self.style.SUCCESS(
                    f"Combined backup zip created successfully: {zip_path}"
                )
            )

            # Show file sizes for confirmation
            zip_size = os.path.getsize(zip_path) / (1024 * 1024)  # MB
            self.stdout.write(f"Zip file size: {zip_size:.2f} MB")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error creating zip file: {e}"))
            if os.path.exists(zip_path):
                os.remove(zip_path)
            raise

    def analyze_fields(self, sample_size, model_filter):
        """Show field samples to help identify PII"""

        self.stdout.write(self.style.SUCCESS("Showing field samples..."))
        self.stdout.write(f"Sample size: {sample_size}")
        if model_filter:
            self.stdout.write(f"Filtering to model: {model_filter}")
        self.stdout.write("")

        # Models to analyze
        MODELS_TO_ANALYZE = [
            "job.Job",
            "job.CostSet",
            "job.CostLine",
            "job.JobEvent",
            "job.JobFile",
            "accounts.Staff",
            "client.Client",
            "client.ClientContact",
        ]

        if model_filter:
            MODELS_TO_ANALYZE = [m for m in MODELS_TO_ANALYZE if m == model_filter]

        # Use dumpdata to get records
        cmd = (
            ["python", "manage.py", "dumpdata"] + MODELS_TO_ANALYZE + ["--indent", "2"]
        )
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
