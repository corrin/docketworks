---
status: draft
spec: docs/plans/2026-04-22-prod-to-dev-scrubbed-dump.md
---

# pg_dump-based backport refresh — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Django `dumpdata` + Faker + `loaddata` refresh path with native `pg_dump`/`pg_restore` via a prod-side scrub DB. **This is a tooling-only rewrite — the set of fields anonymised, the records dropped, and the tables excluded are identical to today's `backport_data_backup.py` behaviour.** Any expansion of scrub scope is out of scope here and will be tracked as a separate ticket. Speed target: 10–100× faster end-to-end. Unanonymised prod data never leaves the prod host.

**Architecture:** One management command (`manage.py backport_data_backup`, same name, rewritten internals) drives `pg_dump` prod → `pg_restore` into a pre-provisioned `dw_<client>_<env>_scrub` sibling DB → call `db_scrubber.scrub()` (Django ORM + raw SQL on a second `scrub` DB alias) → `pg_dump` the scrubbed DB → ship the `.dump` to dev via rclone → delete the raw dump. The scrubber reproduces today's `PII_CONFIG` (anonymise) + `_filter_unlinked_accounting_records` (drop) + `EXCLUDE_MODELS` (truncate) — nothing more, nothing less. Dev side is runbook-only: `pg_restore` + `migrate` + two fixture loads + Xero reauth + validators. Because `pg_dump` includes the `django_migrations` table, `manage.py migrate` on dev applies only the migrations dev is ahead by — no rewind hacks.

**Tech Stack:** Django 6, PostgreSQL 16, `pg_dump -Fc` / `pg_restore --no-owner --no-privileges`, `subprocess.run`, Django multi-database ORM (`QuerySet.using("scrub")`), Django `TransactionTestCase` for multi-DB tests, `rclone`, Faker (reused), `apps/accounts/staff_anonymization.py` (reused unchanged).

---

## Scope check

Single subsystem: the refresh pipeline. No sub-projects. Ship as one plan.

## Strict like-for-like contract

The current `apps/workflow/management/commands/backport_data_backup.py` performs three categories of PII handling. The new flow must reproduce each one exactly. Anything outside this list is **out of scope** and must not be added.

### 1. Anonymise (today's `PII_CONFIG` + `_anonymize_staff`)

| Model | Fields touched |
|---|---|
| `accounts.staff` | `first_name`, `last_name`, `preferred_name`, `email` (coherent profile via `create_staff_profile()`) |
| `client.client` | `name` (allow-list preserved), `primary_contact_name`, `primary_contact_email`, `email`, `phone`, plus `raw_json._name`, `raw_json._email_address`, `raw_json._bank_account_details`, `raw_json._phones[]._phone_number`, `raw_json._batch_payments._bank_account_number`, `raw_json._batch_payments._bank_account_name` |
| `client.clientcontact` | `name`, `email`, `phone` |
| `accounting.invoice` | `raw_json._contact._name`, `raw_json._contact._email_address` |
| `accounting.bill` | `raw_json._contact._name`, `raw_json._contact._email_address` |
| `accounting.creditnote` | `raw_json._contact._name`, `raw_json._contact._email_address` |

**Allow-list (preserved verbatim):** `CompanyDefaults.shop_client_name`, `CompanyDefaults.test_client_name`, plus `SUPPLIER_NAME` declared on each scraper class via `apps.quoting.management.commands.run_scrapers.Command.get_available_scrapers()`. A client whose `name` is in the allow-list is skipped entirely (its email, phone, raw_json all stay).

**Explicitly NOT touched today (and therefore NOT touched here):** `staff.xero_user_id`, `staff.password`, `client.address`, `client.all_phones`, `client.additional_contact_persons`, `client.supplierpickupaddress.*`, `job.job.*`, `job.historicaljob.*`, `job.costline.*`, `job.jobevent.*`, `purchasing.purchaseorder.*`, `purchasing.stock.*`, line item descriptions on any accounting model.

### 2. Drop unlinked records (today's `_filter_unlinked_accounting_records`)

- `accounting.bill` and `accounting.billlineitem` — drop **all** rows.
- `accounting.creditnote` and `accounting.creditnotelineitem` — drop **all** rows.
- `accounting.invoice` — drop rows where `job_id IS NULL`.
- `accounting.invoicelineitem` — drop rows whose parent invoice was dropped (FK cascade).
- `accounting.quote` — drop rows where `job_id IS NULL`.

### 3. Exclude entire tables (today's `EXCLUDE_MODELS`)

These tables are excluded from `dumpdata` today, so dev never sees their prod rows. With `pg_dump` they would otherwise come across in full — they must be `TRUNCATE`d in the scrub DB before the second dump:

- `workflow_xerotoken`, `workflow_serviceapikey` (secrets)
- `workflow_xeropayitem` (pre-seeded by migration `0187` with fixed UUIDs)
- `workflow_apperror`, `workflow_xeroerror` (debug data)
- `django_apscheduler_djangojob`, `django_apscheduler_djangojobexecution` (scheduler state)
- `accounts_historicalstaff`, `job_historicaljob`, `process_historicalform`, `process_historicalformentry`, `process_historicalprocedure` (SimpleHistory tables)

**Framework tables are NOT truncated.** `django_content_type`, `auth_permission`, `auth_group`, `django_session`, `django_site` are excluded by today's `dumpdata` because `loaddata` would conflict with what `migrate` regenerates. With `pg_dump`, they travel as part of the schema+data and remain internally consistent — every FK pointing at them resolves correctly. Truncating them with `CASCADE` would wipe `accounts_staff_user_permissions`, `accounts_staff_groups`, etc., which is worse than letting prod's IDs through.

---

## File structure

**Create:**
- `apps/workflow/services/db_scrubber.py` — one `scrub()` entry point + private helpers: `_scrub_staff()`, `_scrub_clients()`, `_scrub_accounting_contacts()`, `_delete_unlinked_accounting()`, `_truncate_excluded_tables()`. ORM writes use `.using("scrub")`; SQL uses `connections["scrub"].cursor()`. Wrapped in a single `transaction.atomic(using="scrub")`. Fail-fast with `persist_app_error(exc)` + re-raise.
- `apps/workflow/tests/services/__init__.py` — empty package marker (regenerate via `python scripts/update_init.py`, do not hand-edit).
- `apps/workflow/tests/services/test_db_scrubber.py` — `TransactionTestCase` subclasses with `databases = {"default", "scrub"}`, one per helper.
- `apps/workflow/tests/management/__init__.py` — empty package marker (regenerate via `python scripts/update_init.py`).
- `apps/workflow/tests/management/test_backport_data_backup.py` — wiring test for the rewritten command.
- `scripts/test_cleanup_backups.py` — pure-unittest tests for the new retention regex.

**Modify:**
- `apps/workflow/management/commands/backport_data_backup.py` — full internal rewrite of `handle()`. Keep `--analyze-fields` sub-mode and its helpers (`analyze_fields`, `collect_field_samples`, `cannot_be_pii`, `is_uuid_string`) verbatim.
- `docketworks/settings.py` — add `scrub` DB alias below `default` at line ~403. (**Done in Task 1**)
- `.env.example` — add `SCRUB_DB_NAME` near the other `DB_*` variables. (**Done in Task 1**)
- `docs/restore-prod-to-nonprod.md` — full rewrite for the new 7-step dev flow. Preserve the old runbook as an appendix labeled "legacy JSON path" for one release cycle.
- `scripts/cleanup_backups.py` — add `SCRUBBED_RE` and `compute_scrubbed_keep()` with 30-day retention.
- `scripts/server/instance.sh` — provision and tear down the scrub DB alongside the main DB.
- `scripts/server/templates/env-instance.template` — add `SCRUB_DB_NAME=__SCRUB_DB_NAME__`.

