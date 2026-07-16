#!/usr/bin/env python
"""Verify the test company (CompanyDefaults.test_company_name) exists. Read-only."""

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from apps.company.models import Company
from apps.workflow.models import CompanyDefaults

cd = CompanyDefaults.get_solo()
company = Company.objects.filter(name=cd.test_company_name).first()

if not company:
    print(
        f"ERROR: Test company {cd.test_company_name!r} not found — "
        "run scripts/fix_test_company.py first"
    )
    sys.exit(1)

print(f"Test company: {company.name} (ID: {company.id})")
