"""Shared test fixtures derived from real Xero API responses.

The JSON snapshots in this directory are captured against Xero Demo Company
via scripts in `adhoc/` (e.g. `adhoc/capture_xero_contact_response.py`). Test
mocks built from these snapshots match the real response shape — populated
fields like `contact_status`, `updated_date_utc`, and the full phones /
addresses arrays — so future tests don't drift away from reality.

Re-run the capture script whenever the SDK or Xero API changes.
"""

import json
from pathlib import Path

from xero_python.accounting.models import Address, Contact, Contacts, Phone

FIXTURES_DIR = Path(__file__).parent
CREATE_CONTACTS_RESPONSE_JSON = FIXTURES_DIR / "xero_create_contacts_response.json"


def _build_contact_from_dict(data: dict) -> Contact:
    """Reconstruct a Contact SDK instance from a captured to_dict() snapshot.

    Fields are enumerated explicitly so unknown SDK additions don't break
    reconstruction; extend here when a test needs a field we don't carry.
    """
    phones_data = data.get("phones") or []
    addresses_data = data.get("addresses") or []
    return Contact(
        contact_id=data.get("contact_id"),
        contact_status=data.get("contact_status"),
        name=data.get("name"),
        email_address=data.get("email_address"),
        is_customer=data.get("is_customer"),
        phones=[
            Phone(
                phone_type=p.get("phone_type"),
                phone_number=p.get("phone_number"),
            )
            for p in phones_data
        ]
        or None,
        addresses=[
            Address(
                address_type=a.get("address_type"),
                address_line1=a.get("address_line1"),
                attention_to=a.get("attention_to"),
            )
            for a in addresses_data
        ]
        or None,
        updated_date_utc=data.get("updated_date_utc"),
    )


def make_create_contacts_response(
    *, contact_id: str | None = None, name: str | None = None
) -> Contacts:
    """Real-shape Contacts wrapper as returned by accounting_api.create_contacts.

    Loaded from a snapshot of a live Xero Demo Company response. Pass
    `contact_id=` or `name=` to override the captured values for a specific
    test scenario; everything else stays as Xero actually returned it.
    """
    snapshot = json.loads(CREATE_CONTACTS_RESPONSE_JSON.read_text())
    if contact_id is not None:
        snapshot["contact_id"] = contact_id
    if name is not None:
        snapshot["name"] = name
    return Contacts(contacts=[_build_contact_from_dict(snapshot)])
