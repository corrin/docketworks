#!/usr/bin/env python
"""Fix shop company name after production restore (anonymized during backup)."""

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from apps.company.models import Company

SHOP_COMPANY_ID = "00000000-0000-0000-0000-000000000001"
NEW_NAME = "Demo Company Shop"

try:
    shop_company = Company.objects.get(id=SHOP_COMPANY_ID)
    old_name = shop_company.name
    shop_company.name = NEW_NAME
    shop_company.save()

    print("Updated shop company:")
    print(f"  Old name: {old_name}")
    print(f"  New name: {shop_company.name}")
    print(f"  ID: {shop_company.id}")
    print(f"  Job count: {shop_company.jobs.count()}")
except Company.DoesNotExist:
    print(f"ERROR: Shop company with ID {SHOP_COMPANY_ID} not found")
    sys.exit(1)