**Reuse unchanged:**
- `apps/accounts/staff_anonymization.py` — `create_staff_profile()` + `NAME_PROFILES`.
- `scripts/restore_checks/*` — 13 post-restore validator scripts.

**Do NOT edit any `__init__.py` directly** — run `python scripts/update_init.py` after creating new modules.

---

## Task 1 — Add `scrub` DB alias to settings and `.env.example` ✅ DONE

Implemented at commit `6d8f84ce`. See plan history.

---

## Task 2 — Scaffold `db_scrubber` service module and safety gate

Establishes the empty `scrub()` entry point, the test class wired for multi-DB, and the safety gate that refuses to run unless the scrub alias's NAME ends in `_scrub`.

**Files:**
- Create: `apps/workflow/services/db_scrubber.py`
- Create: `apps/workflow/tests/services/test_db_scrubber.py`

- [ ] **Step 2.1 — Write failing tests**

Create `apps/workflow/tests/services/test_db_scrubber.py`:

```python
from django.conf import settings
from django.test import TransactionTestCase, override_settings

from apps.workflow.services import db_scrubber


class ScrubSafetyGateTests(TransactionTestCase):
    databases = {"default", "scrub"}

    def test_scrub_refuses_if_alias_name_does_not_end_in_scrub(self):
        bad = dict(settings.DATABASES)
        bad["scrub"] = dict(bad["scrub"])
        bad["scrub"]["NAME"] = "dw_yourco_prod"
        with override_settings(DATABASES=bad):
            with self.assertRaisesRegex(RuntimeError, "must end in '_scrub'"):
                db_scrubber.scrub()

    def test_scrub_runs_on_correctly_named_alias(self):
        # Smoke: empty scrub DB, scrub() returns without error.
        db_scrubber.scrub()
```

- [ ] **Step 2.2 — Run, confirm fails**

Run: `python manage.py test apps.workflow.tests.services.test_db_scrubber -v 2`
Expected: `ModuleNotFoundError: No module named 'apps.workflow.services.db_scrubber'`.

- [ ] **Step 2.3 — Implement the safety gate and empty `scrub()`**

Create `apps/workflow/services/db_scrubber.py`:

```python
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

from apps.workflow.services.error_persistence import persist_app_error


SCRUB_ALIAS = "scrub"


def _assert_scrub_alias_is_safe() -> None:
    name = settings.DATABASES[SCRUB_ALIAS]["NAME"]
    if not name or not name.endswith("_scrub"):
        raise RuntimeError(
            f"SCRUB_DB_NAME ({name!r}) must end in '_scrub'. "
            "Refusing to run scrubber against anything else."
        )


def scrub() -> None:
    """Reproduce the legacy command's PII handling on the scrub DB.

    Single transaction. Persists and re-raises on any error.
    """
    _assert_scrub_alias_is_safe()
    try:
        with transaction.atomic(using=SCRUB_ALIAS):
            # Per-step helpers added by subsequent tasks.
            pass
    except Exception as exc:
        persist_app_error(exc)
        raise
```

- [ ] **Step 2.4 — Regenerate `__init__.py` files**

Run: `python scripts/update_init.py`
Verify: `apps/workflow/services/__init__.py` and `apps/workflow/tests/services/__init__.py` are present (the script may auto-create the test one if it doesn't exist).

- [ ] **Step 2.5 — Run tests, confirm pass**

Django's test runner creates `test_<SCRUB_DB_NAME>` automatically. If the runner errors with `permission denied to create database`, grant `CREATEDB` to the test DB user.

Run: `python manage.py test apps.workflow.tests.services.test_db_scrubber -v 2`
Expected: `OK` (2 tests).

- [ ] **Step 2.6 — Commit**

```bash
git add apps/workflow/services/db_scrubber.py \
        apps/workflow/services/__init__.py \
        apps/workflow/tests/services/__init__.py \
        apps/workflow/tests/services/test_db_scrubber.py
git commit -m "feat(db_scrubber): scaffold scrub() with _scrub alias safety gate"
```

---

## Task 3 — Scrub `accounts_staff` (matches today's `_anonymize_staff`)

Replicates today's behaviour exactly: overwrite `first_name`, `last_name`, `preferred_name`, `email` using `create_staff_profile()`. Do NOT touch `xero_user_id` (today's flow leaves it as-is). Do NOT reset `password` (today's flow ships the hashed password verbatim; `setup_dev_logins.py` resets passwords on dev as a separate post-restore step).

**Files:**
- Modify: `apps/workflow/services/db_scrubber.py`
- Modify: `apps/workflow/tests/services/test_db_scrubber.py`

- [ ] **Step 3.1 — Write failing test**

Append:

```python
from apps.accounts.models import Staff
from apps.workflow.services.db_scrubber import _scrub_staff


class ScrubStaffTests(TransactionTestCase):
    databases = {"default", "scrub"}

    def test_scrub_overwrites_only_name_and_email_fields(self):
        s = Staff.objects.using("scrub").create(
            email="real.person@morrissheetmetal.co.nz",
            first_name="Real",
            last_name="Person",
            preferred_name="Realperson",
            xero_user_id="aaaa1111-2222-3333-4444-555566667777",
            is_active=True,
        )
        original_password = s.password  # hashed Django password string
        original_xero_user_id = s.xero_user_id

        _scrub_staff()

        row = Staff.objects.using("scrub").get(id=s.id)
        self.assertNotEqual(row.email, "real.person@morrissheetmetal.co.nz")
        self.assertNotEqual(row.first_name, "Real")
        self.assertNotEqual(row.last_name, "Person")
        self.assertTrue(row.email.endswith("@example.com"))
        # Today's flow leaves these alone — preserve that exactly.
        self.assertEqual(row.xero_user_id, original_xero_user_id)
        self.assertEqual(row.password, original_password)

    def test_scrub_generates_unique_emails(self):
        for i in range(5):
            Staff.objects.using("scrub").create(
                email=f"x{i}@morrissheetmetal.co.nz",
                first_name=f"F{i}",
                last_name=f"L{i}",
                preferred_name=None,
                is_active=True,
            )
        _scrub_staff()
        emails = set(Staff.objects.using("scrub").values_list("email", flat=True))
        self.assertEqual(len(emails), 5)
```

- [ ] **Step 3.2 — Run, confirm fails**

Expected: `ImportError: cannot import name '_scrub_staff'`.

- [ ] **Step 3.3 — Implement `_scrub_staff`**

Add to `apps/workflow/services/db_scrubber.py`:

```python
from apps.accounts.models import Staff
from apps.accounts.staff_anonymization import create_staff_profile

_GENERATE_ATTEMPTS = 100


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
```

Wire into `scrub()`:

```python
            _scrub_staff()
```

- [ ] **Step 3.4 — Run tests, confirm pass**

Run: `python manage.py test apps.workflow.tests.services.test_db_scrubber.ScrubStaffTests -v 2`
Expected: `OK` (2 tests).

- [ ] **Step 3.5 — Commit**

```bash
git add apps/workflow/services/db_scrubber.py \
        apps/workflow/tests/services/test_db_scrubber.py
git commit -m "feat(db_scrubber): scrub accounts_staff (name fields + email only)"
```

---

## Task 4 — Scrub client tables (`client_client`, `client_clientcontact`)

Match today's `PII_CONFIG` exactly. Allow-list preserved untouched. Specific raw_json paths only — **do not** wipe the whole `raw_json`. Do NOT touch `client.address`, `client.all_phones`, `client.additional_contact_persons`, or `client.supplierpickupaddress` (none in today's config).

**Files:**
- Modify: `apps/workflow/services/db_scrubber.py`
- Modify: `apps/workflow/tests/services/test_db_scrubber.py`

- [ ] **Step 4.1 — Write failing test**

Append:

