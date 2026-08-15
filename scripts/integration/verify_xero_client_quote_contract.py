#!/usr/bin/env python
"""Verify the public app API and Xero agree on company/quote contact data.

INTEGRATION SCRIPT — creates real data. App writes go through the configured
public app URL; Xero verification uses official Xero SDK read APIs. This
creates real local records and real Xero records, leaves them in place for
investigation, and is never part of the default test suite.

v2 wire differences from v1 (the API is free outside pinned URLs): login
sets HttpOnly cookies instead of returning bearer tokens, and job creation
takes ``company_id`` rather than ``client_id``.

Required environment (repo ``.env`` is loaded by settings; the E2E login
comes from ``frontend/.env.test`` / ``frontend/.env`` when present):
    APP_DOMAIN or APP_BASE_URL
    E2E_TEST_USERNAME
    E2E_TEST_PASSWORD

Usage:
    uv run python -m scripts.integration.verify_xero_client_quote_contract
"""

import json
import logging
import os
import sys
import uuid
from typing import Any

import requests
from dotenv import load_dotenv
from xero_python.accounting import AccountingApi, Contact, Quote

from scripts import REPO_ROOT
from scripts.bootstrap import setup_django

# .env.test first: like playwright.config.ts it must win over frontend/.env,
# and load_dotenv never overrides variables that are already set.
load_dotenv(REPO_ROOT / "frontend" / ".env.test")
load_dotenv(REPO_ROOT / "frontend" / ".env")

setup_django()

