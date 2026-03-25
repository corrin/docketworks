#!/usr/bin/env python
"""Verify chart of accounts synced from Xero."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from apps.workflow.models import XeroAccount

print(f"Total accounts synced: {XeroAccount.objects.count()}")

sales = XeroAccount.objects.filter(account_code="200").first()
purchases = XeroAccount.objects.filter(account_code="300").first()

print(f"Sales account (200): {sales.account_name if sales else 'NOT FOUND'}")
print(
    f"Purchases account (300): {purchases.account_name if purchases else 'NOT FOUND'}"
)