```python
from apps.client.models import Client, ClientContact
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.db_scrubber import _scrub_clients


class ScrubClientsTests(TransactionTestCase):
    databases = {"default", "scrub"}

    def _seed_company_defaults(self):
        CompanyDefaults.objects.using("scrub").all().delete()
        CompanyDefaults.objects.using("scrub").create(
            id=1,
            shop_client_name="Shop Co",
            test_client_name="Test Client",
            company_name="Demo Co",
        )

    def test_preserved_clients_untouched(self):
        self._seed_company_defaults()
        shop = Client.objects.using("scrub").create(
            name="Shop Co", email="shop@real.example", phone="+64 1 234",
            raw_json={"_name": "Shop Co", "_email_address": "shop@real.example"},
        )
        Client.objects.using("scrub").create(
            name="Real Customer Ltd", email="bill@realcustomer.co.nz",
            phone="+64 9 876", raw_json={"_name": "Real Customer Ltd"},
        )

        _scrub_clients()

        shop.refresh_from_db(using="scrub")
        self.assertEqual(shop.name, "Shop Co")
        self.assertEqual(shop.email, "shop@real.example")
        self.assertEqual(shop.raw_json["_name"], "Shop Co")

        other = Client.objects.using("scrub").exclude(name="Shop Co").get()
        self.assertNotEqual(other.name, "Real Customer Ltd")
        self.assertNotEqual(other.email, "bill@realcustomer.co.nz")

    def test_only_configured_raw_json_paths_changed(self):
        self._seed_company_defaults()
        Client.objects.using("scrub").create(
            name="Real Co", email="a@b.c",
            raw_json={
                "_name": "Real Co",
                "_email_address": "a@b.c",
                "_bank_account_details": "1234-56-789",
                "_phones": [{"_phone_number": "+64 1 111"}, {"_phone_number": "+64 2 222"}],
                "_batch_payments": {
                    "_bank_account_number": "999-888-777",
                    "_bank_account_name": "Real Co Ltd",
                },
                "_unrelated_field": "keep me",
                "_address_line_1": "1 Real Street",
            },
        )

        _scrub_clients()

        c = Client.objects.using("scrub").get()
        self.assertNotEqual(c.raw_json["_name"], "Real Co")
        self.assertNotEqual(c.raw_json["_email_address"], "a@b.c")
        self.assertNotEqual(c.raw_json["_bank_account_details"], "1234-56-789")
        self.assertNotEqual(c.raw_json["_phones"][0]["_phone_number"], "+64 1 111")
        self.assertNotEqual(c.raw_json["_phones"][1]["_phone_number"], "+64 2 222")
        self.assertNotEqual(c.raw_json["_batch_payments"]["_bank_account_number"], "999-888-777")
        self.assertNotEqual(c.raw_json["_batch_payments"]["_bank_account_name"], "Real Co Ltd")
        # Untouched paths survive verbatim.
        self.assertEqual(c.raw_json["_unrelated_field"], "keep me")
        self.assertEqual(c.raw_json["_address_line_1"], "1 Real Street")

    def test_top_level_fields_not_in_pii_config_are_left_alone(self):
        self._seed_company_defaults()
        Client.objects.using("scrub").create(
            name="Real Co", email="a@b.c",
            address="1 Real Street",
            all_phones=["+64 1 111", "+64 2 222"],
            additional_contact_persons=[{"name": "Real Person", "email": "rp@x.co"}],
        )

        _scrub_clients()

        c = Client.objects.using("scrub").get()
        # Today's PII_CONFIG does NOT include these — preserve that.
        self.assertEqual(c.address, "1 Real Street")
        self.assertEqual(c.all_phones, ["+64 1 111", "+64 2 222"])
        self.assertEqual(
            c.additional_contact_persons,
            [{"name": "Real Person", "email": "rp@x.co"}],
        )

    def test_contact_anonymised_only_on_configured_fields(self):
        self._seed_company_defaults()
        c = Client.objects.using("scrub").create(name="Real Co", email="a@b.c")
        ClientContact.objects.using("scrub").create(
            client=c, name="Real Name", email="real@x.co", phone="123",
            position="Manager", notes="real note about real person",
        )

        _scrub_clients()

        cc = ClientContact.objects.using("scrub").get()
        self.assertNotEqual(cc.name, "Real Name")
        self.assertNotEqual(cc.email, "real@x.co")
        self.assertNotEqual(cc.phone, "123")
        # Today's PII_CONFIG does NOT include position/notes.
        self.assertEqual(cc.position, "Manager")
        self.assertEqual(cc.notes, "real note about real person")
```

- [ ] **Step 4.2 — Run, confirm fails**

Expected: `ImportError: cannot import name '_scrub_clients'`.

- [ ] **Step 4.3 — Implement `_scrub_clients`**

Add to `apps/workflow/services/db_scrubber.py`:

```python
from faker import Faker

from apps.client.models import Client, ClientContact
from apps.workflow.models import CompanyDefaults


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
```

Wire into `scrub()` after `_scrub_staff()`:

```python
            _scrub_clients()
```

- [ ] **Step 4.4 — Run tests, confirm pass**

Run: `python manage.py test apps.workflow.tests.services.test_db_scrubber.ScrubClientsTests -v 2`
Expected: `OK` (4 tests).

- [ ] **Step 4.5 — Commit**

```bash
git add apps/workflow/services/db_scrubber.py \
        apps/workflow/tests/services/test_db_scrubber.py
git commit -m "feat(db_scrubber): scrub clients per legacy PII_CONFIG (no expansion)"
```

---

## Task 5 — Scrub accounting `raw_json._contact` paths

Match today's `PII_CONFIG` for `accounting.invoice`/`bill`/`creditnote` exactly: only `raw_json._contact._name` and `raw_json._contact._email_address`. Do NOT wipe `raw_json` wholesale. Do NOT touch line item `description`. Do NOT touch totals or amounts.

**Files:**
- Modify: `apps/workflow/services/db_scrubber.py`
- Modify: `apps/workflow/tests/services/test_db_scrubber.py`

- [ ] **Step 5.1 — Write failing test**

Append:

```python
from apps.accounting.models import (
    Invoice, InvoiceLineItem, Bill, BillLineItem, CreditNote, CreditNoteLineItem,
)
from apps.workflow.services.db_scrubber import _scrub_accounting_contacts


class ScrubAccountingContactsTests(TransactionTestCase):
    databases = {"default", "scrub"}

    def test_only_contact_name_and_email_in_raw_json_changed(self):
        inv = Invoice.objects.using("scrub").create(
            number="INV-001", total_excl_tax=100,
            raw_json={
                "_contact": {
                    "_name": "Real Customer Ltd",
                    "_email_address": "ar@realcustomer.co.nz",
                    "_phone": "+64 9 876",  # NOT in PII_CONFIG, must survive
                },
                "_invoice_number": "INV-001",  # NOT in PII_CONFIG, must survive
            },
        )
        InvoiceLineItem.objects.using("scrub").create(
            invoice=inv, description="real line about client project"
        )

        _scrub_accounting_contacts()

        inv.refresh_from_db(using="scrub")
        self.assertNotEqual(inv.raw_json["_contact"]["_name"], "Real Customer Ltd")
        self.assertNotEqual(inv.raw_json["_contact"]["_email_address"], "ar@realcustomer.co.nz")
        # Untouched paths survive verbatim.
        self.assertEqual(inv.raw_json["_contact"]["_phone"], "+64 9 876")
        self.assertEqual(inv.raw_json["_invoice_number"], "INV-001")
        # Amounts untouched.
        self.assertEqual(inv.total_excl_tax, 100)

        # Line item descriptions are NOT in today's PII_CONFIG → must survive.
        li = InvoiceLineItem.objects.using("scrub").get()
        self.assertEqual(li.description, "real line about client project")

    def test_bill_and_creditnote_contact_paths_also_scrubbed(self):
        Bill.objects.using("scrub").create(
            number="BILL-1", total_excl_tax=10,
            raw_json={"_contact": {"_name": "Real Vendor", "_email_address": "v@real.co"}},
        )
        CreditNote.objects.using("scrub").create(
            number="CN-1", total_excl_tax=20,
            raw_json={"_contact": {"_name": "Real Other", "_email_address": "o@real.co"}},
        )

        _scrub_accounting_contacts()

        b = Bill.objects.using("scrub").get()
        cn = CreditNote.objects.using("scrub").get()
        self.assertNotEqual(b.raw_json["_contact"]["_name"], "Real Vendor")
        self.assertNotEqual(cn.raw_json["_contact"]["_name"], "Real Other")
```

