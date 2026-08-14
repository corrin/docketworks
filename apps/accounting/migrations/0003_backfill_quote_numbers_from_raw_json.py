"""Backfill Quote.number from the row's own mirrored payload.

A v1 sync era stored quotes without writing the ``number`` column while the
mirrored ``raw_json`` carried ``_quote_number`` all along — the 2026-08
production data holds 380 such rows. The Xero seeding path keys batch
responses on the document number and refuses numberless documents upfront
(apps/xero/seeding.py), which is how the defect surfaced. Fix the data, not
the reader (ADR 0015): the number every such row already carries in its own
payload is the one Xero holds for it.

Rows with no ``_quote_number`` in raw_json are left untouched — inventing a
number would break the very keying this repairs; the seeding refusal will
name any such row loudly.
"""

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps
from django.db.models import Q


def backfill_numbers(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Copy raw_json's _quote_number into the empty number column."""
    quote_model = apps.get_model("accounting", "Quote")
    to_fix = quote_model.objects.filter(Q(number__isnull=True) | Q(number="")).exclude(
        raw_json__isnull=True
    )
    repaired = []
    for quote in to_fix.iterator():
        payload_number = (quote.raw_json or {}).get("_quote_number")
        if not payload_number:
            continue
        quote.number = payload_number
        repaired.append(quote)
    quote_model.objects.bulk_update(repaired, ["number"], batch_size=500)


class Migration(migrations.Migration):
    """One-way data repair; reversing would re-null repaired numbers."""

    dependencies = [
        ("accounting", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_numbers, migrations.RunPython.noop),
    ]
