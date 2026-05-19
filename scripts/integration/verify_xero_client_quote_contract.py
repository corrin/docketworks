#!/usr/bin/env python
"""Verify the public app API and Xero agree on client/quote contact data.

App writes go through the configured public app URL. Xero verification uses
official Xero SDK read APIs. This creates real local records and real Xero
records, and leaves them in place for investigation.

Required environment is loaded from `.env` and `frontend/.env` when present:
    APP_DOMAIN or APP_BASE_URL
    E2E_TEST_USERNAME
    E2E_TEST_PASSWORD

Usage:
    ./.venv/bin/python scripts/integration/verify_xero_client_quote_contract.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[2]


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


load_env(ROOT / ".env")
load_env(ROOT / "frontend" / ".env")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from xero_python.accounting import AccountingApi

from apps.workflow.api.xero.auth import api_client, get_tenant_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("verify_xero_client_quote_contract")


def app_base_url() -> str:
    explicit = os.getenv("APP_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    domain = os.environ["APP_DOMAIN"]
    return f"https://{domain}".rstrip("/")


BASE_URL = app_base_url()
USERNAME = os.environ["E2E_TEST_USERNAME"]
PASSWORD = os.environ["E2E_TEST_PASSWORD"]
SESSION = requests.Session()
SESSION.headers.update(
    {"Accept": "application/json", "ngrok-skip-browser-warning": "true"}
)


def app_request(method: str, path: str, **kwargs: Any) -> Any:
    response = SESSION.request(method, f"{BASE_URL}{path}", timeout=90, **kwargs)
    log.info("%s %s -> %s", method, path, response.status_code)
    try:
        body = response.json()
    except ValueError:
        body = response.text
    log.info("app response: %s", body)
    response.raise_for_status()
    return body


def xero_contact(contact_id: str):
    response = AccountingApi(api_client).get_contacts(
        get_tenant_id(), i_ds=[contact_id], include_archived=True
    )
    if not response or not response.contacts:
        raise AssertionError(f"Xero did not return contact {contact_id}")
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


def xero_quote(quote_id: str):
    response = AccountingApi(api_client).get_quote(get_tenant_id(), quote_id)
    if not response or not response.quotes:
        raise AssertionError(f"Xero did not return quote {quote_id}")
    quote = response.quotes[0]
    log.info(
        "xero quote: id=%s number=%r contact_id=%s contact_name=%r",
        quote.quote_id,
        quote.quote_number,
        getattr(quote.contact, "contact_id", None),
        getattr(quote.contact, "name", None),
    )
    return quote


def assert_contact_contract(contact, expected: dict[str, str]) -> None:
    phone_numbers = {p.phone_number for p in contact.phones or []}
    address_lines = {a.address_line1 for a in contact.addresses or []}
    assert contact.name == expected["name"], (contact.name, expected["name"])
    assert contact.email_address == expected["email"], (
        contact.email_address,
        expected["email"],
    )
    assert expected["phone"] in phone_numbers, phone_numbers
    assert expected["address"] in address_lines, address_lines


log.info("app base URL: %s", BASE_URL)
login = app_request(
    "POST",
    "/api/accounts/token/",
    json={"username": USERNAME, "password": PASSWORD},
)
if isinstance(login, dict) and login.get("access"):
    SESSION.headers["Authorization"] = f"Bearer {login['access']}"

ping = app_request("GET", "/api/xero/ping/")
assert ping.get("connected") is True, ping

run_id = uuid.uuid4().hex[:8]
client_payload = {
    "name": f"ZZ-XERO-CONTRACT-{run_id}",
    "email": f"xero-contract-{run_id}@example.test",
    "phone": "027 351 8326",
    "address": "123 Contract Street",
    "is_account_customer": True,
    "allow_jobs": True,
}
log.info("client request: %s", json.dumps(client_payload, sort_keys=True))
client = app_request("POST", "/api/clients/create/", json=client_payload)["client"]
assert client["email"] == client_payload["email"], client
assert client["phone"] == client_payload["phone"], client
assert client["address"] == client_payload["address"], client
assert client["xero_contact_id"], client

created_contact = xero_contact(client["xero_contact_id"])
assert_contact_contract(created_contact, client_payload)

job_payload = {
    "name": f"Xero Contract Job {run_id}",
    "client_id": client["id"],
    "description": "Xero contract smoke test",
    "pricing_methodology": "fixed_price",
    "estimated_materials": "1000.00",
    "estimated_time": "4.00",
}
log.info("job request: %s", json.dumps(job_payload, sort_keys=True))
job = app_request("POST", "/api/job/jobs/", json=job_payload)
job_id = job["job_id"]

job_readback = app_request("GET", f"/api/job/jobs/{job_id}/")["data"]["job"]
assert job_readback["client_id"] == client["id"], job_readback

quote = app_request(
    "POST", f"/api/xero/create_quote/{job_id}", json={"breakdown": False}
)
quote_readback = xero_quote(quote["xero_id"])
assert str(quote_readback.contact.contact_id) == client["xero_contact_id"], (
    quote_readback.contact.contact_id,
    client["xero_contact_id"],
)

contact_after_quote = xero_contact(client["xero_contact_id"])
assert_contact_contract(contact_after_quote, client_payload)

log.info("PASS")
log.info("client_id=%s", client["id"])
log.info("xero_contact_id=%s", client["xero_contact_id"])
log.info("job_id=%s", job_id)
log.info("xero_quote_id=%s", quote["xero_id"])
log.info("email=%s", client_payload["email"])

sys.exit(0)