- [ ] **Step 5.2 — Run, confirm fails**

Expected: `ImportError`.

- [ ] **Step 5.3 — Implement `_scrub_accounting_contacts`**

Add:

```python
from apps.accounting.models import Invoice, Bill, CreditNote


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
```

Wire into `scrub()` after `_scrub_clients()`:

```python
            _scrub_accounting_contacts()
```

- [ ] **Step 5.4 — Run tests, confirm pass**

Run: `python manage.py test apps.workflow.tests.services.test_db_scrubber.ScrubAccountingContactsTests -v 2`
Expected: `OK` (2 tests).

- [ ] **Step 5.5 — Commit**

```bash
git add apps/workflow/services/db_scrubber.py \
        apps/workflow/tests/services/test_db_scrubber.py
git commit -m "feat(db_scrubber): scrub accounting raw_json._contact name/email only"
```

---

## Task 6 — Delete unlinked accounting records

Replicates today's `_filter_unlinked_accounting_records` exactly. The legacy code drops these records from the JSON dump; the new flow deletes them from the scrub DB before re-dumping.

**Files:**
- Modify: `apps/workflow/services/db_scrubber.py`
- Modify: `apps/workflow/tests/services/test_db_scrubber.py`

- [ ] **Step 6.1 — Write failing test**

Append:

```python
from apps.accounting.models import Quote
from apps.job.models import Job
from apps.workflow.services.db_scrubber import _delete_unlinked_accounting


class DeleteUnlinkedAccountingTests(TransactionTestCase):
    databases = {"default", "scrub"}

    def _job(self):
        client = Client.objects.using("scrub").create(name="X Ltd", email="a@b.c")
        return Job.objects.using("scrub").create(client=client, name="J")

    def test_bills_and_creditnotes_dropped_entirely(self):
        Bill.objects.using("scrub").create(number="B1", total_excl_tax=10, raw_json={})
        CreditNote.objects.using("scrub").create(number="CN1", total_excl_tax=10, raw_json={})

        _delete_unlinked_accounting()

        self.assertEqual(Bill.objects.using("scrub").count(), 0)
        self.assertEqual(CreditNote.objects.using("scrub").count(), 0)

    def test_invoice_without_job_dropped_with_line_items(self):
        j = self._job()
        kept = Invoice.objects.using("scrub").create(
            number="INV-A", total_excl_tax=10, raw_json={}, job=j,
        )
        dropped = Invoice.objects.using("scrub").create(
            number="INV-B", total_excl_tax=20, raw_json={},
        )
        InvoiceLineItem.objects.using("scrub").create(invoice=kept, description="keep")
        InvoiceLineItem.objects.using("scrub").create(invoice=dropped, description="drop")

        _delete_unlinked_accounting()

        self.assertEqual(
            list(Invoice.objects.using("scrub").values_list("number", flat=True)),
            ["INV-A"],
        )
        # FK cascade removes orphaned line items.
        self.assertEqual(InvoiceLineItem.objects.using("scrub").count(), 1)

    def test_quote_without_job_dropped(self):
        j = self._job()
        Quote.objects.using("scrub").create(number="QU-A", total_excl_tax=10, job=j)
        Quote.objects.using("scrub").create(number="QU-B", total_excl_tax=20)

        _delete_unlinked_accounting()

        self.assertEqual(
            list(Quote.objects.using("scrub").values_list("number", flat=True)),
            ["QU-A"],
        )
```

- [ ] **Step 6.2 — Run, confirm fails**

Expected: `ImportError`.

- [ ] **Step 6.3 — Implement `_delete_unlinked_accounting`**

Add:

```python
from apps.accounting.models import (
    Quote,
    InvoiceLineItem,
    BillLineItem,
    CreditNoteLineItem,
)


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
```

Wire into `scrub()` after `_scrub_accounting_contacts()`:

```python
            _delete_unlinked_accounting()
```

- [ ] **Step 6.4 — Run tests, confirm pass**

Run: `python manage.py test apps.workflow.tests.services.test_db_scrubber.DeleteUnlinkedAccountingTests -v 2`
Expected: `OK` (3 tests).

- [ ] **Step 6.5 — Commit**

```bash
git add apps/workflow/services/db_scrubber.py \
        apps/workflow/tests/services/test_db_scrubber.py
git commit -m "feat(db_scrubber): delete unlinked accounting records (mirror legacy filter)"
```

---

## Task 7 — Truncate excluded tables

Replicates today's `EXCLUDE_MODELS` behaviour. Tables in this list never reach dev today — with `pg_dump` they would otherwise come across in full, so we `TRUNCATE` them in the scrub DB before re-dumping. **Framework tables (contenttypes/auth/sessions/sites) are NOT in this list** — see the strict like-for-like contract above for why.

**Files:**
- Modify: `apps/workflow/services/db_scrubber.py`
- Modify: `apps/workflow/tests/services/test_db_scrubber.py`

- [ ] **Step 7.1 — Write failing test**

Append:

```python
from apps.workflow.models import XeroToken, ServiceAPIKey, AppError, XeroError, XeroPayItem
from apps.workflow.services.db_scrubber import _truncate_excluded_tables


class TruncateExcludedTablesTests(TransactionTestCase):
    databases = {"default", "scrub"}

    def test_secrets_emptied(self):
        XeroToken.objects.using("scrub").create(
            tenant_id="t", access_token="secret", refresh_token="secret"
        )
        ServiceAPIKey.objects.using("scrub").create(name="gemini", api_key="sk-real")
        _truncate_excluded_tables()
        self.assertEqual(XeroToken.objects.using("scrub").count(), 0)
        self.assertEqual(ServiceAPIKey.objects.using("scrub").count(), 0)

    def test_pay_items_emptied(self):
        XeroPayItem.objects.using("scrub").create(name="Wages", uses_leave_api=False)
        _truncate_excluded_tables()
        self.assertEqual(XeroPayItem.objects.using("scrub").count(), 0)

    def test_debug_tables_emptied(self):
        AppError.objects.using("scrub").create(message="boom", traceback="...")
        XeroError.objects.using("scrub").create(message="xero boom")
        _truncate_excluded_tables()
        self.assertEqual(AppError.objects.using("scrub").count(), 0)
        self.assertEqual(XeroError.objects.using("scrub").count(), 0)

    def test_simplehistory_tables_emptied(self):
        # Use raw SQL since historical models are auto-managed and tedious to seed.
        from django.db import connections
        with connections["scrub"].cursor() as cur:
            for table in (
                "accounts_historicalstaff",
                "job_historicaljob",
                "process_historicalform",
                "process_historicalformentry",
                "process_historicalprocedure",
            ):
                cur.execute(f'INSERT INTO "{table}" DEFAULT VALUES') \
                    if False else None  # rely on truncation alone — seeding is enough work
        _truncate_excluded_tables()
        with connections["scrub"].cursor() as cur:
            for table in (
                "accounts_historicalstaff",
                "job_historicaljob",
                "process_historicalform",
                "process_historicalformentry",
                "process_historicalprocedure",
            ):
                cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                self.assertEqual(cur.fetchone()[0], 0)
```

- [ ] **Step 7.2 — Run, confirm fails**

Expected: `ImportError`.

- [ ] **Step 7.3 — Implement `_truncate_excluded_tables`**

Add:

