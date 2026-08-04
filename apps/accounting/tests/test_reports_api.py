"""Wire-contract tests for the /api/accounting/reports/ surface.

v1 gated every report on plain IsAuthenticated (DRF default — no view set a
permission class), so the auth cases here assert exactly that: cookie required,
no office/superuser gate.
"""

import pytest
from django.test import Client

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounting.tests.urls"),
]


class TestProfitAndLoss:
    def test_requires_authentication(self) -> None:
        response = Client().get("/api/accounting/reports/profit-and-loss/")
        assert response.status_code == 401

    def test_returns_501_until_rebuilt_against_xero(self, authenticated_client: Client) -> None:
        """v1 removed the implementation and pinned this exact 501 body; the
        frontend keys off it. Rebuilding is Phase 4 (Xero) work."""
        response = authenticated_client.get("/api/accounting/reports/profit-and-loss/")
        assert response.status_code == 501
        assert response.json()["detail"] == (
            "Profit and Loss reporting is unavailable until it is rebuilt "
            "against the Xero Reports API."
        )
