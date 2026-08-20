"""Factories and fixtures for the Xero app's tests."""

from collections.abc import Iterator
from contextlib import ExitStack
from datetime import timedelta
from typing import TypedDict, Unpack
from unittest.mock import patch

import pytest
from django.test import Client
from django.utils import timezone as dj_timezone
from ninja_jwt.tokens import RefreshToken

from apps.accounts.models import Staff
from apps.core.auth import jwt_cookie_config
from apps.xero.models import XeroApp

TEST_TENANT_ID = "test-tenant-id"

# Every path that writes a Xero id also stamps the connected tenant, and
# resolving it needs a live Xero session these suites deliberately do not have.
# Patched per binding rather than at apps.xero.auth: each module imports the
# function by name, so the source binding is not the one they call.
_TENANT_ID_BINDINGS = (
    "apps.xero.documents.invoice.get_tenant_id",
    "apps.xero.documents.po.get_tenant_id",
    "apps.xero.documents.quote.get_tenant_id",
    "apps.xero.raw_fields.get_tenant_id",
)


@pytest.fixture(autouse=True)
def xero_tenant_id() -> Iterator[str]:
    """Resolve the connected tenant to a fixed id for every Xero test.

    Autouse, not opt-in: an unconfigured Xero session is a property of the
    whole suite, and the alternative — a usefixtures marker on each of the
    seven modules that push or sync a document — leaves the eighth silently
    asserting a RuntimeError instead of the behaviour it was written for.
    """
    with ExitStack() as stack:
        for target in _TENANT_ID_BINDINGS:
            stack.enter_context(patch(target, return_value=TEST_TENANT_ID))
        yield TEST_TENANT_ID


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
        office_email="floor@example.test",
        password="s3cret-Pass!",
        first_name="Floor",
        last_name="Staff",
        is_office_staff=False,
    )
    client = Client()
    refresh = RefreshToken.for_user(staff)
    client.cookies[jwt_cookie_config().access_name] = str(refresh.access_token)
    return client
