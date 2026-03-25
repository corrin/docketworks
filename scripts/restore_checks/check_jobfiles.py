#!/usr/bin/env python
"""Verify dummy files exist for all JobFile instances."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from django.conf import settings

from apps.job.models import JobFile

total_files = (
    JobFile.objects.filter(file_path__isnull=False).exclude(file_path="").count()
)
existing_files = 0

for job_file in JobFile.objects.filter(file_path__isnull=False).exclude(file_path=""):
    dummy_path = os.path.join(settings.DROPBOX_WORKFLOW_FOLDER, str(job_file.file_path))
    if os.path.exists(dummy_path):
        existing_files += 1

print(f"Total JobFile records with file_path: {total_files}")
print(f"Dummy files created: {existing_files}")
print(f"Missing files: {total_files - existing_files}")
