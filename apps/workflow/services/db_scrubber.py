"""
Scrubs a restored copy of prod (in the `scrub` DB alias) of all PII.

Reproduces three behaviours from the legacy backport_data_backup command:
  1. Anonymise the columns in PII_CONFIG (+ _anonymize_staff).
  2. Delete the unlinked accounting records that _filter_unlinked_accounting_records dropped.
  3. Truncate the tables in EXCLUDE_MODELS (minus framework tables).

Anything beyond that is OUT OF SCOPE for this task and must NOT be added without
a separate ticket — see docs/plans/2026-04-25-pg-dump-backport-refresh-plan.md
"Strict like-for-like contract".

Safety: refuses to run unless settings.DATABASES["scrub"]["NAME"] ends in
"_scrub" — last line of defence against a misconfigured SCRUB_DB_NAME pointing
at prod.
"""

from django.conf import settings
from django.db import transaction
from faker import Faker

from apps.accounting.models import (
    Bill,
    BillLineItem,
    CreditNote,
    CreditNoteLineItem,
    Invoice,
    Quote,
)
from apps.accounts.models import Staff
from apps.accounts.staff_anonymization import create_staff_profile
from apps.client.models import Client, ClientContact
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.error_persistence import persist_app_error

SCRUB_ALIAS = "scrub"
_GENERATE_ATTEMPTS = 100


def _assert_scrub_alias_is_safe() -> None:
    name = settings.DATABASES[SCRUB_ALIAS]["NAME"]
    if not name or not name.endswith("_scrub"):
        raise RuntimeError(
            f"SCRUB_DB_NAME ({name!r}) must end in '_scrub'. "
            "Refusing to run scrubber against anything else."
        )


def _scrub_staff() -> None:
    """Mirror legacy _anonymize_staff: coherent profiles, unique emails.

    Touches first_name, last_name, preferred_name, email only — matches the
    legacy behaviour. xero_user_id and password are intentionally left alone.
    """
    used_emails: set[str] = set()
    for staff in Staff.objects.using(SCRUB_ALIAS).all():
        for _ in range(_GENERATE_ATTEMPTS):
            profile = create_staff_profile()
            if profile["email"] not in used_emails:
                break
        else:
            raise RuntimeError(
                f"Could not generate unique staff email after "
                f"{_GENERATE_ATTEMPTS} attempts; {len(used_emails)} in use."
            )
        used_emails.add(profile["email"])
        staff.email = profile["email"]
        staff.first_name = profile["first_name"]
        staff.last_name = profile["last_name"]
        staff.preferred_name = profile["preferred_name"]
        staff.save(
            using=SCRUB_ALIAS,
            update_fields=["email", "first_name", "last_name", "preferred_name"],
        )


def _preserved_client_names() -> set[str]:
    """Names that must survive scrubbing: shop, test client, scraper suppliers.

    Mirrors legacy backport_data_backup._get_preserved_client_names() exactly.
    """
    preserved: set[str] = set()
    try:
        cd = CompanyDefaults.objects.using(SCRUB_ALIAS).get()
    except CompanyDefaults.DoesNotExist:
        pass
    else:
        if cd.shop_client_name:
            preserved.add(cd.shop_client_name)
        if cd.test_client_name:
            preserved.add(cd.test_client_name)

    from apps.quoting.management.commands.run_scrapers import Command as ScraperCmd

    for scraper_info in ScraperCmd().get_available_scrapers():
        supplier_name = getattr(scraper_info["class_obj"], "SUPPLIER_NAME", None)
        if supplier_name:
            preserved.add(supplier_name)
    return preserved


