#!/usr/bin/env python
"""Verify the test client (CompanyDefaults.test_client_name) exists. Read-only."""

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from apps.client.models import Client
from apps.workflow.models import CompanyDefaults

cd = CompanyDefaults.get_solo()
client = Client.objects.filter(name=cd.test_client_name).first()

if not client:
    print(
        f"ERROR: Test client {cd.test_client_name!r} not found — "
        "run scripts/fix_test_client.py first"
    )
    sys.exit(1)

print(f"Test client: {client.name} (ID: {client.id})")