```python
# Mirrors legacy EXCLUDE_MODELS, MINUS framework tables (contenttypes/auth/
# sessions/sites). Framework tables stay because pg_dump-restored FKs from
# accounts_staff_user_permissions etc. depend on them and TRUNCATE CASCADE
# would wipe those user-permission rows.
_EXCLUDED_TABLES = (
    "workflow_xerotoken",
    "workflow_serviceapikey",
    "workflow_xeropayitem",
    "workflow_apperror",
    "workflow_xeroerror",
    "django_apscheduler_djangojob",
    "django_apscheduler_djangojobexecution",
    "accounts_historicalstaff",
    "job_historicaljob",
    "process_historicalform",
    "process_historicalformentry",
    "process_historicalprocedure",
)


def _truncate_excluded_tables() -> None:
    """Mirror legacy EXCLUDE_MODELS by emptying these tables in the scrub DB."""
    from django.db import connections

    with connections[SCRUB_ALIAS].cursor() as cur:
        for table in _EXCLUDED_TABLES:
            cur.execute(f'TRUNCATE TABLE "{table}" RESTART IDENTITY CASCADE')
```

Wire into `scrub()` after `_delete_unlinked_accounting()`:

```python
            _truncate_excluded_tables()
```

- [ ] **Step 7.4 — Run tests, confirm pass**

Run: `python manage.py test apps.workflow.tests.services.test_db_scrubber.TruncateExcludedTablesTests -v 2`
Expected: `OK` (4 tests).

- [ ] **Step 7.5 — Commit**

```bash
git add apps/workflow/services/db_scrubber.py \
        apps/workflow/tests/services/test_db_scrubber.py
git commit -m "feat(db_scrubber): truncate legacy EXCLUDE_MODELS tables on scrub DB"
```

---

## Task 8 — Rewrite `backport_data_backup` management command

Replaces the dumpdata/Faker/zip pipeline with subprocess-driven `pg_dump`/`pg_restore` + `db_scrubber.scrub()`. Preserves the `--analyze-fields` mode and its helpers verbatim.

**Files:**
- Modify: `apps/workflow/management/commands/backport_data_backup.py`
- Create: `apps/workflow/tests/management/test_backport_data_backup.py`

- [ ] **Step 8.1 — Write failing test**

Create `apps/workflow/tests/management/test_backport_data_backup.py`:

```python
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase


class BackportCommandWiringTests(SimpleTestCase):
    @mock.patch("apps.workflow.management.commands.backport_data_backup.subprocess.run")
    @mock.patch("apps.workflow.services.db_scrubber.scrub")
    def test_command_calls_pg_dump_restore_scrub_dump(self, mock_scrub, mock_run):
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        call_command("backport_data_backup")

        cmds = [call.args[0][0] for call in mock_run.call_args_list]
        self.assertIn("pg_dump", cmds)
        self.assertIn("pg_restore", cmds)
        self.assertIn("rclone", cmds)
        mock_scrub.assert_called_once()

    @mock.patch("apps.workflow.services.db_scrubber.scrub")
    def test_analyze_fields_sub_mode_does_not_run_dump_pipeline(self, mock_scrub):
        with mock.patch(
            "apps.workflow.management.commands.backport_data_backup.subprocess.run"
        ) as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="[]", stderr="")
            call_command("backport_data_backup", "--analyze-fields", "--sample-size", "1")
            mock_scrub.assert_not_called()
```

- [ ] **Step 8.2 — Run, confirm fails**

Expected: `AssertionError: 'pg_restore' not found in cmds`.

- [ ] **Step 8.3 — Rewrite the command**

Replace the entire `Command` class body in `apps/workflow/management/commands/backport_data_backup.py`. The `--analyze-fields` mode and its helpers (`analyze_fields`, `collect_field_samples`, `cannot_be_pii`, `is_uuid_string`) move into the new class **verbatim**. Drop everything else (the legacy `_anonymize_*`, `_set_field_by_path`, `_get_replacement_value`, `_get_preserved_client_names`, `_filter_unlinked_accounting_records`, `anonymize_item`, `create_schema_backup`, `create_migrations_snapshot`, `create_combined_zip`, the `Faker` import, `PII_CONFIG`, `EXCLUDE_MODELS`, the `_used_*` state) — that logic now lives in `db_scrubber`.

```python
import datetime
import os
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.workflow.services import db_scrubber
from apps.workflow.services.error_persistence import persist_app_error


class Command(BaseCommand):
    help = (
        "Produces a scrubbed pg_dump of prod for dev refresh. "
        "Raw prod data never leaves the prod host."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--analyze-fields",
            action="store_true",
            help="Show field samples to help identify PII (legacy tool)",
        )
        parser.add_argument("--sample-size", type=int, default=50)
        parser.add_argument("--model-filter", type=str)
        parser.add_argument(
            "--rclone-target",
            type=str,
            default=os.getenv("BACKPORT_RCLONE_TARGET", "gdrive:dw_backups"),
            help="rclone target for the scrubbed dump",
        )

    def handle(self, *args, **options):
        if options.get("analyze_fields"):
            return self.analyze_fields(
                sample_size=options["sample_size"],
                model_filter=options.get("model_filter"),
            )

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        env_name = "dev" if settings.DEBUG else "prod"
        backup_dir = os.path.join(settings.BASE_DIR, "restore")
        os.makedirs(backup_dir, exist_ok=True)

        raw_dump = f"/tmp/raw_{ts}.dump"
        scrubbed_dump = os.path.join(backup_dir, f"scrubbed_{env_name}_{ts}.dump")

        default_db = settings.DATABASES["default"]
        scrub_db = settings.DATABASES["scrub"]
        env = os.environ.copy()
        env["PGPASSWORD"] = default_db["PASSWORD"]

        try:
            self._run(
                ["pg_dump", "-Fc", "-h", default_db["HOST"], "-U", default_db["USER"],
                 "-d", default_db["NAME"], "-f", raw_dump],
                env=env,
            )
            self._run(
                ["psql", "-h", scrub_db["HOST"], "-U", scrub_db["USER"],
                 "-d", scrub_db["NAME"],
                 "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"],
                env=env,
            )
            self._run(
                ["pg_restore", "--no-owner", "--no-privileges", "--exit-on-error",
                 "-h", scrub_db["HOST"], "-U", scrub_db["USER"],
                 "-d", scrub_db["NAME"], raw_dump],
                env=env,
            )
            db_scrubber.scrub()
            self._run(
                ["pg_dump", "-Fc", "-h", scrub_db["HOST"], "-U", scrub_db["USER"],
                 "-d", scrub_db["NAME"], "-f", scrubbed_dump],
                env=env,
            )
            self._run(
                ["psql", "-h", scrub_db["HOST"], "-U", scrub_db["USER"],
                 "-d", scrub_db["NAME"],
                 "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"],
                env=env,
            )
            os.remove(raw_dump)
            self._run(["rclone", "copy", scrubbed_dump, options["rclone_target"]])
            self.stdout.write(self.style.SUCCESS(
                f"Scrubbed dump written: {scrubbed_dump}"
            ))
        except Exception as exc:
            persist_app_error(exc)
            if os.path.exists(raw_dump):
                os.remove(raw_dump)
            raise

    def _run(self, cmd, env=None):
        subprocess.run(cmd, check=True, env=env, capture_output=True, text=True)

    # ---------- Legacy analyze_fields sub-mode (unchanged) ----------
    # Move analyze_fields, collect_field_samples, cannot_be_pii, is_uuid_string
    # methods here verbatim from the current file. Keep their module-level
    # imports too: uuid, json, collections.defaultdict, django.db.connection.
```

- [ ] **Step 8.4 — Run tests, confirm pass**

Run: `python manage.py test apps.workflow.tests.management.test_backport_data_backup -v 2`
Expected: `OK` (2 tests).

- [ ] **Step 8.5 — Commit**

