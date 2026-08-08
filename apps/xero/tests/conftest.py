"""Factories and fixtures for the Xero app's tests."""

from datetime import timedelta
from typing import TypedDict, Unpack

import pytest
from django.test import Client
from django.utils import timezone as dj_timezone
from ninja_jwt.tokens import RefreshToken

from apps.accounts.models import Staff
from apps.core.auth import jwt_cookie_config
from apps.xero.models import XeroApp


class XeroAppOverrides(TypedDict, total=False):
    """The XeroApp columns tests vary."""

    label: str
    client_id: str
    client_secret: str
    redirect_uri: str
    is_active: bool
    webhook_key: str | None
    access_token: str | None
    refresh_token: str | None
    token_type: str | None
    expires_at: object
    scope: str | None
    day_remaining: int | None
    minute_remaining: int | None
    snapshot_at: object
    last_429_at: object


def make_xero_app(**overrides: Unpack[XeroAppOverrides]) -> XeroApp:
    """Create a XeroApp row; inactive with no tokens unless overridden."""
    defaults: XeroAppOverrides = {
        "label": "A",
        "client_id": "c-a",
        "client_secret": "s",
        "redirect_uri": "https://example.test/cb",
        "is_active": False,
    }
    defaults.update(overrides)
    return XeroApp.objects.create(**defaults)


def set_active_quota(
    day_remaining: int, minute_remaining: int = 60, snapshot_age_seconds: int = 0
) -> None:
    """Set the active XeroApp's quota snapshot, creating an active row if needed."""
    snapshot_at = dj_timezone.now() - timedelta(seconds=snapshot_age_seconds)
    if XeroApp.objects.filter(is_active=True).exists():
        XeroApp.objects.filter(is_active=True).update(
            day_remaining=day_remaining,
            minute_remaining=minute_remaining,
            snapshot_at=snapshot_at,
        )
    else:
        make_xero_app(
            is_active=True,
            day_remaining=day_remaining,
            minute_remaining=minute_remaining,
            snapshot_at=snapshot_at,
        )


@pytest.fixture
def non_office_api() -> Client:
    """An authenticated client whose staff member is NOT office staff."""
    staff: Staff = Staff.objects.create_user(
        email="floor@example.test",
        password="s3cret-Pass!",
        first_name="Floor",
        last_name="Staff",
        is_office_staff=False,
    )
    client = Client()
    refresh = RefreshToken.for_user(staff)
    client.cookies[jwt_cookie_config().access_name] = str(refresh.access_token)
    return client
