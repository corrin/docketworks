#!/usr/bin/env python
"""Diagnostic: which contact payload shape survives a Xero round trip.

Pushes three contacts to the connected Xero tenant (Demo Company in dev) using
three different payload shapes, GETs each back, and prints what stuck for each:

   (A) snake_case raw dict   -- the shape v1's production path pushed; it is
                                 how "contact created without email" happened,
                                 because Xero silently ignores unknown keys.
   (B) PascalCase raw dict   -- the same data with Xero's wire-format keys.
   (C) SDK model instance    -- xero_python.accounting.models.Contact; the SDK
                                 applies attribute_map. This is the only shape
                                 v2 pushes (apps/xero/contacts.py
                                 contact_from_company, used by both
                                 sync_company_to_xero and the seeding path's
                                 bulk_create_contacts_in_xero).

Kept as a standing diagnostic rather than a test: the question it answers --
which shapes Xero's create_contacts accepts and which fields it silently
drops -- is external-API behaviour that no mock can witness. If contacts ever
appear in Xero without emails again, run this before touching the sync code.

Usage (from repository root, against a dev/demo tenant only -- it writes
contacts and does not delete them; Demo Company resets monthly):

    uv run python scripts/ops/debug_xero_email_drop.py
"""

import datetime
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from xero_python.accounting import AccountingApi  # noqa: E402 -- Django must be configured first
from xero_python.accounting.models import Address, Contact, Phone  # noqa: E402

from apps.xero.auth import get_api_client, get_tenant_id  # noqa: E402
from apps.xero.constants import SLEEP_TIME  # noqa: E402
from apps.xero.transforms import process_xero_data  # noqa: E402

EMAIL = "tomas@cossiga.test"
PHONE = "027 351 8326"
ADDR_LINE1 = "123 Test Street"


def fetch_back(accounting_api: AccountingApi, tenant_id: str, contact_id: str) -> dict[str, Any]:
    """GET the contact and return its process_xero_data() raw_json (underscore keys)."""
    resp = accounting_api.get_contacts(tenant_id, i_ds=[contact_id])
    time.sleep(SLEEP_TIME)
    if not resp.contacts:
        raise RuntimeError(f"Contact {contact_id} not found on readback")
    raw = process_xero_data(resp.contacts[0])
    if not isinstance(raw, dict):
        raise TypeError(f"process_xero_data returned {type(raw).__name__}, expected dict")
    return raw


def summarise(label: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Pull the fields we care about from raw_json for the comparison table.

    ``.get`` everywhere is deliberate: a missing key is the measurement (the
    field did not survive the round trip), not malformed data to validate away.
    """
    return {
        "label": label,
        "_name": raw.get("_name"),
        "_email_address": raw.get("_email_address"),
        "_is_customer": raw.get("_is_customer"),
        "phones": [
            (p.get("_phone_type"), p.get("_phone_number")) for p in (raw.get("_phones") or [])
        ],
        "addresses": [
            (a.get("_address_type"), a.get("_address_line1")) for a in (raw.get("_addresses") or [])
        ],
        "contact_persons": [
            (p.get("_first_name"), p.get("_last_name"), p.get("_email_address"))
            for p in (raw.get("_contact_persons") or [])
        ],
    }


def push(accounting_api: AccountingApi, tenant_id: str, label: str, payload: object) -> str:
    """Create one contact from the given payload shape and return its contact_id."""
    print(f"=== Pushing {label} ===")
    if isinstance(payload, dict):
        print(f"payload: {json.dumps(payload, indent=2)}")
    else:
        print(f"payload: {payload!r}")
    resp = accounting_api.create_contacts(tenant_id, contacts={"contacts": [payload]})
    time.sleep(SLEEP_TIME)
    if not resp.contacts:
        raise RuntimeError(f"Xero returned no contacts creating the {label} payload")
    contact_id = str(resp.contacts[0].contact_id)
    print(f"created: {contact_id}\n")
    return contact_id


def main() -> None:
    nonce = datetime.datetime.now(tz=datetime.UTC).strftime("%Y%m%d-%H%M%S")
    accounting_api = AccountingApi(get_api_client())
    tenant_id = get_tenant_id()
    print(f"Tenant: {tenant_id}")
    print(f"Run nonce: {nonce}\n")

    snake_payload = {
        "contact_id": "",
        "name": f"ZZ-DEBUG-A-snake-{nonce}",
        "email_address": EMAIL,
        "phones": [{"phone_type": "DEFAULT", "phone_number": PHONE}],
        "addresses": [
            {
                "address_type": "STREET",
                "attention_to": f"ZZ-DEBUG-A-snake-{nonce}",
                "address_line1": ADDR_LINE1,
            }
        ],
        "is_customer": False,
    }
    pascal_payload = {
        "Name": f"ZZ-DEBUG-B-pascal-{nonce}",
        "EmailAddress": EMAIL,
        "Phones": [{"PhoneType": "DEFAULT", "PhoneNumber": PHONE}],
        "Addresses": [
            {
                "AddressType": "STREET",
                "AttentionTo": f"ZZ-DEBUG-B-pascal-{nonce}",
                "AddressLine1": ADDR_LINE1,
            }
        ],
        "IsCustomer": False,
    }
    sdk_contact = Contact(
        name=f"ZZ-DEBUG-C-sdkmodel-{nonce}",
        email_address=EMAIL,
        phones=[Phone(phone_type="DEFAULT", phone_number=PHONE)],
        addresses=[
            Address(
                address_type="STREET",
                attention_to=f"ZZ-DEBUG-C-sdkmodel-{nonce}",
                address_line1=ADDR_LINE1,
            )
        ],
        is_customer=False,
    )

    shapes: list[tuple[str, object]] = [
        ("(A) snake_case raw dict", snake_payload),
        ("(B) PascalCase raw dict", pascal_payload),
        ("(C) xero_python Contact model", sdk_contact),
    ]
    created = [
        (label, push(accounting_api, tenant_id, label, payload)) for label, payload in shapes
    ]

    print("\n" + "=" * 78)
    print("READBACK")
    print("=" * 78)

    raws: list[tuple[str, dict[str, Any]]] = []
    for label, contact_id in created:
        raw = fetch_back(accounting_api, tenant_id, contact_id)
        raws.append((label, raw))
        print(f"\n--- {label} -- {contact_id} ---")
        print(json.dumps(raw, indent=2, default=str))

    print("\n" + "=" * 78)
    print("SUMMARY (fields that survived the round trip)")
    print("=" * 78)

    for label, raw in raws:
        s = summarise(label, raw)
        print(f"\n{s['label']}:")
        print(f"  _name           = {s['_name']!r}")
        print(f"  _email_address  = {s['_email_address']!r}")
        print(f"  _is_customer    = {s['_is_customer']!r}")
        print(f"  phones          = {s['phones']}")
        print(f"  addresses       = {s['addresses']}")
        print(f"  contact_persons = {s['contact_persons']}")

    print("\nDone.")


if __name__ == "__main__":
    main()
