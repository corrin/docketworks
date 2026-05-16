"""Regression coverage for the unavailable Profit and Loss endpoint."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Staff


@pytest.mark.django_db
def test_profit_and_loss_endpoint_reports_unavailable() -> None:
    staff = Staff.objects.create(
        email="pnl-report@example.test",
        first_name="Pnl",
        last_name="Report",
        password_needs_reset=False,
        is_office_staff=True,
    )
    api = APIClient()
    api.force_authenticate(user=staff)

    response = api.get(
        "/api/accounting/reports/profit-and-loss/",
        {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        },
    )

    assert response.status_code == 501
    assert "unavailable" in response.json()["error"]
