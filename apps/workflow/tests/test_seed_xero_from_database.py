"""Tests for seed_xero_from_database management command.

Regression coverage for Trello #309 — the production-DB guard must
prevent ``clear_production_xero_ids`` from wiping live
``xero_contact_id`` values when the configured DB name belongs to a
prod instance. The DB name pattern is ``dw_<company>_<env>``
(``scripts/server/instance.sh:171``); env is validated against
``dev``/``uat``/``staging``/``prod`` (``scripts/server/common.sh:13``),
so the ``_prod`` suffix is a deterministic signal of a prod DB.
"""

from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from apps.company.models import Company
from apps.workflow.management.commands.seed_xero_from_database import Command

SENTINEL_XERO_CONTACT_ID = "11111111-1111-1111-1111-111111111111"


class ClearProductionXeroIdsTests(TestCase):
    def test_refuses_when_db_name_ends_with_prod(self):
        """Catastrophic-regression guard: if the configured DB name
        ends with ``_prod``, ``clear_production_xero_ids`` must not
        touch the DB. Wiping live ``xero_contact_id``s breaks Xero
        sync until every contact is manually re-linked."""
        company = Company.objects.create(
            name="Acme Ltd",
            email="info@acme.test",
            address="123 Test Street",
            xero_last_modified=timezone.now(),
            xero_contact_id=SENTINEL_XERO_CONTACT_ID,
        )

        cmd = Command()
        cmd.stdout = StringIO()

        with patch.dict(settings.DATABASES["default"], {"NAME": "dw_msm_prod"}):
            cmd.clear_production_xero_ids(dry_run=False)

        company.refresh_from_db()
        self.assertEqual(company.xero_contact_id, SENTINEL_XERO_CONTACT_ID)
