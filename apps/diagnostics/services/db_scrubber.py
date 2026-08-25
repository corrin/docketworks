"""Scrub a restored copy of prod (the ``scrub`` DB alias) of all PII.

Ported from v1's ``apps/workflow/services/db_scrubber.py`` with v2 model
homes; the physical tables are unchanged (workflow_* db_table pins). Six
behaviours, in order:

  1. Anonymise the PII columns: staff identities, pay-slip employee names
     (the preserved ``xero_user_id`` join would otherwise reverse the staff
     anonymisation), company/person names, emails and street addresses,
     person-link notes, contact methods (values and labels), and the Xero
     ``raw_json`` PII paths.
  2. Delete accounting records not linked to a job.
  3. Anonymise the surviving accounting documents' contact blocks.
  4. Redact process-domain entry data and its audit-trail delta snapshots.
  5. Truncate the excluded tables.
  6. Prove every database-backed external-system credential table is empty.

Deliberate, not omissions: ``xero_user_id`` is left alone (it is the marker
the seed's employees phase re-reads, and it names a Xero employee record
rather than a person), and ``CompanyDefaults.test_company_name`` plus the
shop and enabled-scraper supplier companies keep their real names.

Fable: process_form and process_procedure metadata (title, tags, document
number, ``form_schema``'s field structure, Google Doc ids/urls) carry no PII
of their own, and identify staff only through FKs already anonymised at the
Staff table — matching job's own audit trail (JobEvent) — so that metadata
needs no excluded-table entry. ``Procedure.site_location`` is the one
exception in that pair: a free-text site field can hold a residential
address, so it is scrubbed like ``Company.address`` (see
``_scrub_companies``). ``FormEntry.data`` is schema-driven user content, not
metadata — an incident form's text/textarea fields are exactly where a named
person's injury or witness details live — so it is redacted field-by-field
against its form's schema (see ``_scrub_process_entries``), never exempted.
``ProcessEvent``'s own columns (``event_type``, ``staff``, ``timestamp``) are
metadata like ``JobEvent``'s, but its ``delta_before``/``delta_after`` and
``detail.changes`` are snapshots of that same entry data, so they are
redacted alongside it (see ``_scrub_process_events``).

v1 also left staff PASSWORDS alone, on the reasoning that the restore runbook
resets them. v2 does not: the reset happens after the archive has already
travelled, so the file itself carried production hashes. They are replaced
here, at the one transition.

Safety: refuses to run unless ``settings.DATABASES["scrub"]["NAME"]`` ends in
``_scrub`` — last line of defence against a misconfigured SCRUB_DB_NAME
pointing at prod.

This scrub is the ONE confidential-to-non-confidential transition (ADR 0039,
responsibilities are exclusive): everything downstream treats its output as
clean by construction. A
downstream step that re-scrubs or adds secrecy ceremony signals a defect
HERE, and the fix belongs here — which is why completeness (KAN-340/341) is
this module's whole burden.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import date

from django.apps import apps as django_apps
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import connections, transaction
from faker import Faker
from ninja.errors import HttpError

from apps.accounting.models import (
    Bill,
    BillLineItem,
    CreditNote,
    CreditNoteLineItem,
    Invoice,
    Quote,
)
from apps.accounts.models import SYSTEM_AUTOMATION_EMAIL, Staff
from apps.accounts.nonprod_credentials import STAFF_PASSWORD
from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.core.errors import AppErrorContext, persist_app_error
from apps.core.models import CompanyDefaults
from apps.diagnostics.services.staff_anonymization import create_staff_profile
from apps.process.models import FormEntry, Procedure, ProcessEvent
from apps.process.schemas import FormFieldSchema
from apps.process.services.entry_validation import parse_schema
from apps.quoting.models import SupplierScraperConfig

logger = logging.getLogger("apps.diagnostics.services.db_scrubber")

SCRUB_ALIAS = "scrub"
_GENERATE_ATTEMPTS = 100

# Fable: form/entry free text and event deltas get one fixed placeholder, not
# Faker output — unlike a company name or an email, nothing downstream needs
# this text to look plausible, and one literal makes "scrubbed" trivially
# greppable in a restored dump.
_TEXT_SCRUB_TOKEN = "[SCRUBBED]"  # noqa: S105 -- a redaction placeholder, not a credential
_FREE_TEXT_FIELD_TYPES = ("text", "textarea")


def _assert_scrub_alias_is_safe() -> None:
    # Only absence is checked: config/settings.py refuses to define the alias
    # unless its name ends in _scrub, so an existing alias is proof (ADR
    # 0039, exclusivity — settings owns that invariant, this module trusts it).
    if SCRUB_ALIAS not in settings.DATABASES:
        raise RuntimeError(
            "No 'scrub' database alias is configured. Set SCRUB_DB_NAME "
            "(a sibling database whose name ends in '_scrub') in the "
            "environment before running the scrubber."
        )


def _validated_raw_json(raw_json: object, owner: str) -> dict[str, object] | None:
    """Return raw_json as a dict, None when absent, and refuse anything else.

    A malformed value must stop the run rather than be coerced to ``{}``:
    coercion would let a row's PII paths survive the scrub unvisited.
    """
    if raw_json is None:
        return None
    if not isinstance(raw_json, dict):
        raise TypeError(f"{owner}: raw_json is {type(raw_json).__name__}, expected object/null")
    return raw_json


def _scrub_staff() -> None:
    """Anonymise staff identities and replace every password.

    Touches first_name, last_name, preferred_name, email and password.
    ``xero_user_id`` alone is preserved — it is the marker the seed's
    employees phase re-reads, and it identifies a Xero employee record, not a
    person, once the name and email beside it are fake.

    Passwords are REPLACED, not left: v1 left the real hashes and relied on
    the restore runbook resetting them afterwards, which does nothing for the
    archive itself — the file travels to workstations with production hashes
    in it, and ``flag_weak_passwords`` exists because those passwords were
    once believed weak. Every row gets the public nonprod staff password, so a
    restored database is directly usable; hashed once and shared because the
    value is public by design and per-row hashing costs a second per hundred
    staff for no benefit.

    The System Automation row keeps its identity — it is a system account,
    not PII, and consumers (audit-trail saves, Xero sync of
    background-job-created invoices) look it up by canonical email — but its
    password is made unusable: nothing ever logs in as it.
    """
    scrubbed_password = make_password(STAFF_PASSWORD)

    automation = (
        Staff.objects.using(SCRUB_ALIAS).filter(office_email=SYSTEM_AUTOMATION_EMAIL).first()
    )
    if automation is not None:
        automation.set_unusable_password()
        automation.save(using=SCRUB_ALIAS, update_fields=["password"])

    used_emails: set[str] = set()
    for staff in Staff.objects.using(SCRUB_ALIAS).exclude(office_email=SYSTEM_AUTOMATION_EMAIL):
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
        staff.office_email = profile["email"]
        staff.first_name = profile["first_name"]
        staff.last_name = profile["last_name"]
        staff.preferred_name = profile["preferred_name"]
        staff.password = scrubbed_password
        staff.password_needs_reset = True
        staff.save(
            using=SCRUB_ALIAS,
            update_fields=[
                "office_email",
                "first_name",
                "last_name",
                "preferred_name",
                "password",
                "password_needs_reset",
            ],
        )


def _scrub_payslips() -> None:
    """Re-name pay slips to match the scrubbed staff identities.

    ``Staff.xero_user_id`` is deliberately preserved (the seed's employees
    phase re-reads it), so ``XeroPaySlip.xero_employee_id`` joins a slip back
    to its Staff row — a real ``employee_name`` here would reverse the staff
    anonymisation and attach real names to real pay. Where the join resolves,
    the slip takes the scrubbed Staff name so the repair commands' display
    output stays coherent; a slip with no Staff row (departed employee) gets
    a generated name. ``raw_json`` is scrubbed surgically (``_first_name`` /
    ``_last_name``) rather than blanked, because the timesheet repair
    commands read its earnings lines. Pay amounts stay: figures attached to
    an anonymised identity are what a restore is for, matching the recorded
    stance on staff wage fields.
    """
    fake = Faker()
    # Registry lookup: xero is a sibling integration app (layer contract).
    xero_pay_slip = django_apps.get_model("xero", "XeroPaySlip")
    staff_names: dict[str, tuple[str, str]] = {
        str(uuid.UUID(staff.xero_user_id)): (staff.first_name, staff.last_name)
        for staff in Staff.objects.using(SCRUB_ALIAS).filter(xero_user_id__isnull=False)
    }
    for slip in xero_pay_slip._default_manager.using(SCRUB_ALIAS).all():
        key = str(slip.xero_employee_id)
        if key in staff_names:
            first, last = staff_names[key]
        else:
            first, last = fake.first_name(), fake.last_name()
        if slip.employee_name is not None:
            slip.employee_name = f"{first} {last}".strip()
        rj = _validated_raw_json(slip.raw_json, f"XeroPaySlip {slip.pk}")
        if rj is not None:
            if "_first_name" in rj:
                rj["_first_name"] = first
            if "_last_name" in rj:
                rj["_last_name"] = last
            slip.raw_json = rj
        slip.save(using=SCRUB_ALIAS, update_fields=["employee_name", "raw_json"])


def _preserved_company_names() -> set[str]:
    """Names that must survive scrubbing: shop, test company, scraper suppliers."""
    preserved: set[str] = set()
    cd = CompanyDefaults.objects.using(SCRUB_ALIAS).get()
    preserved.add(cd.shop_company.name)
    # Nullable by contract: NULL means no test company is configured, so
    # there is nothing to preserve — not a data defect to raise on.
    if cd.test_company_name is not None:
        preserved.add(cd.test_company_name)

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
    raise RuntimeError("Failed to generate unique contact method value after 1000 attempts")


def _scrub_bank_and_phone_paths(rj: dict[str, object], fake: Faker) -> None:
    """Rewrite the nested phone and bank-account PII paths in raw_json."""
    phones = rj.get("_phones")
    if isinstance(phones, list):
        for p in phones:
            if isinstance(p, dict) and "_phone_number" in p:
                p["_phone_number"] = fake.phone_number()
    bp = rj.get("_batch_payments")
    if isinstance(bp, dict):
        if "_bank_account_number" in bp:
            bp["_bank_account_number"] = fake.iban()
        if "_bank_account_name" in bp:
            bp["_bank_account_name"] = fake.name()


def _scrub_address_paths(rj: dict[str, object], fake: Faker) -> None:
    """Rewrite the nested street-address PII paths in raw_json.

    Street lines and the attention-to name identify a customer; city, region
    and postal code are left as coarse, non-identifying shape.
    """
    addresses = rj.get("_addresses")
    if not isinstance(addresses, list):
        return
    for entry in addresses:
        if not isinstance(entry, dict):
            continue
        for line_key in ("_address_line1", "_address_line2", "_address_line3", "_address_line4"):
            if entry.get(line_key):
                entry[line_key] = fake.street_address()
        if entry.get("_attention_to"):
            entry["_attention_to"] = fake.name()


def _scrub_company_raw_json(company: Company, fake: Faker, candidate: str) -> None:
    """Rewrite the PII paths inside a company's Xero raw_json snapshot.

    Paths touched: _name, _email_address, _bank_account_details,
    _phones[]._phone_number, _batch_payments._bank_account_number,
    _batch_payments._bank_account_name, _addresses[]._address_line1-4,
    _addresses[]._attention_to — every other path is left untouched.
    """
    rj = _validated_raw_json(company.raw_json, f"Company {company.pk}")
    if rj is None:
        return
    if "_name" in rj:
        rj["_name"] = candidate
    if "_email_address" in rj:
        rj["_email_address"] = fake.email()
    if "_bank_account_details" in rj:
        rj["_bank_account_details"] = fake.iban()
    _scrub_bank_and_phone_paths(rj, fake)
    _scrub_address_paths(rj, fake)
    company.raw_json = rj


def _scrub_companies() -> None:
    """Anonymise company/person names, emails, addresses, notes and contact methods."""
    fake = Faker()
    preserved = _preserved_company_names()
    # Seeded with the preserved names: a generated name colliding with the
    # shop/test/scraper-supplier names would rename a company INTO the
    # preserved set, and the notes/contact-method scrubs below would then
    # skip its real data via their company__name__in=preserved exclusions.
    used_company_names: set[str] = set(preserved)

    for company in Company.objects.using(SCRUB_ALIAS).exclude(name__in=preserved):
        for _ in range(1000):
            candidate = fake.company()
            if candidate not in used_company_names:
                used_company_names.add(candidate)
                break
        else:
            raise RuntimeError("Failed to generate unique company name after 1000 attempts")
        company.name = candidate
        company.email = fake.email()
        if company.address:
            company.address = fake.address()
        _scrub_company_raw_json(company, fake, candidate)
        company.save(using=SCRUB_ALIAS)

    for person in Person.objects.using(SCRUB_ALIAS).all():
        person.name = fake.name()
        person.email = fake.email()
        person.save(
            using=SCRUB_ALIAS,
            update_fields=["name", "email"],
        )

    _scrub_person_link_notes(fake, preserved)
    _scrub_contact_methods(fake, preserved)


def _scrub_person_link_notes(fake: Faker, preserved: set[str]) -> None:
    """Anonymise CompanyPersonLink.notes.

    Link notes are free text about a named person ("mates with the owner,
    call after 3pm") — scrubbed like a value, not preserved like a category.
    Preserved companies keep theirs, matching every other exclusion here.
    """
    links_to_update = []
    for link in (
        CompanyPersonLink.objects.using(SCRUB_ALIAS)
        .exclude(notes=None)
        .exclude(notes="")
        .exclude(company__name__in=preserved)
    ):
        link.notes = fake.sentence()
        links_to_update.append(link)
    CompanyPersonLink.objects.using(SCRUB_ALIAS).bulk_update(
        links_to_update, ["notes"], batch_size=500
    )


def _scrub_contact_methods(fake: Faker, preserved: set[str]) -> None:
    """Anonymise ContactMethod values and labels.

    Preserved companies (shop, test, enabled scrapers) keep their real contact
    methods, matching the name/email exclusion in ``_scrub_companies``. A
    method is preserved whether it is owned directly by the company or by a
    linked person.
    """
    used_method_values: set[tuple[str, str]] = set()
    methods_to_update: list[ContactMethod] = []
    for method in (
        ContactMethod.objects.using(SCRUB_ALIAS)
        .exclude(company__name__in=preserved)
        .exclude(person__company_links__company__name__in=preserved)
    ):
        changed = False
        if method.label:
            # A label is free text ("John's mobile"), not a category — it can
            # carry a person's name, so it is scrubbed like the value.
            method.label = fake.word()
            changed = True
        if method.method_type == ContactMethod.MethodType.PHONE:
            generate: Callable[[], str] | None = fake.phone_number
        elif method.method_type == ContactMethod.MethodType.EMAIL:
            generate = fake.email
        else:
            generate = None
        if generate is not None:
            value, normalized = _unique_scrub_value(
                generate, method.method_type, used_method_values
            )
            method.value = value
            method.normalized_value = normalized
            changed = True
        if changed:
            methods_to_update.append(method)
    # bulk_update bypasses ContactMethod.save(), so the one-number-one-company
    # guard and primary-demotion logic (neither of which is a business operation
    # during a scrub) never run and cannot abort the transaction on a collision.
    ContactMethod.objects.using(SCRUB_ALIAS).bulk_update(
        methods_to_update, ["value", "normalized_value", "label"], batch_size=500
    )


def _scrub_procedures() -> None:
    """Anonymise Procedure.site_location; every other field is metadata (see module docstring).

    Mirrors ``Company.address`` in ``_scrub_companies``: a free-text site
    field can hold a residential address as easily as a work-site name.
    """
    fake = Faker()
    procedures_to_update = []
    for procedure in Procedure.objects.using(SCRUB_ALIAS).exclude(site_location=None):
        procedure.site_location = fake.address()
        procedures_to_update.append(procedure)
    Procedure.objects.using(SCRUB_ALIAS).bulk_update(
        procedures_to_update, ["site_location"], batch_size=500
    )


def _select_conforms(field: FormFieldSchema, value: object) -> bool:
    return value in (field.options or [])


def _number_conforms(_field: FormFieldSchema, value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _boolean_conforms(_field: FormFieldSchema, value: object) -> bool:
    return isinstance(value, bool)


def _date_conforms(_field: FormFieldSchema, value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    # deliberate-swallow: a non-ISO string fails the conformance check, which
    # is the answer this predicate reports either way.
    except ValueError:
        return False
    return True


def _uuid_conforms(_field: FormFieldSchema, value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
    # deliberate-swallow: a non-UUID string fails the conformance check, which
    # is the answer this predicate reports either way.
    except ValueError:
        return False
    return True


# staff/entry_ref share one checker: both are id strings, and confirming the
# referenced row still exists is deliberately NOT part of this check (see
# _field_value_conforms's docstring).
_CONFORMANCE_CHECKERS: dict[str, Callable[[FormFieldSchema, object], bool]] = {
    "select": _select_conforms,
    "number": _number_conforms,
    "boolean": _boolean_conforms,
    "date": _date_conforms,
    "staff": _uuid_conforms,
    "entry_ref": _uuid_conforms,
}


def _field_value_conforms(field: FormFieldSchema, value: object) -> bool:
    """Report whether ``value`` structurally matches ``field.type`` — no DB lookups.

    Not ``apps.process.services.entry_validation``'s ``_check_staff``/
    ``_check_entry_ref``: those also confirm the referenced row still
    exists, which needs a query against ``SCRUB_ALIAS`` this module has no
    reason to thread through the validation layer for, and existence is not
    the question a scrub asks — a dangling but well-typed id is still a
    UUID, not the free text this pass exists to catch. v1 accepted arbitrary
    JSON into ``FormEntry.data``, so a restored row's value under a
    structurally-typed key (e.g. ``severity`` typed ``select`` today) can
    hold free text written before the form ever had that type — this is the
    gate that catches it.
    """
    checker = _CONFORMANCE_CHECKERS.get(field.type)
    if checker is None:  # pragma: no cover - caller excludes text/textarea; FieldType is closed
        raise AssertionError(f"Unhandled field type {field.type}")
    return checker(field, value)


def _scrub_process_entries() -> None:
    """Redact free-text form-entry content; only conforming structural values survive.

    A text/textarea field is exactly where an incident form carries a named
    person's injury or witness details, so its value is replaced
    unconditionally. Date, boolean, number and select values are closed
    shapes with no room for a name and staff/entry_ref values are ids — but
    v1 accepted arbitrary JSON into this field, so a restored row can hold
    free text under a key whose CURRENT schema types it as one of those five:
    a value survives only when it both names a field of the current schema
    AND structurally conforms to that field's type (``_field_value_conforms``).
    A key with no current field, or a value that fails its field's type check
    — free text written under a schema version that has since dropped,
    retyped it, or never validated it at all — is exactly the unaudited
    content this scrub exists to remove, so it is redacted too, never kept
    and never dropped: the key survives with the placeholder so the row's
    shape stays inspectable. An entry whose form schema no longer parses is
    not skipped either: its whole ``data`` is replaced and the count is
    logged, because a corrupt schema is exactly the case a silent skip would
    hide.
    """
    unparseable = 0
    for entry in FormEntry.objects.using(SCRUB_ALIAS).select_related("form"):
        try:
            spec = parse_schema(entry.form)
        # deliberate-swallow: an unparseable stored schema means the entry's
        # free-text keys cannot be identified, so the whole data payload is
        # wiped (the safe direction) and the count is logged after the loop.
        except HttpError:
            unparseable += 1
            entry.data = {}
            entry.save(using=SCRUB_ALIAS, update_fields=["data"])
            continue
        structured_fields = {
            field.key: field for field in spec.fields if field.type not in _FREE_TEXT_FIELD_TYPES
        }
        redacted = {
            key: (
                value
                if key in structured_fields and _field_value_conforms(structured_fields[key], value)
                else _TEXT_SCRUB_TOKEN
            )
            for key, value in entry.data.items()
        }
        if redacted != entry.data:
            entry.data = redacted
            entry.save(using=SCRUB_ALIAS, update_fields=["data"])
    if unparseable:
        logger.warning(
            "Scrub wiped data on %d form entries whose form schema would not parse.",
            unparseable,
        )


def _redact_detail_changes(detail: dict[str, object]) -> dict[str, object] | None:
    """Return ``detail`` with every changes[].old_value/new_value redacted, or None if unchanged.

    field_name is left alone — it names the schema field, not its content.
    A ``detail`` with no ``changes`` key at all (e.g. a form_created event
    written with no field changes) is a normal shape, not malformed, and is
    left alone. Fable: scrub-by-default — a ``changes`` that IS present but
    malformed (not a list, or a list holding a non-dict entry) is replaced
    with an empty changes list rather than passed through unredacted: detail
    is free-form JSON, not a validated contract, so audit fidelity in a
    scrubbed dump is expendable, but a redaction gap that ships real content
    through an unparseable shape is not.
    """
    if "changes" not in detail:
        return None
    changes = detail["changes"]
    if not isinstance(changes, list) or any(not isinstance(change, dict) for change in changes):
        return {"changes": []}
    redacted_changes = []
    changed = False
    for change in changes:
        redacted_change = dict(change)
        for key in ("old_value", "new_value"):
            if key in redacted_change:
                redacted_change[key] = _TEXT_SCRUB_TOKEN
                changed = True
        redacted_changes.append(redacted_change)
    if not changed:
        return None
    return {**detail, "changes": redacted_changes}


def _scrub_process_events() -> None:
    """Null the delta snapshots and redact changed values; field names stay.

    ``delta_before``/``delta_after`` and ``detail.changes[].old_value``/
    ``new_value`` are snapshots of ``FormEntry.data`` taken at edit time — the
    same free text ``_scrub_process_entries`` just redacted on the live row
    would otherwise survive unredacted in the audit trail. Scrubbed
    environments lose exact audit display fidelity (old/new values read as
    the placeholder); that is an acceptable loss, the same trade
    ``_scrub_process_entries`` makes on the live data.
    """
    events_to_update: list[ProcessEvent] = []
    for event in ProcessEvent.objects.using(SCRUB_ALIAS).all():
        changed = False
        if event.delta_before is not None:
            event.delta_before = None
            changed = True
        if event.delta_after is not None:
            event.delta_after = None
            changed = True
        redacted_detail = _redact_detail_changes(event.detail or {})
        if redacted_detail is not None:
            event.detail = redacted_detail
            changed = True
        if changed:
            events_to_update.append(event)
    ProcessEvent.objects.using(SCRUB_ALIAS).bulk_update(
        events_to_update, ["delta_before", "delta_after", "detail"], batch_size=500
    )


# Every accounting model whose raw_json can carry a Xero contact block. Quote
# is here even though v1's scrubber omitted it: job-linked quotes survive the
# unlinked-delete with their contact block intact, so leaving them out ships
# real customer names in a "scrubbed" dump (v1 shared the defect; parity does
# not excuse it). Pinned by the scrubber tests against the accounting app's
# raw_json-bearing models so a new document model cannot silently join the
# leak.
_CONTACT_SCRUB_MODELS = (Invoice, Bill, CreditNote, Quote)


def _scrub_accounting_contacts() -> None:
    """Anonymise the contact block in accounting-document raw_json.

    Only ``raw_json._contact._name`` and ``raw_json._contact._email_address``
    are touched — every other path in raw_json (and every other field on
    the model) is left untouched.
    """
    fake = Faker()
    # Unrolled rather than looped over _CONTACT_SCRUB_MODELS: the constrained
    # TypeVar resolves per call, which is what keeps bulk_update fully typed —
    # a loop variable would be the union and defeat it. When adding a model
    # to the tuple, add its call here; the coverage pin test guards the tuple.
    _scrub_contact_blocks(Invoice, fake)
    _scrub_contact_blocks(Bill, fake)
    _scrub_contact_blocks(CreditNote, fake)
    _scrub_contact_blocks(Quote, fake)


def _scrub_contact_blocks[M: (Invoice, Bill, CreditNote, Quote)](
    model: type[M], fake: Faker
) -> None:
    changed_rows: list[M] = []
    for row in model.objects.using(SCRUB_ALIAS).all():
        rj = _validated_raw_json(row.raw_json, f"{model.__name__} {row.pk}")
        if rj is None:
            continue
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
            changed_rows.append(row)
    # bulk_update is safe here: raw_json is a plain JSONField and none of
    # these models override save() with behaviour a scrub should run.
    model.objects.using(SCRUB_ALIAS).bulk_update(changed_rows, ["raw_json"], batch_size=500)


def _delete_unlinked_accounting() -> None:
    """Drop accounting records that have no job link.

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


# The contract with scripts/ops/verify_scrubbed_backup.py: a scrubbed backup
# must never carry configuration that could authenticate against production
# services, and the verifier fails an archive where any of these tables holds
# a row. Table names, not model imports, because TRUNCATE addresses the
# physical table and the verifier speaks the same names.
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
    # NB: workflow_xeropayitem is deliberately NOT in this list. TRUNCATE ...
    # CASCADE in Postgres bypasses Django's on_delete=PROTECT and follows FKs
    # blindly — wiping xeropayitem would cascade through
    # Job.default_xero_pay_item and CostLine.xero_pay_item and erase every Job
    # and CostLine in the dump. Pay item names aren't PII; letting prod's set
    # through is harmless.
    "accounts_historicalstaff",
)