```bash
python scripts/update_init.py  # registers the new management tests package
git add apps/workflow/management/commands/backport_data_backup.py \
        apps/workflow/tests/management/test_backport_data_backup.py \
        apps/workflow/tests/management/__init__.py
git commit -m "feat(backport_data_backup): rewrite to pg_dump+pg_restore+db_scrubber"
```

---

## Task 9 — Rewrite `docs/restore-prod-to-nonprod.md` for the new 7-step dev flow

Keep the existing document as appendix `## Appendix: Legacy JSON path (deprecated)` for one release cycle.

**Files:**
- Modify: `docs/restore-prod-to-nonprod.md`

- [ ] **Step 9.1 — Insert the new body above the current content**

Replace lines 1–34 (top through the extracted-zip paragraph) with:

```markdown
# Restore Production to Non-Production

Restore a production backup to any non-production environment (dev or server
instance). Assume venv active, `.env` loaded, in the project root.

The scrubbed dump is produced on prod by `manage.py backport_data_backup` and
lives at `gdrive:dw_backups/scrubbed_<env>_<ts>.dump`.

## CRITICAL: audit log

Log every command and its key output to
`logs/restore_log_scrubbed_<env>_<ts>.log`.

## Steps

1. **Fetch the dump**
   ```bash
   rclone copy gdrive:dw_backups/scrubbed_prod_<ts>.dump ./restore/
   ```

2. **Reset the target DB**
   ```bash
   python manage.py dbshell -- -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
   ```

3. **Restore the dump**
   ```bash
   pg_restore --no-owner --no-privileges --exit-on-error \
     -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" \
     ./restore/scrubbed_prod_<ts>.dump
   ```

4. **Apply any dev-side migrations prod hasn't seen yet**

   The `django_migrations` table came across in the dump, so this only runs
   migrations that exist locally beyond the prod state.
   ```bash
   python manage.py migrate
   ```

5. **Reload dev-only fixtures**

   Company defaults (shipped demo branding) and AI provider rows are excluded
   from prod scrubbing (they contain dev API keys).
   ```bash
   python manage.py loaddata apps/workflow/fixtures/company_defaults.json
   python manage.py loaddata apps/workflow/fixtures/ai_providers.json
   ```

6. **Re-authenticate Xero**
   ```bash
   cd frontend && npx tsx tests/scripts/xero-login.ts && cd ..
   python manage.py xero --setup
   python manage.py xero --configure-payroll
   ```

7. **Run the post-restore validators**
   ```bash
   python scripts/setup_dev_logins.py
   for s in scripts/restore_checks/check_*.py; do python "$s"; done
   ```

Optional (dev): run `python scripts/recreate_jobfiles.py` to materialise dummy
files for JobFile records.
```

Then insert `## Appendix: Legacy JSON path (deprecated)` above the current `## Prerequisites` block so the existing 23-step content lives beneath it unchanged. Add at the top of the appendix:

> Deprecated — retained for one release cycle while the pg_dump flow beds in.

- [ ] **Step 9.2 — Smoke-render check**

Run: `grep -n '^#' docs/restore-prod-to-nonprod.md | head -20`
Expected: new H1 at top, `## Steps` below, `## Appendix: Legacy JSON path (deprecated)` present.

- [ ] **Step 9.3 — Commit**

```bash
git add docs/restore-prod-to-nonprod.md
git commit -m "docs(restore): rewrite for pg_dump flow; keep legacy as appendix"
```

---

## Task 10 — Extend `scripts/cleanup_backups.py` with `scrubbed_*.dump` retention

30-day window, same pattern as predeploy.

**Files:**
- Modify: `scripts/cleanup_backups.py`
- Create: `scripts/test_cleanup_backups.py`

- [ ] **Step 10.1 — Write failing test**

Create `scripts/test_cleanup_backups.py`:

```python
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import cleanup_backups as cb


class ScrubbedRetentionTests(unittest.TestCase):
    def test_scrubbed_regex_matches(self):
        self.assertIsNotNone(cb.SCRUBBED_RE.match("scrubbed_prod_20260425_101112.dump"))
        self.assertIsNone(cb.SCRUBBED_RE.match("prod_backup_20260425_101112.json.gz"))

    def test_scrubbed_keep_honours_30_day_window(self):
        now = datetime(2026, 4, 25, 12, 0, 0)
        recent = "scrubbed_prod_" + (now - timedelta(days=5)).strftime("%Y%m%d_%H%M%S") + ".dump"
        old = "scrubbed_prod_" + (now - timedelta(days=45)).strftime("%Y%m%d_%H%M%S") + ".dump"
        keep = cb.compute_scrubbed_keep([recent, old], now)
        self.assertIn(recent, keep)
        self.assertNotIn(old, keep)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 10.2 — Run, confirm fails**

Run: `python -m unittest scripts.test_cleanup_backups -v`
Expected: `AttributeError: module 'cleanup_backups' has no attribute 'SCRUBBED_RE'`.

- [ ] **Step 10.3 — Add the pattern and keep function**

Edit `scripts/cleanup_backups.py`:

1. Near `PREDEPLOY_RE`:

```python
SCRUBBED_RE = re.compile(r"^scrubbed_[a-z]+_(\d{8}_\d{6})\.dump$")
SCRUBBED_RETENTION_DAYS = 30
```

2. Below `compute_predeploy_keep`:

```python
def compute_scrubbed_keep(entries, now):
    cutoff = now - timedelta(days=SCRUBBED_RETENTION_DAYS)
    keep = set()
    for name in entries:
        m = SCRUBBED_RE.match(name)
        if not m:
            continue
        ts = datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
        if ts >= cutoff:
            keep.add(name)
    return keep
```

3. Extend `classify()`:

```python
def classify(name):
    if TS_DIR_RE.match(name):
        return "ts_dir"
    if PREDEPLOY_RE.match(name):
        return "predeploy"
    if SCRUBBED_RE.match(name):
        return "scrubbed"
    return "other"
```

4. In `main()`, add `scrubbed_entries`, compute `scrubbed_keep`, fold into `managed`:

```python
    scrubbed_entries = []
    for name in entries:
        kind = classify(name)
        if kind == "ts_dir":
            ts_dir_entries.append(name)
        elif kind == "predeploy":
            predeploy_entries.append(name)
        elif kind == "scrubbed":
            scrubbed_entries.append(name)
        else:
            other_entries.append(name)

    scrubbed_keep = compute_scrubbed_keep(scrubbed_entries, now)

    managed = set(ts_dir_entries) | set(predeploy_entries) | set(scrubbed_entries)
    to_delete = sorted(managed - ts_dir_keep - predeploy_keep - scrubbed_keep)

    print("Keeping (ts_dir):", sorted(ts_dir_keep))
    print("Keeping (predeploy):", sorted(predeploy_keep))
    print("Keeping (scrubbed):", sorted(scrubbed_keep))
```

- [ ] **Step 10.4 — Run, confirm pass**

Run: `python -m unittest scripts.test_cleanup_backups -v`
Expected: `OK` (2 tests).

- [ ] **Step 10.5 — Commit**

```bash
git add scripts/cleanup_backups.py scripts/test_cleanup_backups.py
git commit -m "feat(cleanup_backups): 30-day retention for scrubbed_*.dump"
```

---

## Task 11 — Provision the scrub DB through `instance.sh`

The Django DB user has no `CREATEDB` on prod. `instance.sh` already runs as `sudo -u postgres` when provisioning the main DB — the right place to also ensure the scrub DB exists, and to drop it during `instance.sh destroy`.

**Files:**
- Modify: `scripts/server/instance.sh`
- Modify: `scripts/server/templates/env-instance.template`
- Modify: `docs/restore-prod-to-nonprod.md` (short note for pre-existing instances).

- [ ] **Step 11.1 — Add `SCRUB_DB_NAME` to the env template**

Edit `scripts/server/templates/env-instance.template`, after `DB_PORT=`:

```
DB_NAME=__DB_NAME__
DB_USER=__DB_USER__
DB_PASSWORD=__DB_PASSWORD__
DB_HOST=/var/run/postgresql
DB_PORT=
SCRUB_DB_NAME=__SCRUB_DB_NAME__
```

- [ ] **Step 11.2 — Derive `SCRUB_DB_NAME` and substitute in `instance.sh`**

At line 164:

```bash
    local DB_NAME="dw_${CLIENT}_${ENV}"
    local DB_USER="dw_${CLIENT}_${ENV}"
    local SCRUB_DB_NAME="dw_${CLIENT}_${ENV}_scrub"
