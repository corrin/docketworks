#!/usr/bin/env python
"""Verify the install's XeroApp row was loaded from the per-install fixture.

Runs after `loaddata apps/workflow/fixtures/xero_apps.json` and BEFORE the
OAuth step, so token columns are expected to be null. Just asserts that
exactly one row is marked active.
"""

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from apps.workflow.models import XeroApp

active = XeroApp.objects.filter(is_active=True)
count = active.count()
if count == 0:
    print(
        "ERROR: No active XeroApp row. Did you copy "
        "apps/workflow/fixtures/xero_apps.json.example to xero_apps.json, "
        "fill in your credentials, and run loaddata?"
    )
    sys.exit(1)
if count > 1:
    print(f"ERROR: {count} XeroApp rows marked is_active=True; expected exactly 1.")
    sys.exit(1)

row = active.first()
print(f"XeroApp configured: {row.label}")
