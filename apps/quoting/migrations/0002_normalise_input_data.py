"""Normalise ProductParsingMapping.input_data to the one canonical dict shape.

v1 wrote this JSONField two ways from the same file: ``_save_mapping`` stored a
dict keyed ``product_name``/``description``/``specifications``, while
``create_mapping_record`` stored a *JSON string* keyed ``input_product_name``/
``input_description``/``input_specifications`` — double-encoded, so the column
holds a JSON string rather than a JSON object. The 2026-08-01 production
restore carries both: 644 object rows and 559 string rows.

v2 writes one shape and the API declares ``input_data: dict``, so the string
rows fail response validation and 500 the product-mappings listing. ADR 0015
says fix the data rather than soften the consumer, so this migration decodes
the string rows and maps the ``input_*`` keys onto the canonical ones. Rows
that are already dicts are untouched.

A row this migration cannot normalise ABORTS the migration, naming the primary
keys. Leaving it in place would be the worst of both worlds: the migration
reports success, and the row 500s the product-mappings listing the first time
someone opens it — the exact defect this migration exists to remove. Inventing
a shape for it instead would be the read-side fallback ADR 0015 forbids. So the
only honest options are "fixed" and "stop, a human must look at this", and on
the 2026-08-01 restore every one of the 1,203 rows takes the fixed path.

Found by running the app against migrated production data (the endpoint 500'd),
not by any test — the synthetic fixtures only ever produced the good shape.
"""

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

from apps.quoting.migrations._0002_helpers import normalise_rows


def normalise_input_data(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Decode double-encoded input_data rows and rename their legacy keys."""
    normalise_rows(apps.get_model("quoting", "ProductParsingMapping"))


def reverse_noop(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Irreversible by design: the legacy shape is the defect being removed."""


class Migration(migrations.Migration):
    dependencies = [
        ("quoting", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(normalise_input_data, reverse_noop),
    ]