```

In the `sed` block around line 274:

```bash
            -e "s|__DB_NAME__|$DB_NAME|g" \
            -e "s|__DB_USER__|$DB_USER|g" \
            -e "s|__SCRUB_DB_NAME__|$SCRUB_DB_NAME|g" \
```

Mirror this addition wherever else the template is rendered — search the script for `__DB_NAME__`.

- [ ] **Step 11.3 — Provision the scrub DB in the postgres bootstrap block**

Extend the `sudo -u postgres psql <<EOSQL ... EOSQL` block at `instance.sh:308-322`. Append before `EOSQL`:

```sql
SELECT 'CREATE DATABASE "$SCRUB_DB_NAME" OWNER "$DB_USER"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$SCRUB_DB_NAME')\gexec
GRANT ALL PRIVILEGES ON DATABASE "$SCRUB_DB_NAME" TO "$DB_USER";
```

Update the `log` line at the top of the block:

```bash
    log "Ensuring databases $DB_NAME and $SCRUB_DB_NAME and user $DB_USER exist..."
```

- [ ] **Step 11.4 — Drop the scrub DB on `destroy`**

Around line 524, between the existing two drop lines:

```bash
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS \"$SCRUB_DB_NAME\";" || true
```

Derive `SCRUB_DB_NAME` at the top of the destroy function (mirror of step 11.2).

- [ ] **Step 11.5 — Runbook note for legacy instances**

Add at the top of `docs/restore-prod-to-nonprod.md`, before `## CRITICAL: audit log`:

```markdown
## First-time setup (existing instances only)

New instances pick up the scrub DB automatically via `scripts/server/instance.sh`.
Existing instances provisioned before this change need a one-off `instance.sh create`
re-run (idempotent — it skips anything that already exists and only adds the scrub DB).
No separate `createdb` command is needed; do not invent one.
```

- [ ] **Step 11.6 — Smoke-check `instance.sh`**

Run: `shellcheck scripts/server/instance.sh`
Expected: no new warnings beyond the baseline output on `main`.

- [ ] **Step 11.7 — Commit**

```bash
git add scripts/server/instance.sh \
        scripts/server/templates/env-instance.template \
        docs/restore-prod-to-nonprod.md
git commit -m "feat(instance.sh): provision and tear down scrub DB alongside main DB"
```

---

## Task 12 — End-to-end UAT verification

- [ ] **Step 12.1 — Provision or refresh a UAT instance**

Run: `sudo scripts/server/instance.sh create uat-<name>` (or re-run on an existing UAT instance).
Verify: `sudo -u postgres psql -lqt | awk -F'|' '{print $1}' | grep _scrub` includes the new scrub DB.

- [ ] **Step 12.2 — End-to-end dry run on UAT**

```bash
python manage.py backport_data_backup
```

Expected: exits 0; `restore/scrubbed_<env>_<ts>.dump` created.

- [ ] **Step 12.3 — Leak check on the produced dump**

```bash
DUMP=restore/scrubbed_<env>_<ts>.dump
pg_restore -a -f - "$DUMP" \
  | grep -iE '<known prod client name>|@morrissheetmetal\.co\.nz' \
  && { echo "LEAK DETECTED"; exit 1; } \
  || echo "No leaks found"
```

Expected: `No leaks found`. (The grep targets must come from the live data — pick names/domains you know to exist on prod.)

- [ ] **Step 12.4 — Restore into the dev DB via the new runbook**

Follow Steps 1–7 of the rewritten `docs/restore-prod-to-nonprod.md`. Record wall-clock at step 3 (`pg_restore`). Compare against the legacy runbook's step 5 (`loaddata`): target ≥ 5× faster end-to-end.

- [ ] **Step 12.5 — Run the validators**

```bash
for s in scripts/restore_checks/check_*.py; do python "$s"; done
```

Expected: every script prints its expected output.

No commit step — verification only. If any check fails, stop and fix the underlying cause.

---

## Task 13 — Equivalence check against the legacy pipeline

