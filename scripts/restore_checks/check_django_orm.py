#!/usr/bin/env python
"""Test Django ORM access to restored data."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import Job

print(f"Jobs: {Job.objects.count()}")
print(f"Staff: {Staff.objects.count()}")
print(f"Clients: {Client.objects.count()}")

job = Job.objects.first()
if job:
    print(f"Sample job: {job.name} (#{job.job_number})")
    print(f"Contact: {job.contact.name if job.contact else 'None'}")
else:
    print("ERROR: No jobs found")
