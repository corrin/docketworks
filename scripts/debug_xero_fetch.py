"""Debug script: test that RateLimitedRESTClient handles 429 properly.

Usage: python manage.py shell < scripts/debug_xero_fetch.py
"""

import logging

from xero_python.accounting import AccountingApi

from apps.workflow.api.xero.auth import api_client, get_tenant_id

# Show xero logger output
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("xero")
logger.setLevel(logging.DEBUG)

print(f"REST client type: {type(api_client.rest_client).__name__}")

xero_api = AccountingApi(api_client)
tid = get_tenant_id()
print(f"Tenant ID: {tid}")

print("\nCalling get_accounts...")
try:
    r = xero_api.get_accounts(tid)
    print(f"OK: got {len(r.accounts)} accounts")
except Exception as exc:
    print(f"Exception: {type(exc).__name__}: {exc}")

print("\nDone.")
