"""What Xero fills in on an object the application did not spell out.

Every value here is read off a recording in ``recordings/`` — the file is
named beside each block — and ``tests/test_defaults.py`` asserts each key is
one that recording carries, so a default that Xero stopped sending, or one
this file invented, fails a test rather than shipping in a body.
"""

from apps.xero.fake.wire import Json

# recordings/organisation.json: the fake's own name in every envelope, so a
# log line or an error body that reached a person says where it came from.
PROVIDER_NAME = "Docketworks fake Xero"

# recordings/contact.json — Xero returns a created contact with the four
# phone slots and the two address slots present and empty.
CONTACT: dict[str, Json] = {
    "ContactStatus": "ACTIVE",
    "Addresses": [{"AddressType": "POBOX"}, {"AddressType": "STREET"}],
    "Phones": [
        {"PhoneType": "DDI"},
        {"PhoneType": "DEFAULT"},
        {"PhoneType": "FAX"},
        {"PhoneType": "MOBILE"},
    ],
    "ContactGroups": [],
    "IsSupplier": False,
    "IsCustomer": False,
    "ContactPersons": [],
    "HasAttachments": False,
    "Attachments": [],
    "HasValidationErrors": False,
}

# recordings/invoice.json
INVOICE: dict[str, Json] = {
    "Type": "ACCREC",
    "Status": "DRAFT",
    "LineAmountTypes": "Exclusive",
    "CreditNotes": [],
    "Prepayments": [],
    "Overpayments": [],
    "AmountPaid": 0,
    "AmountCredited": 0,
    "SentToContact": False,
    "CurrencyRate": 1,
    "IsDiscounted": False,
    "HasAttachments": False,
    "HasErrors": False,
    "Attachments": [],
    "InvoicePaymentServices": [],
}

# recordings/quote.json
QUOTE: dict[str, Json] = {
    "Status": "DRAFT",
    "LineAmountTypes": "EXCLUSIVE",
    "CurrencyRate": 1,
    "Terms": "",
}

# recordings/purchase_order.json
PURCHASE_ORDER: dict[str, Json] = {
    "Type": "PURCHASEORDER",
    "Status": "DRAFT",
    "LineAmountTypes": "Exclusive",
    "CurrencyRate": 1,
    "HasErrors": False,
    "IsDiscounted": False,
    "SentToContact": False,
    "HasAttachments": False,
    "Attachments": [],
}

# recordings/invoice.json, first line item: a line always carries its
# tracking list, empty when nothing is tracked.
LINE_ITEM: dict[str, Json] = {"Tracking": []}

# Xero's first number for a new organisation, by document kind: the
# sequence the store continues from when it holds nothing of the kind.
FIRST_NUMBER = {"invoice": "INV-0001", "quote": "QU-0001", "purchase_order": "PO-0001"}
