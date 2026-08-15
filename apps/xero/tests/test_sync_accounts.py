"""sync_accounts: the chart of accounts, keyed on xero_id.

The sibling writer is ``seeding.seed_accounts_from_xero``, which keys on the
account NAME because a post-restore mirror holds the previous org's ids. The
two must agree on what they store, so what is asserted here is asserted there
too (``test_seeding.py::TestSeedAccountsFromXero``).
"""

import uuid
from unittest.mock import patch

import pytest
from django.utils import timezone
from xero_python.accounting import Account, AccountType

from apps.xero.models import XeroAccount
from apps.xero.transforms import sync_accounts

TENANT = "demo-tenant-id"
SALES_ID = str(uuid.uuid4())
MISSING_DATE_ID = str(uuid.uuid4())


@pytest.fixture(autouse=True)
def _tenant() -> object:
    with patch("apps.xero.transforms.get_tenant_id", return_value=TENANT) as patched:
        yield patched


@pytest.mark.django_db
class TestSyncAccounts:
    def test_creates_an_account_stamped_with_its_org(self) -> None:
        modified = timezone.now()
        account = Account(
            account_id=SALES_ID,
            name="Sales",
            code="200",
            description="Sales income",
            type=AccountType.REVENUE,
            tax_type="OUTPUT2",
            enable_payments_to_account=False,
            updated_date_utc=modified,
        )

        sync_accounts([account])

        row = XeroAccount.objects.get(xero_id=SALES_ID)
        assert row.account_name == "Sales"
        assert row.account_code == "200"
        # .value, not str(): "AccountType.REVENUE" would be persisted otherwise.
        assert row.account_type == "REVENUE"
        assert row.xero_last_modified == modified
        # The org this row was mirrored from. Unstamped rows cannot be told
        # apart from rows restored from another organisation's backup.
        assert row.xero_tenant_id == TENANT

    def test_an_account_without_a_modified_date_is_refused(self) -> None:
        # xero_last_modified is NOT NULL, so the payload is named rather than
        # left to surface as an IntegrityError from inside the loop.
        with pytest.raises(ValueError, match="missing id, name or updated_date_utc"):
            sync_accounts(
                [Account(account_id=MISSING_DATE_ID, name="Sales", updated_date_utc=None)]
            )

        assert not XeroAccount.objects.filter(xero_id=MISSING_DATE_ID).exists()
