#!/usr/bin/env python
"""Verify Xero seed completed successfully."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.job.models import Job
from apps.purchasing.models import Stock

companies_with_xero = Company.objects.filter(xero_contact_id__isnull=False).count()
jobs_with_xero = Job.objects.filter(xero_project_id__isnull=False).count()
stock_with_xero = Stock.objects.filter(xero_id__isnull=False, is_active=True).count()
staff_with_xero = Staff.objects.filter(
    xero_user_id__isnull=False, date_left__isnull=True
).count()

print(f"Companies linked to Xero: {companies_with_xero}")
print(f"Jobs linked to Xero: {jobs_with_xero}")
print(f"Stock items synced to Xero: {stock_with_xero}")
print(f"Staff linked to Xero Payroll: {staff_with_xero}")
