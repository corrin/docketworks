"""
Scrubs a restored copy of prod (in the `scrub` DB alias) of all PII.

Reproduces three behaviours from the legacy backport_data_backup command:
  1. Anonymise the columns in PII_CONFIG (+ _anonymize_staff).
  2. Delete the unlinked accounting records that _filter_unlinked_accounting_records dropped.
  3. Truncate the tables in EXCLUDE_MODELS (minus framework tables).

It additionally excludes DB-backed external-system credentials introduced
after the legacy command. A scrubbed backup must never carry configuration that
could authenticate against production services.

Safety: refuses to run unless settings.DATABASES["scrub"]["NAME"] ends in
"_scrub" — last line of defence against a misconfigured SCRUB_DB_NAME pointing
at prod.
"""

from collections.abc import Callable

from django.conf import settings
from django.db import connections, transaction
from faker import Faker

from apps.accounting.models import (
    Bill,
    BillLineItem,
    CreditNote,
    CreditNoteLineItem,
    Invoice,
    Quote,
)
from apps.accounts.models import SYSTEM_AUTOMATION_EMAIL, Staff
from apps.accounts.staff_anonymization import create_staff_profile
from apps.company.models import Company, ContactMethod, Person
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

    The System Automation row (seeded by accounts.0015) is preserved as-is —
    it's a system identity, not PII, and downstream consumers (audit-trail
    saves, Xero sync of background-job-created invoices) look it up by
    canonical email.
    """
    used_emails: set[str] = set()
    for staff in Staff.objects.using(SCRUB_ALIAS).exclude(
        email=SYSTEM_AUTOMATION_EMAIL
    ):
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


def _preserved_company_names() -> set[str]:
    """Names that must survive scrubbing: shop, test company, scraper suppliers.

    Mirrors legacy backport_data_backup._get_preserved_company_names() exactly.
    """
    preserved: set[str] = set()
    cd = CompanyDefaults.objects.using(SCRUB_ALIAS).get()
    preserved.add(cd.shop_company.name)
    preserved.add(cd.test_company_name)

    from apps.quoting.models import SupplierScraperConfig

    supplier_names = (
        SupplierScraperConfig.objects.using(SCRUB_ALIAS)
        .filter(is_enabled=True)
        .values_list("supplier__name", flat=True)
    )
    preserved.update(supplier_names)
    return preserved


def _unique_scrub_value(
    generate: Callable[[], str],
    method_type: str,
    used: set[tuple[str, str]],
) -> tuple[str, str]:
    """Return a (value, normalized) whose normalized form is globally unique.

    ``used`` accumulates every ``(method_type, normalized)`` produced so far, so
    no two scrubbed contact methods can share a normalized value. That keeps the
    scrub clear of the per-owner unique constraints even against a real,
    not-yet-scrubbed number still in the table, without relying on the
    one-number-one-company guard in ``ContactMethod.save()`` (which
    ``bulk_update`` deliberately bypasses).
    """
    for _ in range(1000):
        value = generate()
        normalized = ContactMethod.normalize_value(method_type, value)
        key = (method_type, normalized)
        if normalized and key not in used:
            used.add(key)
            return value, normalized
    raise RuntimeError(
        "Failed to generate unique contact method value after 1000 attempts"
    )


def _scrub_companies() -> None:
    """Mirror legacy PII_CONFIG entries for companies and people.

    Top-level fields touched: company name/email and person name/email.
    raw_json paths touched: _name, _email_address, _bank_account_details,
    _phones[]._phone_number, _batch_payments._bank_account_number,
    _batch_payments._bank_account_name.
    """
    fake = Faker()
    preserved = _preserved_company_names()
    used_company_names: set[str] = set()

    for company in Company.objects.using(SCRUB_ALIAS).exclude(name__in=preserved):
        for _ in range(1000):
            candidate = fake.company()
            if candidate not in used_company_names:
                used_company_names.add(candidate)
                break
        else:
            raise RuntimeError(
                "Failed to generate unique company name after 1000 attempts"
            )
        company.name = candidate
        company.email = fake.email()

        rj = company.raw_json or {}
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
        company.raw_json = rj
        company.save(using=SCRUB_ALIAS)

    for person in Person.objects.using(SCRUB_ALIAS).all():
        person.name = fake.name()
        person.email = fake.email()
        person.save(
            using=SCRUB_ALIAS,
            update_fields=["name", "email"],
        )

    # Preserved companies (shop, test, enabled scrapers) keep their real contact
    # methods, matching the name/email exclusion above. A method is preserved
    # whether it is owned directly by the company or by a linked person.
    used_method_values: set[tuple[str, str]] = set()
    methods_to_update: list[ContactMethod] = []
    for method in (
        ContactMethod.objects.using(SCRUB_ALIAS)
        .exclude(company__name__in=preserved)
        .exclude(person__company_links__company__name__in=preserved)
    ):
        if method.method_type == ContactMethod.MethodType.PHONE:
            generate = fake.phone_number
        elif method.method_type == ContactMethod.MethodType.EMAIL:
            generate = fake.email
        else:
            continue
        value, normalized = _unique_scrub_value(
            generate, method.method_type, used_method_values
        )
        method.value = value
        method.normalized_value = normalized
        methods_to_update.append(method)
    # bulk_update bypasses ContactMethod.save(), so the one-number-one-company
    # guard and primary-demotion logic (neither of which is a business operation
    # during a scrub) never run and cannot abort the transaction on a collision.
    ContactMethod.objects.using(SCRUB_ALIAS).bulk_update(
        methods_to_update, ["value", "normalized_value"], batch_size=500
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


# Mirrors legacy EXCLUDE_MODELS, MINUS framework tables (contenttypes/auth/
# sessions/sites). Framework tables stay because pg_dump-restored FKs from
# accounts_staff_user_permissions etc. depend on them and TRUNCATE CASCADE
# would wipe those user-permission rows.
# NB: workflow_xeropayitem is deliberately NOT in this list, even though the
# legacy flow excludes it from dumpdata. TRUNCATE ... CASCADE in Postgres
# bypasses Django's on_delete=PROTECT and follows FKs blindly — wiping
# xeropayitem would cascade through Job.default_xero_pay_item and
# CostLine.xero_pay_item and erase every Job and CostLine in the dump.
# Pay item names aren't PII; letting prod's set through is harmless.
_PRIVATE_CONFIG_TABLES = (
    "workflow_aiprovider",
    "workflow_xeroapp",
    "workflow_serviceapikey",
    "crm_phoneprovidersettings",
    "quoting_suppliercredential",
)

_EXCLUDED_TABLES = (
    # In joined-table inheritance, child tables have FKs back to parent.
    # TRUNCATE parent WITH CASCADE will cascade to children. Do NOT include
    # child tables — workflow_xeroerror will be cascaded from workflow_apperror.
    "workflow_apperror",  # Parent; CASCADE will delete xeroerror children
    *_PRIVATE_CONFIG_TABLES,
    "accounts_historicalstaff",
    "process_historicalform",
    "process_historicalformentry",
    "process_historicalprocedure",
)


def _truncate_excluded_tables() -> None:
    """Mirror legacy EXCLUDE_MODELS by emptying these tables in the scrub DB."""
    with connections[SCRUB_ALIAS].cursor() as cur:
        for table in _EXCLUDED_TABLES:
            cur.execute(f'TRUNCATE TABLE "{table}" RESTART IDENTITY CASCADE')


def _assert_private_config_removed() -> None:
    """Fail closed if a scrubbed DB still contains external credentials."""
    remaining: list[str] = []
    with connections[SCRUB_ALIAS].cursor() as cur:
        for table in _PRIVATE_CONFIG_TABLES:
            cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            count = cur.fetchone()[0]
            if count:
                remaining.append(f"{table}={count}")
    if remaining:
        raise RuntimeError(
            "Private configuration remained after scrubbing: " + ", ".join(remaining)
        )


def scrub() -> None:
    """Reproduce the legacy command's PII handling on the scrub DB.

    Single transaction. Persists and re-raises on any error.
    """
    _assert_scrub_alias_is_safe()
    try:
        with transaction.atomic(using=SCRUB_ALIAS):
            # Per-step helpers added by subsequent tasks.
            _scrub_staff()
            _scrub_companies()
            _scrub_accounting_contacts()
            _delete_unlinked_accounting()
            _truncate_excluded_tables()
            _assert_private_config_removed()
    except Exception as exc:
        persist_app_error(exc)
        raise
