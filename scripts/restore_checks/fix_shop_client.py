#!/usr/bin/env python
"""Fix shop client name after production restore (anonymized during backup)."""

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from apps.client.models import Client

SHOP_CLIENT_ID = "00000000-0000-0000-0000-000000000001"
NEW_NAME = "Demo Company Shop"

try:
    shop_client = Client.objects.get(id=SHOP_CLIENT_ID)
    old_name = shop_client.name
    shop_client.name = NEW_NAME
    shop_client.save()

    print("Updated shop client:")
    print(f"  Old name: {old_name}")
    print(f"  New name: {shop_client.name}")
    print(f"  ID: {shop_client.id}")
    print(f"  Job count: {shop_client.jobs.count()}")
except Client.DoesNotExist:
    print(f"ERROR: Shop client with ID {SHOP_CLIENT_ID} not found")
    sys.exit(1)
