"""Populate XeroApp from the legacy XeroToken row + env vars.

On a fresh install (no env, no token) the table stays empty and the user
adds the first row via the UI. On an existing install, this produces one
row labeled "Primary" marked is_active=True with the credentials and
tokens that were previously in .env / XeroToken.

Env vars are read directly from os.environ rather than settings — the
follow-up migration (0219) drops XeroToken and the same-PR settings.py
cleanup removes the XERO_CLIENT_* settings entries. Reading os.environ
keeps the migration replayable on a clean checkout.

Fail-early posture: if the install has a legacy XeroToken row but is
MISSING any of the three env vars, the migration raises rather than
silently skipping. Otherwise the next migration (0219) drops XeroToken
permanently and the install has no Xero credentials at all.
"""

import os

from django.db import migrations


def populate_from_legacy(apps, schema_editor):
    XeroApp = apps.get_model("workflow", "XeroApp")
    XeroToken = apps.get_model("workflow", "XeroToken")

    client_id = os.environ.get("XERO_CLIENT_ID")
    client_secret = os.environ.get("XERO_CLIENT_SECRET")
    redirect_uri = os.environ.get("XERO_REDIRECT_URI")

    legacy = XeroToken.objects.first()
    env_present = bool(client_id and client_secret and redirect_uri)

    # Legacy token + missing env: silently dropping the token here (the
    # next migration deletes XeroToken) would leave the install with no
    # Xero credentials at all. Fail loudly so the operator either fixes
    # .env first or accepts the loss explicitly. Other partial-state
    # combinations are recoverable: missing legacy with env present is a
    # fresh deployment that just needs the operator to OAuth once via the
    # UI; both missing is a brand-new install.
    if legacy is not None and not env_present:
        missing = [
            name
            for name, value in (
                ("XERO_CLIENT_ID", client_id),
                ("XERO_CLIENT_SECRET", client_secret),
                ("XERO_REDIRECT_URI", redirect_uri),
            )
            if not value
        ]
        raise RuntimeError(
            "Cannot migrate XeroToken to XeroApp: legacy token row exists "
            f"but env vars are missing: {', '.join(missing)}. Set them in "
            ".env (the values are still available in your previous "
            "deployment's environment) and retry the migrate."
        )

    # Same skip path as before: only seed when both sides are present.
    if not env_present or legacy is None:
        return

    if XeroApp.objects.filter(client_id=client_id).exists():
        return

    XeroApp.objects.create(
        label="Primary",
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        is_active=True,
        tenant_id=legacy.tenant_id,
        token_type=legacy.token_type,
        access_token=legacy.access_token,
        refresh_token=legacy.refresh_token,
        expires_at=legacy.expires_at,
        scope=legacy.scope,
    )


def reverse_populate(apps, schema_editor):
    # Narrow to the row this migration would have created — matched by
    # client_id, the only field that uniquely identifies the legacy app.
    # Filtering by label="Primary" alone would also delete any row a user
    # later renamed/created as "Primary" via the UI.
    XeroApp = apps.get_model("workflow", "XeroApp")
    client_id = os.environ.get("XERO_CLIENT_ID")
    if not client_id:
        return
    XeroApp.objects.filter(client_id=client_id, label="Primary").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0217_xeroapp"),
    ]
    operations = [
        migrations.RunPython(populate_from_legacy, reverse_populate),
    ]
