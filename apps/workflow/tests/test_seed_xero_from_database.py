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
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from apps.company.models import Company
from apps.workflow.api.xero.transforms import sync_accounts
from apps.workflow.management.commands.seed_xero_from_database import Command
from apps.workflow.models import XeroAccount

SENTINEL_XERO_CONTACT_ID = "11111111-1111-1111-1111-111111111111"


class ClearProductionXeroIdsTests(TestCase):
    def test_refuses_when_db_name_ends_with_prod(self) -> None:
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


class XeroAccountSeedTests(TestCase):
    @patch(
        "apps.workflow.api.xero.transforms.process_xero_data",
        return_value={},
    )
    def test_sync_normalises_empty_optional_text(
        self, _process_xero_data_mock: Mock
    ) -> None:
        sync_accounts(
            [
                SimpleNamespace(
                    account_id=uuid4(),
                    code="",
                    name="Uncoded account",
                    description="",
                    type="",
                    tax_type="",
                    enable_payments_to_account=False,
                    _updated_date_utc=timezone.now(),
                )
            ]
        )

        account = XeroAccount.objects.get(account_name="Uncoded account")
        self.assertIsNone(account.account_code)
        self.assertIsNone(account.description)
        self.assertIsNone(account.account_type)
        self.assertIsNone(account.tax_type)

    @patch(
        "apps.workflow.management.commands.seed_xero_from_database.process_xero_data",
        return_value={},
    )
    @patch(
        "apps.workflow.management.commands.seed_xero_from_database.get_tenant_id",
        return_value="demo-tenant",
    )
    @patch("apps.workflow.management.commands.seed_xero_from_database.AccountingApi")
    def test_empty_xero_description_is_stored_as_null(
        self,
        accounting_api_mock: Mock,
        _tenant_id_mock: Mock,
        _process_xero_data_mock: Mock,
    ) -> None:
        prod_xero_id = uuid4()
        demo_xero_id = uuid4()
        modified_at = timezone.now()
        XeroAccount.objects.create(
            xero_id=prod_xero_id,
            account_code="805",
            account_name="Accrued Liabilities",
            description="Production description",
            account_type="CURRLIAB",
            tax_type="NONE",
            xero_last_modified=modified_at,
            raw_json={},
        )
        accounting_api_mock.return_value.get_accounts.return_value.accounts = [
            SimpleNamespace(
                account_id=demo_xero_id,
                code="805",
                name="Accrued Liabilities",
                description="",
                type="CURRLIAB",
                tax_type="NONE",
                enable_payments_to_account=False,
                _updated_date_utc=modified_at,
            )
        ]

        command = Command()
        command.process_accounts(dry_run=False)

        account = XeroAccount.objects.get(account_name="Accrued Liabilities")
        self.assertEqual(account.xero_id, demo_xero_id)
        self.assertIsNone(account.description)
