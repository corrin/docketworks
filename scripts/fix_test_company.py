#!/usr/bin/env python
"""Create the test company (CompanyDefaults.test_company_name) when missing.

Idempotent restore-time mutation. Pairs with
scripts/restore_checks/check_test_company.py, which is now read-only.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from django.utils import timezone

from apps.company.models import Company
from apps.workflow.models import CompanyDefaults

cd = CompanyDefaults.get_solo()
company = Company.objects.filter(name=cd.test_company_name).first()

if company:
    print(f"Test company already exists: {company.name} (ID: {company.id})")
else:
    company = Company(
        name=cd.test_company_name,
        is_account_customer=False,
        xero_last_modified=timezone.now(),
        xero_last_synced=timezone.now(),
    )
    company.save()
    print(f"Created test company: {company.name} (ID: {company.id})")