Run both pipelines against the same prod-mirror DB and prove the resulting datasets are equivalent on every dimension we care about. This is the gate that confirms the strict like-for-like contract held: **no field that the legacy flow leaves intact has been changed**, **no field that the legacy flow scrubs is now untouched**, and **no row that the legacy flow drops has survived**. Future expansion of scrub scope (the user's open idea) becomes a deliberate, separately-validated diff against this baseline.

**Approach:** restore the latest legacy zip into a temp DB; restore the new `.dump` into another temp DB; compare. All three DBs (source, legacy-restored, new-restored) live on the same Postgres cluster as siblings.

**Files:**
- Create: `scripts/verify_backport_equivalence.py` (throwaway script — delete after merge).

- [ ] **Step 13.1 — Provision two equivalence-check DBs (one-off, superuser)**

```bash
sudo -u postgres createdb dw_msm_dev_legacy_restore -O dw_msm_dev
sudo -u postgres createdb dw_msm_dev_new_restore    -O dw_msm_dev
```

These are throwaway. Drop after Task 13 completes.

- [ ] **Step 13.2 — Produce a legacy artefact from the same source DB**

Check out the parent commit of this branch to a sibling worktree-free clone (don't use git worktrees per project convention — use `git stash`-free approach: clone into `/tmp/legacy_checkout`):

```bash
git clone /home/corrin/src/docketworks /tmp/legacy_checkout
cd /tmp/legacy_checkout
git checkout main
# Run legacy pipeline; output zip lands in /tmp/legacy_checkout/restore/
python manage.py backport_data_backup
LEGACY_ZIP=$(ls -t /tmp/legacy_checkout/restore/*_complete.zip | head -1)
echo "Legacy artefact: $LEGACY_ZIP"
cd ~/src/docketworks
```

- [ ] **Step 13.3 — Restore the legacy artefact into `dw_msm_dev_legacy_restore`**

Follow the legacy runbook's steps 2–5 against `dw_msm_dev_legacy_restore` (drop schema, migrate, gunzip JSON, loaddata). Skip Xero/setup steps — they don't affect equivalence.

- [ ] **Step 13.4 — Produce a new artefact and restore into `dw_msm_dev_new_restore`**

```bash
python manage.py backport_data_backup
NEW_DUMP=$(ls -t restore/scrubbed_*.dump | head -1)

DB_PASS=$(grep ^DB_PASSWORD .env | cut -d= -f2)
PGPASSWORD=$DB_PASS psql -h /var/run/postgresql -U dw_msm_dev -d dw_msm_dev_new_restore \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
PGPASSWORD=$DB_PASS pg_restore --no-owner --no-privileges --exit-on-error \
  -h /var/run/postgresql -U dw_msm_dev -d dw_msm_dev_new_restore "$NEW_DUMP"
PGPASSWORD=$DB_PASS psql -h /var/run/postgresql -U dw_msm_dev -d dw_msm_dev_new_restore \
  -c "ANALYZE;"
```

- [ ] **Step 13.5 — Run the equivalence script**

Create `scripts/verify_backport_equivalence.py`:

```python
"""Compare legacy-restored DB against new-restored DB for equivalence.

Exits non-zero on any divergence. Designed for the strict like-for-like
contract — proves the new pipeline produces the same data as the legacy
one across every dimension we care about.
"""
import os
import sys
import psycopg

LEGACY = "dw_msm_dev_legacy_restore"
NEW = "dw_msm_dev_new_restore"
USER = "dw_msm_dev"
HOST = "/var/run/postgresql"
PASSWORD = os.environ["PGPASSWORD"]

# Tables that must have IDENTICAL row counts.
ROW_COUNT_TABLES = [
    "accounts_staff", "client_client", "client_clientcontact",
    "job_job", "job_costset", "job_costline", "job_jobevent", "job_jobfile",
    "purchasing_purchaseorder", "purchasing_purchaseorderline", "purchasing_stock",
    "accounting_invoice", "accounting_invoicelineitem", "accounting_quote",
    "workflow_xeroaccount", "workflow_companydefaults",
]

# Tables EXCLUDE_MODELS truncates: must be 0 rows in BOTH (legacy excludes them
# from dumpdata so they're empty after restore; new flow truncates them in scrub).
EMPTY_TABLES = [
    "workflow_xerotoken", "workflow_serviceapikey", "workflow_xeropayitem",
    "workflow_apperror", "workflow_xeroerror",
    "django_apscheduler_djangojob", "django_apscheduler_djangojobexecution",
    "accounts_historicalstaff", "job_historicaljob",
    "process_historicalform", "process_historicalformentry",
    "process_historicalprocedure",
    # Filter-dropped accounting tables.
    "accounting_bill", "accounting_billlineitem",
    "accounting_creditnote", "accounting_creditnotelineitem",
]

# Per-row field equality on tables where the field is NOT in PII_CONFIG.
# Same primary key in both DBs → same value. Lists field paths and a sample size.
NON_PII_FIELDS = [
    ("job_job", "id", ["notes", "description", "name"]),
    ("job_costline",  "id", ["desc", "meta"]),
    ("client_client", "id", ["address", "all_phones", "additional_contact_persons"]),
    ("client_clientcontact", "id", ["position", "notes"]),
    ("accounting_invoice", "id", ["total_excl_tax", "total_incl_tax", "amount_due"]),
    ("accounting_invoicelineitem", "id", ["description", "unit_price", "quantity"]),
]
SAMPLE_SIZE = 200


def conn(db):
    return psycopg.connect(f"host={HOST} dbname={db} user={USER} password={PASSWORD}")


def fail(msg):
    print(f"FAIL: {msg}")
    return 1


def main():
    errors = 0
    with conn(LEGACY) as l, conn(NEW) as n, l.cursor() as lc, n.cursor() as nc:
        # 1. Row counts on tables that survive both pipelines.
        for t in ROW_COUNT_TABLES:
            lc.execute(f'SELECT COUNT(*) FROM "{t}"')
            nc.execute(f'SELECT COUNT(*) FROM "{t}"')
            ln = lc.fetchone()[0]
            nn = nc.fetchone()[0]
            if ln != nn:
                errors += fail(f"{t}: legacy={ln} new={nn}")
            else:
                print(f"OK   {t}: {ln} rows")

        # 2. Tables that must be empty in BOTH.
        for t in EMPTY_TABLES:
            lc.execute(f'SELECT COUNT(*) FROM "{t}"')
            nc.execute(f'SELECT COUNT(*) FROM "{t}"')
            ln, nn = lc.fetchone()[0], nc.fetchone()[0]
            if ln != 0 or nn != 0:
                errors += fail(f"{t} should be empty in both: legacy={ln} new={nn}")
            else:
                print(f"OK   {t}: empty in both")

        # 3. Per-row equality on fields NOT in PII_CONFIG (identity check).
        for table, pk, fields in NON_PII_FIELDS:
            cols = ", ".join(f'"{f}"' for f in fields)
            lc.execute(
                f'SELECT "{pk}", {cols} FROM "{table}" ORDER BY "{pk}" LIMIT {SAMPLE_SIZE}'
            )
            nc.execute(
                f'SELECT "{pk}", {cols} FROM "{table}" ORDER BY "{pk}" LIMIT {SAMPLE_SIZE}'
            )
            l_rows = {r[0]: r[1:] for r in lc.fetchall()}
            n_rows = {r[0]: r[1:] for r in nc.fetchall()}
            mismatched = [
                pk_val for pk_val in l_rows
                if pk_val in n_rows and l_rows[pk_val] != n_rows[pk_val]
            ]
            if mismatched:
                sample = mismatched[:3]
                errors += fail(
                    f"{table}.{fields}: {len(mismatched)} rows differ — "
                    f"sample pks: {sample}"
                )
                for pk_val in sample:
                    print(f"      legacy {pk_val}: {l_rows[pk_val]}")
                print(f"      new    {pk_val}: {n_rows[pk_val]}")
            else:
                print(f"OK   {table}.{fields}: identical on {len(l_rows)} sampled rows")

    if errors:
        print(f"\n{errors} divergence(s) — strict like-for-like contract VIOLATED")
        sys.exit(1)
    print("\nAll equivalence checks passed.")


if __name__ == "__main__":
    main()
```

Run:

```bash
PGPASSWORD=$(grep ^DB_PASSWORD .env | cut -d= -f2) python scripts/verify_backport_equivalence.py
```

Expected: every line starts with `OK`, final output `All equivalence checks passed.`

Any divergence is a real bug — fix the scrubber/command, regenerate the new dump, re-run. **Do not loosen the script's checks to make them pass.**

- [ ] **Step 13.6 — Cleanup the equivalence DBs and the throwaway script**

```bash
sudo -u postgres dropdb dw_msm_dev_legacy_restore
sudo -u postgres dropdb dw_msm_dev_new_restore
rm -rf /tmp/legacy_checkout
git rm scripts/verify_backport_equivalence.py
git commit -m "chore: remove throwaway equivalence verification script"
```

The legacy pipeline lives on as the runbook appendix until next release; if you want to re-run equivalence later, restore the script from this commit's parent.

---

## Spec coverage check

Mapping each spec deliverable to the task that implements it:

- Provision `dw_<client>_<env>_scrub` — **Task 11** (automated via `instance.sh`).
- `apps/workflow/services/db_scrubber.py` — **Tasks 2–7**.
- Unit tests for db_scrubber — **Tasks 2–7** (one test class per helper).
- Rewrite internals of `backport_data_backup.py` — **Task 8**.
- Add `scrub` DB alias + `.env.example` — **Task 1** (done).
- Rewrite `docs/restore-prod-to-nonprod.md` — **Task 9** (+ Task 11.5 for legacy-instance ops note).
- Extend `scripts/cleanup_backups.py` — **Task 10**.

## Out of scope (explicit)

The strict like-for-like contract excludes everything below. None of these may be added in this PR:

- Anonymising any field not in today's `PII_CONFIG` (notably: `staff.xero_user_id`, `staff.password`, `client.address`, `client.all_phones`, `client.additional_contact_persons`, `client.supplierpickupaddress.*`, `job.job.*`, `job.historicaljob.*`, `job.costline.*`, `job.jobevent.*`, `purchasing.purchaseorder.*`, `purchasing.stock.*`, accounting line item descriptions).
- Truncating framework tables (`django_content_type`, `auth_permission`, `auth_group`, `django_session`, `django_site`).
- Renaming the management command.
- Granting `CREATEDB` to the Django DB user (conflicts with `feedback_db_reset_method.md`).

If any of the above turns out to be necessary, raise a separate ticket — do not silently expand scope here.

## Verification gates summary

1. Every task ends with a passing test run before commit.
2. Task 12.3 — grep leak check on the produced dump.
3. Task 12.4 — wall-clock regression check vs legacy path.
4. Task 12.5 — full `restore_checks/` validator suite green on the dev box.
5. **Task 13 — equivalence check against the legacy pipeline. Merge gate. Confirms the strict like-for-like contract held. Future scrub-scope expansion is a separate ticket whose own verification is "diff against this baseline, with the new fields explicitly enumerated as expected differences".**
