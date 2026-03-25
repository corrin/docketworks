#!/usr/bin/env python
"""Check that company defaults are loaded correctly."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from apps.workflow.models import CompanyDefaults

company = CompanyDefaults.get_solo()
print(f"Company defaults loaded: {company.company_name}")