from apps.xero.auth import (  # noqa: E402 -- Django must be configured first
    get_api_client,
    get_tenant_id,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("verify_xero_client_quote_contract")

# App/provider JSON payloads carry no schema of their own here; every value is
# asserted at its use site, so dict[str, Any] is the honest type.
Payload = dict[str, Any]


class ContractViolationError(Exception):
    """The app and Xero disagree (or a response was malformed).

    A named exception rather than ``assert``: S101 aside, asserts vanish
    under ``python -O``, and a contract check whose checks can be compiled
    out is not a check.
    """


def check(condition: bool, message: str, detail: object) -> None:
    """Raise ContractViolationError with the offending detail unless condition holds."""
    if not condition:
        raise ContractViolationError(f"{message}: {detail!r}")


def app_base_url() -> str:
    """The public app URL: APP_BASE_URL wins, else https://APP_DOMAIN."""
    explicit = os.getenv("APP_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    return f"https://{os.environ['APP_DOMAIN']}".rstrip("/")


def require_credentials() -> tuple[str, str]:
    """The E2E login pair, refusing to start without both."""
    missing = [k for k in ("E2E_TEST_USERNAME", "E2E_TEST_PASSWORD") if not os.environ.get(k)]
    if missing:
        raise SystemExit(
            f"Missing {', '.join(missing)}: set them in frontend/.env.test "
            "(the same file the Playwright suite reads)."
        )
    return os.environ["E2E_TEST_USERNAME"], os.environ["E2E_TEST_PASSWORD"]


BASE_URL = app_base_url()
SESSION = requests.Session()
SESSION.headers.update({"Accept": "application/json", "ngrok-skip-browser-warning": "true"})


def app_request(method: str, path: str, **kwargs: Any) -> Payload:
    """Call the public app API, logging both directions; non-2xx raises."""
    response = SESSION.request(method, f"{BASE_URL}{path}", timeout=90, **kwargs)
    log.info("%s %s -> %s", method, path, response.status_code)
    try:
        body = response.json()
    except ValueError:
        body = response.text
    log.info("app response: %s", body)
    response.raise_for_status()
    if not isinstance(body, dict):
        # The explicit guard (not check()) is what narrows the json() Any for mypy.
        raise ContractViolationError(f"{method} {path} returned non-object JSON: {body!r}")
    return body


def xero_contact(contact_id: str) -> Contact:
    """Read one contact back from Xero via the official SDK."""
    response = AccountingApi(get_api_client()).get_contacts(
        get_tenant_id(), i_ds=[contact_id], include_archived=True
    )
    if not response or not response.contacts:
        raise ContractViolationError(f"Xero did not return contact {contact_id}")
    contact = response.contacts[0]
    phones = [(p.phone_type, p.phone_number) for p in contact.phones or []]
    addresses = [(a.address_type, a.address_line1) for a in contact.addresses or []]
    log.info(
        "xero contact: id=%s name=%r email=%r phones=%r addresses=%r",
        contact.contact_id,
        contact.name,
        contact.email_address,
        phones,
        addresses,
    )
    return contact


def xero_quote(quote_id: str) -> Quote:
    """Read one quote back from Xero via the official SDK."""
    response = AccountingApi(get_api_client()).get_quote(get_tenant_id(), quote_id)
    if not response or not response.quotes:
        raise ContractViolationError(f"Xero did not return quote {quote_id}")
    quote = response.quotes[0]
    log.info(
        "xero quote: id=%s number=%r contact_id=%s contact_name=%r",
        quote.quote_id,
        quote.quote_number,
        quote.contact.contact_id if quote.contact else None,
        quote.contact.name if quote.contact else None,
    )
    return quote


def assert_contact_contract(contact: Contact, expected: Payload) -> None:
    """Check Xero persisted the name/email/phone/address the app sent."""
    phone_numbers = {p.phone_number for p in contact.phones or []}
    address_lines = {a.address_line1 for a in contact.addresses or []}
    check(contact.name == expected["name"], "contact name", (contact.name, expected["name"]))
    check(
        contact.email_address == expected["email"],
        "contact email",
        (contact.email_address, expected["email"]),
    )
    check(expected["phone"] in phone_numbers, "contact phone", phone_numbers)
    check(expected["address"] in address_lines, "contact address", address_lines)


def main() -> int:
    username, password = require_credentials()
    log.info("app base URL: %s", BASE_URL)

    # Login sets HttpOnly access/refresh cookies on the session; the body
    # carries no tokens in v2 (cookie-based auth).
    app_request(
        "POST",
        "/api/accounts/token/",
        json={"username": username, "password": password},
    )

    ping = app_request("GET", "/api/xero/ping/")
    check(ping.get("connected") is True, "xero ping not connected", ping)

    run_id = uuid.uuid4().hex[:8]
    client_payload: Payload = {
        "name": f"ZZ-XERO-CONTRACT-{run_id}",
        "email": f"xero-contract-{run_id}@example.test",
        "phone": "027 351 8326",
        "address": "123 Contract Street",
        "is_account_customer": True,
        "allow_jobs": True,
    }
    log.info("company request: %s", json.dumps(client_payload, sort_keys=True))
    company = app_request("POST", "/api/companies/create/", json=client_payload)["company"]
    check(company["email"] == client_payload["email"], "company email", company)
    check(company["phone"] == client_payload["phone"], "company phone", company)
    check(company["address"] == client_payload["address"], "company address", company)
    check(bool(company["xero_contact_id"]), "company xero_contact_id missing", company)

    created_contact = xero_contact(company["xero_contact_id"])
    assert_contact_contract(created_contact, client_payload)

    job_payload = {
        "name": f"Xero Contract Job {run_id}",
        "company_id": company["id"],
        "description": "Xero contract smoke test",
        "pricing_methodology": "fixed_price",
        "estimated_materials": "1000.00",
        "estimated_time": "4.00",
    }
    log.info("job request: %s", json.dumps(job_payload, sort_keys=True))
    job = app_request("POST", "/api/job/jobs/", json=job_payload)
    job_id = job["job_id"]

    job_readback = app_request("GET", f"/api/job/jobs/{job_id}/")["data"]["job"]
    check(job_readback["company_id"] == company["id"], "job company_id", job_readback)

    quote = app_request("POST", f"/api/xero/create_quote/{job_id}", json={"breakdown": False})
    quote_readback = xero_quote(quote["xero_id"])
    if quote_readback.contact is None:
        raise ContractViolationError(f"Xero quote {quote['xero_id']} has no contact")
    check(
        str(quote_readback.contact.contact_id) == company["xero_contact_id"],
        "quote contact id",
        (quote_readback.contact.contact_id, company["xero_contact_id"]),
    )

    contact_after_quote = xero_contact(company["xero_contact_id"])
    assert_contact_contract(contact_after_quote, client_payload)

    log.info("PASS")
    log.info("company_id=%s", company["id"])
    log.info("xero_contact_id=%s", company["xero_contact_id"])
    log.info("job_id=%s", job_id)
    log.info("xero_quote_id=%s", quote["xero_id"])
    log.info("email=%s", client_payload["email"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
