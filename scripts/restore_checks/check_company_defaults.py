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
        "logo_wide is empty — fixture not loaded, or app_images PNGs not "
        "copied into MEDIA_ROOT. Re-run restore-prod-to-nonprod Step 6."
    )
print(f"logo_wide: {company.logo_wide.name}")
