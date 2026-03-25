#!/usr/bin/env python
"""Verify Xero OAuth token exists and is valid."""

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from django.utils import timezone

from apps.workflow.models import XeroToken

token = XeroToken.objects.first()
if not token:
    print("ERROR: No Xero token found. Login script may have failed.")
    sys.exit(1)

if token.expires_at and token.expires_at < timezone.now():
    print("ERROR: Xero token is expired.")
    sys.exit(1)

print("Xero OAuth token found.")
