"""Populate XeroApp from the legacy XeroToken row + env vars.

On a fresh install (no env, no token) the table stays empty and the user
adds the first row via the UI. On an existing install, this produces one
row labeled "Primary" marked is_active=True with the credentials and
tokens that were previously in .env / XeroToken.

Env vars are read directly from os.environ rather than settings — the
follow-up migration (0219) drops XeroToken and the same-PR settings.py
cleanup removes the XERO_CLIENT_* settings entries. Reading os.environ
keeps the migration replayable on a clean checkout.
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

    if not client_id or not client_secret or not redirect_uri or legacy is None:
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
    XeroApp = apps.get_model("workflow", "XeroApp")
    XeroApp.objects.filter(label="Primary").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0217_xeroapp"),
    ]
    operations = [
        migrations.RunPython(populate_from_legacy, reverse_populate),
    ]
