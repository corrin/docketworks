#!/usr/bin/env python
"""Verify shop company has correct name."""

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from apps.company.models import Company

SHOP_COMPANY_ID = "00000000-0000-0000-0000-000000000001"

try:
    shop = Company.objects.get(id=SHOP_COMPANY_ID)
    print(f"Shop company: {shop.name}")
except Company.DoesNotExist:
    print(f"ERROR: Shop company with ID {SHOP_COMPANY_ID} not found")
    sys.exit(1)
