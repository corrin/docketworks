"""Factories for Xero auth-core tests."""

from typing import TypedDict, Unpack

from apps.xero.models import XeroApp


class XeroAppOverrides(TypedDict, total=False):
    """The XeroApp columns tests vary."""

    label: str
    client_id: str
    client_secret: str
    redirect_uri: str
    is_active: bool
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