def _truncate_excluded_tables() -> None:
    """Empty the excluded tables in the scrub DB."""
    with connections[SCRUB_ALIAS].cursor() as cur:
        for table in _EXCLUDED_TABLES:
            # f-string rather than a bound parameter: identifiers cannot be
            # parameterised, and every name comes from the module constant.
            cur.execute(f'TRUNCATE TABLE "{table}" RESTART IDENTITY CASCADE')


def _assert_private_config_removed() -> None:
    """Fail closed if a scrubbed DB still contains external credentials."""
    remaining: list[str] = []
    with connections[SCRUB_ALIAS].cursor() as cur:
        for table in _PRIVATE_CONFIG_TABLES:
            cur.execute(f'SELECT COUNT(*) FROM "{table}"')  # noqa: S608 -- module-constant identifier
            row = cur.fetchone()
            if row is None:
                raise RuntimeError(f"COUNT(*) on {table} returned no row")
            count = int(row[0])
            if count:
                remaining.append(f"{table}={count}")
    if remaining:
        raise RuntimeError(
            "Private configuration remained after scrubbing: " + ", ".join(remaining)
        )


def scrub() -> None:
    """Run the full scrub against the scrub DB in a single transaction.

    Persists and re-raises on any error.
    """
    _assert_scrub_alias_is_safe()
    try:
        with transaction.atomic(using=SCRUB_ALIAS):
            _scrub_staff()
            _scrub_payslips()
            _scrub_companies()
            # Delete first, then anonymise what survives: the unlinked-delete
            # owns WHAT survives, the contact scrub owns anonymising it —
            # scrubbing rows the very next statement drops re-decided the
            # first question for nothing (every Bill/CreditNote, plus every
            # job-less Invoice/Quote, was faked and saved, then deleted).
            _delete_unlinked_accounting()
            _scrub_accounting_contacts()
            _scrub_procedures()
            # Independent of each other (each touches its own table and reads
            # nothing the other writes); ordered entries-then-events only to
            # read in the same order as the module docstring's list.
            _scrub_process_entries()
            _scrub_process_events()
            _truncate_excluded_tables()
            _assert_private_config_removed()
    except Exception as exc:
        persist_app_error(
            exc,
            AppErrorContext(
                additional_context={"operation": "backport_data_backup scrub"},
            ),
        )
        raise
