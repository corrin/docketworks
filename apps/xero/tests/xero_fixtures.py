"""Builders for Xero contact test data.

Two levels, matching the two seams the sync code has:

- ``make_xero_contact`` returns a real ``xero_python`` Contact. The SDK stores
  its fields underscore-prefixed in ``__dict__``, so ``process_xero_data``
  produces production-shaped ``raw_json`` from it without any mocking —
  ``sync_companies`` tests run the whole pipeline for real.
- ``make_contact_raw_json`` returns the stored ``raw_json`` dict directly, for
  tests that exercise ``set_company_fields`` on an already-synced row. The
  shape is copied from real production records (v1's test fixture): the full
  set of underscore-prefixed fields ``process_xero_data`` produces.
"""

from xero_python.accounting import Contact


def make_xero_contact(
    contact_id: str,
    name: str,
    status: str = "ACTIVE",
    merged_to: str | None = None,
) -> Contact:
    """A real SDK Contact carrying what sync_companies and set_company_fields read.

    ``is_customer`` is always present on a fetched Xero contact; leaving it as
    the SDK's None would store NULL into the NOT NULL ``is_account_customer``.
    """
    return Contact(
        contact_id=contact_id,
        name=name,
        contact_status=status,
        merged_to_contact_id=merged_to,
        is_customer=False,
    )


def make_contact_raw_json(
    contact_id: str,
    name: str,
    status: str = "ACTIVE",
    merged_to: str | None = None,
) -> dict[str, object]:
    """Production-shaped stored raw_json for a Xero contact."""
    return {
        "_contact_id": contact_id,
        "_merged_to_contact_id": merged_to,
        "_contact_number": None,
        "_account_number": None,
        "_contact_status": status,
        "_name": name,
        "_first_name": None,
        "_last_name": None,
        "_company_number": None,
        "_email_address": "",
        "_contact_persons": [],
        "_bank_account_details": "",
        "_tax_number": None,
        "_tax_number_type": None,
        "_accounts_receivable_tax_type": None,
        "_accounts_payable_tax_type": None,
        "_addresses": [
            {
                "_address_type": "STREET",
                "_address_line1": None,
                "_address_line2": None,
                "_address_line3": None,
                "_address_line4": None,
                "_city": "",
                "_region": "",
                "_postal_code": "",
                "_country": "",
                "_attention_to": None,
                "discriminator": None,
            },
            {
                "_address_type": "POBOX",
                "_address_line1": None,
                "_address_line2": None,
                "_address_line3": None,
                "_address_line4": None,
                "_city": "",
                "_region": "",
                "_postal_code": "",
                "_country": "",
                "_attention_to": None,
                "discriminator": None,
            },
        ],
        "_phones": [
            {
                "_phone_type": "DDI",
                "_phone_number": "",
                "_phone_area_code": "",
                "_phone_country_code": "",
                "discriminator": None,
            },
            {
                "_phone_type": "DEFAULT",
                "_phone_number": "",
                "_phone_area_code": "",
                "_phone_country_code": "",
                "discriminator": None,
            },
            {
                "_phone_type": "FAX",
                "_phone_number": "",
                "_phone_area_code": "",
                "_phone_country_code": "",
                "discriminator": None,
            },
            {
                "_phone_type": "MOBILE",
                "_phone_number": "",
                "_phone_area_code": "",
                "_phone_country_code": "",
                "discriminator": None,
            },
        ],
        "_is_supplier": False,
        "_is_customer": False,
        "_sales_default_line_amount_type": None,
        "_purchases_default_line_amount_type": None,
        "_default_currency": None,
        "_xero_network_key": None,
        "_sales_default_account_code": None,
        "_purchases_default_account_code": None,
        "_sales_tracking_categories": None,
        "_purchases_tracking_categories": None,
        "_tracking_category_name": None,
        "_tracking_category_option": None,
        "_payment_terms": None,
        "_updated_date_utc": "2026-02-14T23:49:10.183000+00:00",
        "_contact_groups": [],
        "_website": None,
        "_branding_theme": None,
        "_batch_payments": None,
        "_discount": None,
        "_balances": None,
        "_attachments": None,
        "_has_attachments": False,
        "_validation_errors": None,
        "_has_validation_errors": False,
        "_status_attribute_string": None,
        "discriminator": None,
    }