def _scrub_clients() -> None:
    """Mirror legacy PII_CONFIG entries for client.client and client.clientcontact.

    Top-level fields touched: name (with allow-list), primary_contact_name,
    primary_contact_email, email, phone.
    raw_json paths touched: _name, _email_address, _bank_account_details,
    _phones[]._phone_number, _batch_payments._bank_account_number,
    _batch_payments._bank_account_name.

    Anything else (address, all_phones, additional_contact_persons,
    supplierpickupaddress, other raw_json keys) is left untouched — matches
    today's behaviour exactly.
    """
    fake = Faker()
    preserved = _preserved_client_names()
    used_company_names: set[str] = set()

    for client in Client.objects.using(SCRUB_ALIAS).exclude(name__in=preserved):
        for _ in range(1000):
            candidate = fake.company()
            if candidate not in used_company_names:
                used_company_names.add(candidate)
                break
        else:
            raise RuntimeError(
                "Failed to generate unique company name after 1000 attempts"
            )
        client.name = candidate
        client.primary_contact_name = fake.name()
        client.primary_contact_email = fake.email()
        client.email = fake.email()
        client.phone = fake.phone_number()

        rj = client.raw_json or {}
        if "_name" in rj:
            rj["_name"] = candidate
        if "_email_address" in rj:
            rj["_email_address"] = fake.email()
        if "_bank_account_details" in rj:
            rj["_bank_account_details"] = fake.iban()
        if "_phones" in rj and isinstance(rj["_phones"], list):
            for p in rj["_phones"]:
                if isinstance(p, dict) and "_phone_number" in p:
                    p["_phone_number"] = fake.phone_number()
        bp = rj.get("_batch_payments")
        if isinstance(bp, dict):
            if "_bank_account_number" in bp:
                bp["_bank_account_number"] = fake.iban()
            if "_bank_account_name" in bp:
                bp["_bank_account_name"] = fake.name()
        client.raw_json = rj
        client.save(using=SCRUB_ALIAS)

    for contact in ClientContact.objects.using(SCRUB_ALIAS).all():
        contact.name = fake.name()
        contact.email = fake.email()
        contact.phone = fake.phone_number()
        contact.save(
            using=SCRUB_ALIAS,
            update_fields=["name", "email", "phone"],
        )


def _scrub_accounting_contacts() -> None:
    """Mirror legacy PII_CONFIG entries for invoice/bill/creditnote.

    Only `raw_json._contact._name` and `raw_json._contact._email_address`
    are touched — every other path in raw_json (and every other field on
    the model) is left untouched.
    """
    fake = Faker()
    for model in (Invoice, Bill, CreditNote):
        for row in model.objects.using(SCRUB_ALIAS).all():
            rj = row.raw_json or {}
            contact = rj.get("_contact")
            if not isinstance(contact, dict):
                continue
            changed = False
            if "_name" in contact:
                contact["_name"] = fake.company()
                changed = True
            if "_email_address" in contact:
                contact["_email_address"] = fake.email()
                changed = True
            if changed:
                row.raw_json = rj
                row.save(using=SCRUB_ALIAS, update_fields=["raw_json"])


def _delete_unlinked_accounting() -> None:
    """Mirror legacy _filter_unlinked_accounting_records exactly.

    - All Bill / BillLineItem / CreditNote / CreditNoteLineItem rows: dropped.
    - Invoice without job FK: dropped (FK cascade removes its line items).
    - Quote without job FK: dropped.
    """
    BillLineItem.objects.using(SCRUB_ALIAS).all().delete()
    Bill.objects.using(SCRUB_ALIAS).all().delete()
    CreditNoteLineItem.objects.using(SCRUB_ALIAS).all().delete()
    CreditNote.objects.using(SCRUB_ALIAS).all().delete()

    Invoice.objects.using(SCRUB_ALIAS).filter(job__isnull=True).delete()
    Quote.objects.using(SCRUB_ALIAS).filter(job__isnull=True).delete()


def scrub() -> None:
    """Reproduce the legacy command's PII handling on the scrub DB.

    Single transaction. Persists and re-raises on any error.
    """
    _assert_scrub_alias_is_safe()
    try:
        with transaction.atomic(using=SCRUB_ALIAS):
            # Per-step helpers added by subsequent tasks.
            _scrub_staff()
            _scrub_clients()
            _scrub_accounting_contacts()
            _delete_unlinked_accounting()
    except Exception as exc:
        persist_app_error(exc)
        raise
