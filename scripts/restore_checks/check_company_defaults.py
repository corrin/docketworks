#!/usr/bin/env python
"""Check that company defaults are loaded correctly."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from apps.workflow.models import CompanyDefaults

company = CompanyDefaults.get_solo()
print(f"Company defaults loaded: {company.company_name}")

if not company.logo_wide:
    raise SystemExit(
        "logo_wide is empty — re-run restore-prod-to-nonprod Step 5 "
        "(loaddata company_defaults.json)."
    )
print(f"logo_wide: {company.logo_wide.name}")
