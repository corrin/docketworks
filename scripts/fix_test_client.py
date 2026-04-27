#!/usr/bin/env python
"""Create the test client (CompanyDefaults.test_client_name) when missing.

Idempotent restore-time mutation. Pairs with
scripts/restore_checks/check_test_client.py, which is now read-only.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from django.utils import timezone

from apps.client.models import Client
from apps.workflow.models import CompanyDefaults

cd = CompanyDefaults.get_solo()
client = Client.objects.filter(name=cd.test_client_name).first()

if client:
    print(f"Test client already exists: {client.name} (ID: {client.id})")
else:
    client = Client(
        name=cd.test_client_name,
        is_account_customer=False,
        xero_last_modified=timezone.now(),
        xero_last_synced=timezone.now(),
    )
    client.save()
    print(f"Created test client: {client.name} (ID: {client.id})")
