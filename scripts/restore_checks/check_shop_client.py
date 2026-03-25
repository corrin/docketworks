#!/usr/bin/env python
"""Verify shop client has correct name."""

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from apps.client.models import Client

SHOP_CLIENT_ID = "00000000-0000-0000-0000-000000000001"

try:
    shop = Client.objects.get(id=SHOP_CLIENT_ID)
    print(f"Shop client: {shop.name}")
except Client.DoesNotExist:
    print(f"ERROR: Shop client with ID {SHOP_CLIENT_ID} not found")
    sys.exit(1)
