#!/usr/bin/env python
"""Test the Kanban API endpoint to verify it's working correctly."""

import os
import sys

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jobs_manager.settings")
os.environ.setdefault("HTTP_HOST", "localhost:8000")

import django

django.setup()

from django.test import Client

from apps.accounts.models import Staff


def test_kanban_api() -> bool:
    """Test the Kanban API endpoint using Django's test client.

    Returns True if successful, False otherwise.
    """
    # Get admin user for authentication
    admin_user = Staff.objects.filter(email="defaultadmin@example.com").first()
    if not admin_user:
        print("✗ ERROR: Admin user defaultadmin@example.com not found")
        print("  Run scripts/restore_checks/create_admin_user.py first")
        return False

    # Create test client and authenticate
    client = Client()
    client.force_login(admin_user)

    # Make authenticated request to Kanban API
    response = client.get("/api/job/jobs/fetch-all/", HTTP_HOST="localhost:8000")

    if response.status_code != 200:
        print(f"✗ ERROR: API returned status {response.status_code}")
        if hasattr(response, "content"):
            print(f"  Response: {response.content[:500]}")
        return False

    data = response.json()

    # Check API response structure
    if not data.get("success"):
        print("✗ ERROR: API returned success=false")
        if "error" in data:
            print(f"  Error: {data['error']}")
        return False

    active_jobs = data.get("active_jobs", [])
    archived_count = data.get("total_archived", len(data.get("archived_jobs", [])))

    if len(active_jobs) == 0:
        print("✗ ERROR: API returned no active jobs")
        return False

    print(f"✓ API working: {len(active_jobs)} active jobs, {archived_count} archived")
    return True


if __name__ == "__main__":
    print("Testing Kanban API...")
    success = test_kanban_api()
    sys.exit(0 if success else 1)
