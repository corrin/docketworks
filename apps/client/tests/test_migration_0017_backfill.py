"""
Test the data migration that backfills stranded FK records onto merged-into
clients.

Testing data migrations at the migration-replay level usually needs
``django-test-migrations`` (not installed here). Instead we invoke the
migration's ``reassign_stranded_fks`` function directly, feeding it the live
app registry via ``django.apps.apps`` — same signature the migration runner
uses. This still exercises the real code path that will run against prod.
"""

import importlib
import uuid
from datetime import date
from decimal import Decimal

from django.apps import apps as django_apps
from django.utils import timezone

from apps.accounting.models import Invoice
from apps.client.models import Client
from apps.job.models import Job
from apps.testing import BaseTestCase

_migration_module = importlib.import_module(
    "apps.client.migrations.0017_reassign_stranded_merged_client_fks"
)


def _make_client(name: str) -> Client:
    return Client.objects.create(name=name, xero_last_modified=timezone.now())


def _make_stranded_records(source: Client) -> dict:
    """Create one Job + one Invoice on source (covers the two most-common
    prod scenarios; the service itself is exhaustively tested per-FK)."""
    job = Job.objects.create(
        name=f"Job for {source.name}",
        job_number=800000 + abs(hash(source.name)) % 10000,
        client=source,
    )
    invoice = Invoice.objects.create(
        xero_id=uuid.uuid4(),
        number=f"MIG-{uuid.uuid4().hex[:6]}",
        client=source,
        date=date.today(),
        total_excl_tax=Decimal("100.00"),
        tax=Decimal("15.00"),
        total_incl_tax=Decimal("115.00"),
        amount_due=Decimal("115.00"),
        xero_last_modified=timezone.now(),
        raw_json={},
    )
    return {"job": job, "invoice": invoice}


class MigrationBackfillTests(BaseTestCase):
    def test_backfill_moves_stranded_job_onto_merged_into_client(self) -> None:
        destination = _make_client("Destination")
        source = _make_client("Source")
        source.merged_into = destination
        source.save()

        records = _make_stranded_records(source)

        _migration_module.reassign_stranded_fks(django_apps, schema_editor=None)

        records["job"].refresh_from_db()
        records["invoice"].refresh_from_db()
        self.assertEqual(records["job"].client_id, destination.id)
        self.assertEqual(records["invoice"].client_id, destination.id)

    def test_backfill_walks_chain_to_terminal_client(self) -> None:
        """A -> B -> C. Records on A should land on C after the migration."""
        c = _make_client("C")
        b = _make_client("B")
        b.merged_into = c
        b.save()
        a = _make_client("A")
        a.merged_into = b
        a.save()

        records = _make_stranded_records(a)

        _migration_module.reassign_stranded_fks(django_apps, schema_editor=None)

        records["job"].refresh_from_db()
        records["invoice"].refresh_from_db()
        self.assertEqual(records["job"].client_id, c.id)
        self.assertEqual(records["invoice"].client_id, c.id)

    def test_backfill_ignores_non_merged_clients(self) -> None:
        """Clients without merged_into are untouched by the migration."""
        standalone = _make_client("Standalone")
        records = _make_stranded_records(standalone)

        _migration_module.reassign_stranded_fks(django_apps, schema_editor=None)

        records["job"].refresh_from_db()
        records["invoice"].refresh_from_db()
        self.assertEqual(records["job"].client_id, standalone.id)
        self.assertEqual(records["invoice"].client_id, standalone.id)

    def test_backfill_idempotent(self) -> None:
        """Running the migration twice is safe; second run is a no-op."""
        destination = _make_client("Destination")
        source = _make_client("Source")
        source.merged_into = destination
        source.save()

        records = _make_stranded_records(source)

        _migration_module.reassign_stranded_fks(django_apps, schema_editor=None)
        _migration_module.reassign_stranded_fks(django_apps, schema_editor=None)

        records["job"].refresh_from_db()
        records["invoice"].refresh_from_db()
        self.assertEqual(records["job"].client_id, destination.id)
        self.assertEqual(records["invoice"].client_id, destination.id)
