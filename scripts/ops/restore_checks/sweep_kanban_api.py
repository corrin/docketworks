#!/usr/bin/env python
"""Test the Kanban API endpoint to verify it's working correctly.

Deviation from v1: authentication is a JWT access-token cookie
(apps/core/auth.py), not a Django session, so this uses
ninja_jwt.tokens.RefreshToken instead of v1's client.force_login().
"""

import os
import sys

from dotenv import load_dotenv

from scripts import REPO_ROOT
from scripts.bootstrap import setup_django

# config/settings.py already calls load_dotenv() on import, but APP_DOMAIN is
# read here (for HTTP_HOST) before setup_django() triggers that load.
load_dotenv(REPO_ROOT / ".env")
if "APP_DOMAIN" not in os.environ:
    raise RuntimeError("APP_DOMAIN must be set in .env")
_domain = os.environ["APP_DOMAIN"]

setup_django()

from django.test import Client  # noqa: E402 -- Django must be configured first
from ninja_jwt.tokens import RefreshToken  # noqa: E402

from apps.accounts.models import Staff  # noqa: E402


def test_kanban_api() -> bool:
    """Test the Kanban API endpoint using Django's test client.

    Returns True if successful, False otherwise.
    """
    admin_user = Staff.objects.filter(office_email="defaultadmin@example.com").first()
    if not admin_user:
        print("ERROR: Admin user defaultadmin@example.com not found")
        print("  Run scripts/ops/setup_dev_logins.py first")
        return False

    # v1 used client.force_login() (session auth). v2's API reads a JWT from
    # an HttpOnly cookie instead (apps/core/auth.py); set it the way a
    # logged-in browser has it, matching apps/company/tests/conftest.py's
    # authenticate() helper.
    client = Client()
    refresh = RefreshToken.for_user(admin_user)
    client.cookies["access_token"] = str(refresh.access_token)

    response = client.get("/api/job/jobs/fetch-all/", HTTP_HOST=_domain)

    if response.status_code != 200:
        print(f"ERROR: API returned status {response.status_code}")
        print(f"  Response: {response.content[:500]!r}")
        return False

    # Indexed, not .get()-with-fallback: FetchAllJobsResponse
    # (apps/job/schemas.py) declares every key, and ninja validated the body
    # before it reached here. The old `data.get("total_archived",
    # len(data.get("archived_jobs", [])))` re-derived a count the schema
    # already carries, so a contract change would have printed a plausible
    # wrong number instead of failing.
    data = response.json()

    if not data["success"]:
        print("ERROR: API returned success=false")
        return False

    active_jobs = data["active_jobs"]
    archived_count = data["total_archived"]

    if len(active_jobs) == 0:
        print("ERROR: API returned no active jobs")
        return False

    print(f"API working: {len(active_jobs)} active jobs, {archived_count} archived")
    return True


if __name__ == "__main__":
    print("Testing Kanban API...")
    success = test_kanban_api()
    sys.exit(0 if success else 1)
