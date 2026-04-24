---
status: draft
spec: docs/plans/2026-04-22-prod-to-dev-scrubbed-dump.md
---

# pg_dump-based backport refresh — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Django `dumpdata` + Faker + `loaddata` refresh path with native `pg_dump`/`pg_restore` via a prod-side scrub DB, so dev refreshes are 10–100× faster and the 23-step runbook collapses to ~7 steps. Unanonymised prod data never leaves the prod host.

**Architecture:** One management command (`manage.py backport_data_backup`, same name, rewritten internals) drives `pg_dump` prod → `pg_restore` into a pre-provisioned `dw_<client>_scrub` sibling DB → call `db_scrubber.scrub()` service (Django ORM on a second `scrub` DB alias) → `pg_dump` the scrubbed DB → ship the `.dump` to dev via rclone → delete the raw dump. Dev side is runbook-only: `pg_restore` + `migrate` + two fixture loads + xero reauth + validators. Because `pg_dump` includes the `django_migrations` table, `manage.py migrate` on dev naturally applies exactly the migrations dev is ahead by — no rewind hacks.

**Tech Stack:** Django 6, PostgreSQL 16, `pg_dump -Fc` / `pg_restore`, `subprocess.run`, Django multi-database ORM (`QuerySet.using("scrub")`), Django TransactionTestCase for multi-DB tests, `rclone`, Faker (reused for client/address noise), `apps/accounts/staff_anonymization.py` (reused unchanged).

---

## Scope check

Single subsystem: the refresh pipeline. No sub-projects. Ship as one plan.

## File structure

**Create:**
- `apps/workflow/services/db_scrubber.py` — one `scrub()` entry point plus one private helper per table group (staff, clients, jobs, accounting, purchasing, historical_and_tokens). All ORM writes via `.using("scrub")`, wrapped in a single `transaction.atomic(using="scrub")` block, fail-fast with `persist_app_error(exc)` + re-raise.
- `apps/workflow/tests/services/__init__.py` — empty package marker (regenerate via `python scripts/update_init.py`, do not hand-edit).
- `apps/workflow/tests/services/test_db_scrubber.py` — `TransactionTestCase` subclass with `databases = {"default", "scrub"}` and one test method per table group.
- `docs/plans/2026-04-25-pg-dump-backport-refresh-plan.md` — this plan.

**Modify:**
- `apps/workflow/management/commands/backport_data_backup.py` — full internal rewrite; keep the command name and `--analyze-fields` sub-mode untouched.
- `docketworks/settings.py` — add `scrub` DB alias below `default` at line ~403.
- `.env.example` — add `SCRUB_DB_NAME` near the other DB_* variables (line ~8).
- `docs/restore-prod-to-nonprod.md` — full rewrite for the new 7-step dev flow. Preserve the old runbook as an appendix labeled "legacy JSON path" for one release cycle.
- `scripts/cleanup_backups.py` — add `SCRUBBED_RE` pattern and `compute_scrubbed_keep()` with 30-day retention.
- `scripts/server/instance.sh` — provision and tear down the scrub DB alongside the main DB. Django's DB user has no `CREATEDB` privilege, so the postgres superuser (already sudoed in this script) must create it at instance-creation time.
- `scripts/server/templates/env-instance.template` — add `SCRUB_DB_NAME=__SCRUB_DB_NAME__` so every instance gets the env var populated.

**Reuse unchanged:**
- `apps/accounts/staff_anonymization.py` — `create_staff_profile()` / `NAME_PROFILES`.
- `scripts/restore_checks/*` — 13 post-restore validator scripts.
- `scripts/backup_db.sh`, `scripts/predeploy_backup.sh` — referenced patterns, not modified.

**Do NOT edit:** any `__init__.py` file directly — run `python scripts/update_init.py` after creating new modules.

---

## Task 1 — Add `scrub` DB alias to settings and `.env.example`

**Why first:** every subsequent task references `settings.DATABASES["scrub"]`. Must exist before `db_scrubber` can import Django or tests can run.

**Files:**
- Modify: `docketworks/settings.py:395-404`
- Modify: `.env.example:8-12`

- [ ] **Step 1.1 — Write the failing test**

Add a new file `apps/workflow/tests/test_scrub_db_alias.py`:

```python
from django.conf import settings
from django.test import SimpleTestCase


class ScrubDbAliasTests(SimpleTestCase):
    def test_scrub_alias_exists(self):
        self.assertIn("scrub", settings.DATABASES)

    def test_scrub_alias_shape_matches_default(self):
        default = settings.DATABASES["default"]
        scrub = settings.DATABASES["scrub"]
        self.assertEqual(scrub["ENGINE"], default["ENGINE"])
        self.assertEqual(scrub["USER"], default["USER"])
        self.assertEqual(scrub["PASSWORD"], default["PASSWORD"])
        self.assertEqual(scrub["HOST"], default["HOST"])
        self.assertEqual(scrub["PORT"], default["PORT"])

    def test_scrub_name_hard_fails_if_not_suffixed(self):
        # Guard against pointing scrub alias at prod by misconfiguration.
        self.assertTrue(
            settings.DATABASES["scrub"]["NAME"].endswith("_scrub"),
            "SCRUB_DB_NAME must end in '_scrub' to prevent scrubbing prod",
        )
```

- [ ] **Step 1.2 — Run the test, confirm it fails**

Run: `SCRUB_DB_NAME=dw_test_scrub python manage.py test apps.workflow.tests.test_scrub_db_alias -v 2`
Expected: `KeyError: 'scrub'` on `test_scrub_alias_exists`.

- [ ] **Step 1.3 — Add the alias to `docketworks/settings.py`**

Replace the `DATABASES = {...}` block (currently at `docketworks/settings.py:395-404`) with:

```python
DATABASES = {
    "default": {
        "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.postgresql"),
        "NAME": os.getenv("DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", ""),
    },
    # Second DB alias used ONLY by manage.py backport_data_backup on prod.
    # Points at a sibling scrubbing DB (dw_<client>_scrub) that holds a
    # temporary copy of prod restored via pg_restore. The db_scrubber service
    # anonymises in place here before re-dumping. Name MUST end in "_scrub"
    # — hard-checked by db_scrubber to prevent accidental scrubbing of prod.
    "scrub": {
        "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.postgresql"),
        "NAME": os.getenv("SCRUB_DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", ""),
    },
}
```

- [ ] **Step 1.4 — Add `SCRUB_DB_NAME` to `.env.example`**

Modify `.env.example:8-13`. Change from:

```
DB_NAME=dw_yourco_dev
DB_USER=dw_yourco_dev
DB_PASSWORD=your_secure_password_here
DB_HOST=/var/run/postgresql
DB_PORT=5432
TEST_DB_USER=dw_test
```

to:

```
DB_NAME=dw_yourco_dev
DB_USER=dw_yourco_dev
DB_PASSWORD=your_secure_password_here
DB_HOST=/var/run/postgresql
DB_PORT=5432
# Only used on prod by `manage.py backport_data_backup`. Must end in "_scrub".
# Provision once with: createdb dw_yourco_scrub -O dw_yourco_prod
SCRUB_DB_NAME=dw_yourco_scrub
TEST_DB_USER=dw_test
```

- [ ] **Step 1.5 — Run the test, confirm it passes**

Run: `python manage.py test apps.workflow.tests.test_scrub_db_alias -v 2`
Expected: `OK` (3 tests).

- [ ] **Step 1.6 — Commit**

```bash
git add docketworks/settings.py .env.example apps/workflow/tests/test_scrub_db_alias.py
git commit -m "feat(settings): add scrub DB alias for backport refresh pipeline"
```

---

## Task 2 — Scaffold `db_scrubber` service module and test file

Establishes the empty `scrub()` entry point, the test class wired for multi-DB, and the safety gate that refuses to run if the scrub alias points anywhere but a `_scrub` DB.

**Files:**
- Create: `apps/workflow/services/db_scrubber.py`
- Create: `apps/workflow/tests/services/test_db_scrubber.py`

- [ ] **Step 2.1 — Write failing tests for the safety gate and the empty entry point**

Create `apps/workflow/tests/services/test_db_scrubber.py`:

```python
from unittest import mock

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
        # Smoke: no tables scrubbed yet, just assert it returns without error
        # on an empty scrub DB (Django test runner creates test_<SCRUB_DB_NAME>).
        db_scrubber.scrub()
```

- [ ] **Step 2.2 — Run tests, confirm they fail**

Run: `python manage.py test apps.workflow.tests.services.test_db_scrubber -v 2`
Expected: `ModuleNotFoundError: No module named 'apps.workflow.services.db_scrubber'`.

- [ ] **Step 2.3 — Create the module with the safety gate and empty scrub()**

Create `apps/workflow/services/db_scrubber.py`:

```python
"""
Scrubs a restored copy of prod (in the `scrub` DB alias) of all PII.

Called by `manage.py backport_data_backup` AFTER `pg_restore` has loaded a
raw prod dump into `dw_<client>_scrub`. All writes use `.using("scrub")`
and run inside a single transaction so a partial failure leaves the scrub
DB in its pre-scrub state (the next run drops/recreates the schema anyway,
but consistency beats surprise).

Safety: refuses to run unless `settings.DATABASES["scrub"]["NAME"]` ends
in `_scrub`. This is the last line of defence against a misconfigured
SCRUB_DB_NAME pointing at prod.
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
    """Anonymise every PII-bearing table in the `scrub` DB alias.

    Runs as a single transaction. Persists and re-raises on any error.
    """
    _assert_scrub_alias_is_safe()
    try:
        with transaction.atomic(using=SCRUB_ALIAS):
            # Per-table operations added by subsequent tasks.
            pass
    except Exception as exc:
        persist_app_error(exc)
        raise
```

- [ ] **Step 2.4 — Regenerate `__init__.py` files**

Run: `python scripts/update_init.py`
Then: `git status apps/workflow/services/__init__.py apps/workflow/tests/services/__init__.py`
Expected: both files modified or created.

- [ ] **Step 2.5 — Run the tests, confirm they pass**

Django's test runner creates `test_<SCRUB_DB_NAME>` automatically — no pre-provisioning needed. If the runner errors with `permission denied to create database`, grant `CREATEDB` to the test DB user (same user that runs existing multi-DB tests).

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

## Task 3 — Scrub staff (`accounts_staff` + `accounts_historicalstaff`)

**Files:**
- Modify: `apps/workflow/services/db_scrubber.py`
- Modify: `apps/workflow/tests/services/test_db_scrubber.py`

- [ ] **Step 3.1 — Write the failing test**

Append to `apps/workflow/tests/services/test_db_scrubber.py`:

```python
from apps.accounts.models import Staff
from apps.workflow.services.db_scrubber import _scrub_staff


class ScrubStaffTests(TransactionTestCase):
    databases = {"default", "scrub"}

    def test_scrub_overwrites_identifying_fields(self):
        # Arrange: a staff row on the scrub DB mirroring prod shape.
        Staff.objects.using("scrub").create(
            email="real.person@morrissheetmetal.co.nz",
            first_name="Real",
            last_name="Person",
            preferred_name="Realperson",
            xero_user_id="aaaa1111-2222-3333-4444-555566667777",
            is_active=True,
        )

        _scrub_staff()

        row = Staff.objects.using("scrub").get()
        self.assertNotEqual(row.email, "real.person@morrissheetmetal.co.nz")
        self.assertNotEqual(row.first_name, "Real")
        self.assertNotEqual(row.last_name, "Person")
        self.assertIsNone(row.xero_user_id)
        self.assertTrue(row.email.endswith("@example.com"))
        # Password reset to an unusable placeholder
        self.assertFalse(row.has_usable_password())

    def test_scrub_fails_if_duplicate_generated_emails(self):
        # With enough retries the generator should always succeed for N staff.
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
        self.assertEqual(len(emails), 5, "Generated emails must be unique")
```

- [ ] **Step 3.2 — Run the test, confirm it fails**

Run: `python manage.py test apps.workflow.tests.services.test_db_scrubber.ScrubStaffTests -v 2`
Expected: `ImportError: cannot import name '_scrub_staff'`.

- [ ] **Step 3.3 — Implement `_scrub_staff`**

Add to `apps/workflow/services/db_scrubber.py` (above `scrub()`):

```python
from apps.accounts.models import Staff
from apps.accounts.staff_anonymization import create_staff_profile

_GENERATE_ATTEMPTS = 100


def _scrub_staff() -> None:
    """Overwrite identifying fields on every Staff row with a coherent profile.

    Xero user IDs are nulled — dev re-links via `seed_xero_from_database`.
    Passwords are reset to an unusable placeholder; `setup_dev_logins.py`
    resets them to the shared default on the dev side.
    """
    used_emails: set[str] = set()
    for staff in Staff.objects.using("scrub").all():
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
        staff.xero_user_id = None
        staff.set_unusable_password()
        staff.save(
            using=SCRUB_ALIAS,
            update_fields=[
                "email",
                "first_name",
                "last_name",
                "preferred_name",
                "xero_user_id",
                "password",
            ],
        )
```

Also update the `scrub()` body — replace the `pass` with:

```python
            _scrub_staff()
```

- [ ] **Step 3.4 — Run the tests, confirm they pass**

Run: `python manage.py test apps.workflow.tests.services.test_db_scrubber.ScrubStaffTests -v 2`
Expected: `OK` (2 tests).

- [ ] **Step 3.5 — Extend to `accounts_historicalstaff` (SimpleHistory mirror)**

Append to `test_db_scrubber.py`:

```python
class ScrubHistoricalStaffTests(TransactionTestCase):
    databases = {"default", "scrub"}

    def test_historical_staff_rows_match_anonymised_staff(self):
        from apps.accounts.models import HistoricalStaff

        s = Staff.objects.using("scrub").create(
            email="old@morrissheetmetal.co.nz",
            first_name="Old",
            last_name="Name",
            preferred_name=None,
            is_active=True,
        )
        # Write a historical row mirroring the pre-scrub state.
        HistoricalStaff.objects.using("scrub").create(
            id=s.id,
            history_date=s.date_joined,
            history_type="+",
            email="old@morrissheetmetal.co.nz",
            first_name="Old",
            last_name="Name",
            preferred_name=None,
            is_active=True,
        )

        _scrub_staff()

        # Every historical row for this staff must match the scrubbed current row.
        current = Staff.objects.using("scrub").get(id=s.id)
        histories = HistoricalStaff.objects.using("scrub").filter(id=s.id)
        for h in histories:
            self.assertEqual(h.email, current.email)
            self.assertEqual(h.first_name, current.first_name)
            self.assertEqual(h.last_name, current.last_name)
```

Run the failing test: expect rows on `HistoricalStaff` still have pre-scrub values.

Then extend `_scrub_staff()` to update the history table after each row:

```python
        # Rewrite every historical snapshot for this staff to match the new
        # profile. History rows carry their own copies of the fields.
        from apps.accounts.models import HistoricalStaff

        HistoricalStaff.objects.using(SCRUB_ALIAS).filter(id=staff.id).update(
            email=profile["email"],
            first_name=profile["first_name"],
            last_name=profile["last_name"],
            preferred_name=profile["preferred_name"],
        )
```

(Place inside the `for staff in ...` loop, after `staff.save(...)`.)

Re-run the test — expect `OK`.

- [ ] **Step 3.6 — Commit**

```bash
git add apps/workflow/services/db_scrubber.py \
        apps/workflow/tests/services/test_db_scrubber.py
git commit -m "feat(db_scrubber): scrub accounts_staff + historicalstaff"
```

---

## Task 4 — Scrub client tables (`client_client`, `client_clientcontact`, `client_supplierpickupaddress`)

Preserve the shop and test client names (allow-list from `CompanyDefaults` + scraper `SUPPLIER_NAME`). Anonymise everything else with Faker.

**Files:**
- Modify: `apps/workflow/services/db_scrubber.py`
- Modify: `apps/workflow/tests/services/test_db_scrubber.py`

- [ ] **Step 4.1 — Write the failing test**

Append to `test_db_scrubber.py`:

```python
from apps.client.models import Client, ClientContact, SupplierPickupAddress
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.db_scrubber import _scrub_clients


class ScrubClientsTests(TransactionTestCase):
    databases = {"default", "scrub"}

    def test_preserved_clients_are_not_touched(self):
        CompanyDefaults.objects.using("scrub").all().delete()
        CompanyDefaults.objects.using("scrub").create(
            id=1,
            shop_client_name="Shop Co",
            test_client_name="Test Client",
            company_name="Demo Co",
        )
        shop = Client.objects.using("scrub").create(
            name="Shop Co",
            email="shop@real.example",
            phone="+64 1 234",
        )
        Client.objects.using("scrub").create(
            name="Real Customer Ltd",
            email="bill@realcustomer.co.nz",
            phone="+64 9 876",
        )

        _scrub_clients()

        shop.refresh_from_db(using="scrub")
        other = Client.objects.using("scrub").exclude(name="Shop Co").get()
        self.assertEqual(shop.name, "Shop Co")
        self.assertEqual(shop.email, "shop@real.example")
        self.assertNotEqual(other.name, "Real Customer Ltd")
        self.assertNotEqual(other.email, "bill@realcustomer.co.nz")

    def test_raw_json_emptied(self):
        Client.objects.using("scrub").create(
            name="X Ltd", email="a@b.c", raw_json={"_email_address": "a@b.c"}
        )
        _scrub_clients()
        row = Client.objects.using("scrub").get()
        self.assertEqual(row.raw_json, {})

    def test_contact_and_pickup_address_anonymised(self):
        c = Client.objects.using("scrub").create(name="X Ltd", email="a@b.c")
        ClientContact.objects.using("scrub").create(
            client=c, name="Real Name", email="real@x.co", phone="123", position="Mgr"
        )
        SupplierPickupAddress.objects.using("scrub").create(
            client=c, address_line_1="1 Real St", notes="pickup after 5pm"
        )

        _scrub_clients()

        contact = ClientContact.objects.using("scrub").get()
        pickup = SupplierPickupAddress.objects.using("scrub").get()
        self.assertNotEqual(contact.name, "Real Name")
        self.assertNotEqual(contact.email, "real@x.co")
        self.assertNotEqual(pickup.address_line_1, "1 Real St")
        self.assertEqual(pickup.notes, "")
```

- [ ] **Step 4.2 — Run, confirm it fails**

Run: `python manage.py test apps.workflow.tests.services.test_db_scrubber.ScrubClientsTests -v 2`
Expected: `ImportError: cannot import name '_scrub_clients'`.

- [ ] **Step 4.3 — Implement `_scrub_clients`**

Add to `apps/workflow/services/db_scrubber.py`:

```python
from faker import Faker

from apps.client.models import Client, ClientContact, SupplierPickupAddress
from apps.workflow.models import CompanyDefaults


def _preserved_client_names() -> set[str]:
    """Names that must survive scrubbing: shop, test client, and scraper suppliers."""
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
    fake = Faker()
    preserved = _preserved_client_names()
    used_company_names: set[str] = set()

    for client in Client.objects.using(SCRUB_ALIAS).exclude(name__in=preserved):
        # Unique company name
        for _ in range(1000):
            candidate = fake.company()
            if candidate not in used_company_names:
                used_company_names.add(candidate)
                break
        else:
            raise RuntimeError("Failed to generate unique company name after 1000 attempts")

        client.name = candidate
        client.email = fake.email()
        client.phone = fake.phone_number()
        client.address = fake.street_address()
        client.primary_contact_name = fake.name()
        client.primary_contact_email = fake.email()
        client.raw_json = {}
        # Rewrite JSON arrays element-by-element if present.
        if isinstance(client.all_phones, list):
            client.all_phones = [fake.phone_number() for _ in client.all_phones]
        if isinstance(client.additional_contact_persons, list):
            client.additional_contact_persons = [
                {"name": fake.name(), "email": fake.email(), "phone": fake.phone_number()}
                for _ in client.additional_contact_persons
            ]
        client.save(using=SCRUB_ALIAS)

    for contact in ClientContact.objects.using(SCRUB_ALIAS).all():
        contact.name = fake.name()
        contact.email = fake.email()
        contact.phone = fake.phone_number()
        contact.position = fake.job()
        contact.notes = ""
        contact.save(using=SCRUB_ALIAS)

    for pickup in SupplierPickupAddress.objects.using(SCRUB_ALIAS).all():
        pickup.address_line_1 = fake.street_address()
        pickup.address_line_2 = ""
        pickup.city = fake.city()
        pickup.postcode = fake.postcode()
        pickup.notes = ""
        pickup.save(using=SCRUB_ALIAS)
```

Wire into `scrub()` body, after `_scrub_staff()`:

```python
            _scrub_clients()
```

- [ ] **Step 4.4 — Run tests, confirm they pass**

Run: `python manage.py test apps.workflow.tests.services.test_db_scrubber.ScrubClientsTests -v 2`
Expected: `OK` (3 tests).

- [ ] **Step 4.5 — Commit**

```bash
git add apps/workflow/services/db_scrubber.py \
        apps/workflow/tests/services/test_db_scrubber.py
git commit -m "feat(db_scrubber): scrub clients, contacts, supplier pickup addresses"
```

---

## Task 5 — Scrub jobs (`job_job`, `job_historicaljob`, `job_costline`). Leave `job_jobevent` untouched.

`job_jobevent` is **deliberately excluded** per spec's deferred decisions — an audit of `description`/`delta_before`/`delta_after`/`detail` happens in a follow-up ticket.

**Files:**
- Modify: `apps/workflow/services/db_scrubber.py`
- Modify: `apps/workflow/tests/services/test_db_scrubber.py`

- [ ] **Step 5.1 — Write the failing test**

Append:

```python
from apps.job.models import Job, CostSet, CostLine, JobEvent
from apps.workflow.services.db_scrubber import _scrub_jobs


class ScrubJobsTests(TransactionTestCase):
    databases = {"default", "scrub"}

    def _make_job(self, **kwargs):
        defaults = dict(name="Real Job", description="confidential scope", notes="pr ivate")
        defaults.update(kwargs)
        client = Client.objects.using("scrub").create(name="X Ltd", email="a@b.c")
        return Job.objects.using("scrub").create(client=client, **defaults)

    def test_job_notes_and_description_blanked(self):
        j = self._make_job()
        _scrub_jobs()
        j.refresh_from_db(using="scrub")
        self.assertEqual(j.notes, "")
        self.assertEqual(j.description, "")

    def test_costline_meta_note_and_comments_nulled(self):
        j = self._make_job()
        cs = CostSet.objects.using("scrub").create(job=j, kind="actual", rev=1)
        CostLine.objects.using("scrub").create(
            cost_set=cs,
            kind="time",
            desc="worked on confidential project X",
            meta={
                "staff_id": "aaaa1111-2222-3333-4444-555566667777",
                "is_billable": True,
                "note": "PII leak here",
                "comments": "and here",
            },
        )

        _scrub_jobs()

        cl = CostLine.objects.using("scrub").get()
        self.assertNotIn("PII leak", str(cl.meta))
        self.assertNotIn("here", str(cl.meta))
        self.assertEqual(cl.meta["staff_id"], "aaaa1111-2222-3333-4444-555566667777")
        self.assertTrue(cl.meta["is_billable"])

    def test_jobevent_left_untouched(self):
        j = self._make_job()
        JobEvent.objects.using("scrub").create(
            job=j,
            description="real event description",
            delta_before={"x": 1},
            delta_after={"x": 2},
        )

        _scrub_jobs()

        ev = JobEvent.objects.using("scrub").get()
        # Explicit: spec says do NOT scrub JobEvent yet. See deferred decisions.
        self.assertEqual(ev.description, "real event description")
```

- [ ] **Step 5.2 — Run, confirm it fails**

Run: `python manage.py test apps.workflow.tests.services.test_db_scrubber.ScrubJobsTests -v 2`
Expected: `ImportError: cannot import name '_scrub_jobs'`.

- [ ] **Step 5.3 — Implement `_scrub_jobs`**

Add to `apps/workflow/services/db_scrubber.py`:

```python
from apps.job.models import Job, CostLine, HistoricalJob


def _scrub_jobs() -> None:
    # Job + historical: blank notes and description.
    Job.objects.using(SCRUB_ALIAS).update(notes="", description="")
    HistoricalJob.objects.using(SCRUB_ALIAS).update(notes="", description="")

    # CostLine meta: null `note` and `comments`. Keep staff_id/is_billable.
    # Use a server-side JSONB update to avoid pulling every row into Python.
    from django.db import connections

    with connections[SCRUB_ALIAS].cursor() as cur:
        cur.execute(
            """
            UPDATE job_costline
               SET meta = meta
                          - 'note'
                          - 'comments'
              WHERE meta ? 'note' OR meta ? 'comments'
            """
        )
        # Blank `desc` on material lines that may embed client names.
        cur.execute(
            "UPDATE job_costline SET \"desc\" = '' WHERE kind = 'material'"
        )
    # JobEvent: deliberately untouched (see spec deferred decisions).
```

Wire into `scrub()` after `_scrub_clients()`.

- [ ] **Step 5.4 — Run tests, confirm they pass**

Run: `python manage.py test apps.workflow.tests.services.test_db_scrubber.ScrubJobsTests -v 2`
Expected: `OK` (3 tests).

- [ ] **Step 5.5 — Commit**

```bash
git add apps/workflow/services/db_scrubber.py \
        apps/workflow/tests/services/test_db_scrubber.py
git commit -m "feat(db_scrubber): scrub jobs, historicaljob, costline meta (leave jobevent)"
```

---

## Task 6 — Scrub accounting raw_json and line item descriptions

Covers `accounting_invoice`, `accounting_bill`, `accounting_creditnote`, and their line items.

**Files:**
- Modify: `apps/workflow/services/db_scrubber.py`
- Modify: `apps/workflow/tests/services/test_db_scrubber.py`

- [ ] **Step 6.1 — Write the failing test**

Append:

```python
from apps.accounting.models import (
    Invoice, InvoiceLineItem, Bill, BillLineItem, CreditNote, CreditNoteLineItem,
)
from apps.workflow.services.db_scrubber import _scrub_accounting


class ScrubAccountingTests(TransactionTestCase):
    databases = {"default", "scrub"}

    def test_raw_json_emptied_and_line_descriptions_blanked(self):
        inv = Invoice.objects.using("scrub").create(
            number="INV-001",
            total_excl_tax=100,
            raw_json={"_contact": {"_name": "Real Customer Ltd"}},
        )
        InvoiceLineItem.objects.using("scrub").create(
            invoice=inv, description="real line about client project"
        )

        _scrub_accounting()

        inv.refresh_from_db(using="scrub")
        li = InvoiceLineItem.objects.using("scrub").get()
        self.assertEqual(inv.raw_json, {})
        self.assertEqual(li.description, "")
        self.assertEqual(inv.total_excl_tax, 100)  # amounts preserved
```

- [ ] **Step 6.2 — Run, confirm it fails**

Expected: `ImportError: cannot import name '_scrub_accounting'`.

- [ ] **Step 6.3 — Implement `_scrub_accounting`**

```python
from apps.accounting.models import (
    Invoice,
    InvoiceLineItem,
    Bill,
    BillLineItem,
    CreditNote,
    CreditNoteLineItem,
)


def _scrub_accounting() -> None:
    # Null out Xero payloads on parent documents (amounts remain intact).
    for model in (Invoice, Bill, CreditNote):
        model.objects.using(SCRUB_ALIAS).update(raw_json={})

    # Blank free-text descriptions on line items.
    for model in (InvoiceLineItem, BillLineItem, CreditNoteLineItem):
        model.objects.using(SCRUB_ALIAS).update(description="")
```

Wire into `scrub()` after `_scrub_jobs()`.

- [ ] **Step 6.4 — Run tests, confirm they pass**

Run: `python manage.py test apps.workflow.tests.services.test_db_scrubber.ScrubAccountingTests -v 2`
Expected: `OK`.

- [ ] **Step 6.5 — Commit**

```bash
git add apps/workflow/services/db_scrubber.py \
        apps/workflow/tests/services/test_db_scrubber.py
git commit -m "feat(db_scrubber): blank accounting raw_json and line-item descriptions"
```

---

## Task 7 — Scrub purchasing raw_json and null Xero IDs

Covers `purchasing_purchaseorder` and `purchasing_stock`.

**Files:**
- Modify: `apps/workflow/services/db_scrubber.py`
- Modify: `apps/workflow/tests/services/test_db_scrubber.py`

- [ ] **Step 7.1 — Write the failing test**

Append:

```python
from apps.purchasing.models import PurchaseOrder, Stock
from apps.workflow.services.db_scrubber import _scrub_purchasing


class ScrubPurchasingTests(TransactionTestCase):
    databases = {"default", "scrub"}

    def test_purchase_order_raw_json_emptied(self):
        PurchaseOrder.objects.using("scrub").create(
            po_number="PO-1", raw_json={"_contact": {"_name": "Real Supplier"}}
        )
        _scrub_purchasing()
        po = PurchaseOrder.objects.using("scrub").get()
        self.assertEqual(po.raw_json, {})

    def test_stock_xero_id_nulled(self):
        Stock.objects.using("scrub").create(
            item_code="X", description="widget", xero_id="uuid-here"
        )
        _scrub_purchasing()
        s = Stock.objects.using("scrub").get()
        self.assertIsNone(s.xero_id)
```

- [ ] **Step 7.2 — Run, confirm it fails**

Expected: `ImportError`.

- [ ] **Step 7.3 — Implement `_scrub_purchasing`**

```python
from apps.purchasing.models import PurchaseOrder, Stock


def _scrub_purchasing() -> None:
    PurchaseOrder.objects.using(SCRUB_ALIAS).update(raw_json={})
    Stock.objects.using(SCRUB_ALIAS).update(raw_json={}, xero_id=None)
```

Wire into `scrub()`.

- [ ] **Step 7.4 — Run tests, confirm they pass**

Expected: `OK`.

- [ ] **Step 7.5 — Commit**

```bash
git add apps/workflow/services/db_scrubber.py \
        apps/workflow/tests/services/test_db_scrubber.py
git commit -m "feat(db_scrubber): scrub purchasing raw_json and stock.xero_id"
```

---

## Task 8 — Truncate tokens and residual `*_historical*` tables

Secrets must never leave prod; historical tables are large and not needed on dev.

**Files:**
- Modify: `apps/workflow/services/db_scrubber.py`
- Modify: `apps/workflow/tests/services/test_db_scrubber.py`

- [ ] **Step 8.1 — Write the failing test**

```python
from apps.workflow.models import XeroToken, ServiceAPIKey
from apps.workflow.services.db_scrubber import _truncate_secrets_and_history


class TruncateTests(TransactionTestCase):
    databases = {"default", "scrub"}

    def test_tokens_truncated(self):
        XeroToken.objects.using("scrub").create(
            tenant_id="t", access_token="secret", refresh_token="secret"
        )
        ServiceAPIKey.objects.using("scrub").create(
            name="gemini", api_key="sk-real"
        )
        _truncate_secrets_and_history()
        self.assertEqual(XeroToken.objects.using("scrub").count(), 0)
        self.assertEqual(ServiceAPIKey.objects.using("scrub").count(), 0)
```

- [ ] **Step 8.2 — Run, confirm it fails**

Expected: `ImportError`.

- [ ] **Step 8.3 — Implement `_truncate_secrets_and_history`**

```python
def _truncate_secrets_and_history() -> None:
    """Drop all rows from secrets tables and residual *_historical* tables.

    Historical tables other than `historicalstaff` / `historicaljob` are not
    useful on dev; truncating keeps the dev DB slim and avoids shipping
    rows we never explicitly scrubbed.
    """
    from django.db import connections

    XeroToken.objects.using(SCRUB_ALIAS).all().delete()
    ServiceAPIKey.objects.using(SCRUB_ALIAS).all().delete()

    with connections[SCRUB_ALIAS].cursor() as cur:
        cur.execute(
            """
            SELECT tablename FROM pg_tables
             WHERE schemaname = 'public'
               AND tablename LIKE '%_historical%'
               AND tablename NOT IN (
                   'accounts_historicalstaff',
                   'job_historicaljob'
               )
            """
        )
        tables = [row[0] for row in cur.fetchall()]
        for t in tables:
            cur.execute(f'TRUNCATE TABLE "{t}" RESTART IDENTITY CASCADE')
```

Wire into `scrub()` as the final step before the `with transaction.atomic(...)` block closes.

- [ ] **Step 8.4 — Run tests, confirm they pass**

Expected: `OK`.

- [ ] **Step 8.5 — Commit**

```bash
git add apps/workflow/services/db_scrubber.py \
        apps/workflow/tests/services/test_db_scrubber.py
git commit -m "feat(db_scrubber): truncate tokens and residual historical tables"
```

---

## Task 9 — Rewrite `backport_data_backup` management command

Replaces the dumpdata/Faker/zip pipeline with subprocess-driven `pg_dump`/`pg_restore` + a call to `db_scrubber.scrub()`. Preserves the `--analyze-fields` mode (call-through, untouched).

**Files:**
- Modify: `apps/workflow/management/commands/backport_data_backup.py` (full rewrite of `handle()` and supporting helpers; keep `--analyze-fields` sub-mode).

- [ ] **Step 9.1 — Write the failing test for the command wiring**

Create `apps/workflow/tests/management/__init__.py` via `scripts/update_init.py` and `apps/workflow/tests/management/test_backport_data_backup.py`:

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

        # Expect at least: pg_dump (raw), psql drop-schema, pg_restore,
        # pg_dump (scrubbed), psql drop-schema, rclone copy.
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

- [ ] **Step 9.2 — Run, confirm the first test fails**

Run: `python manage.py test apps.workflow.tests.management.test_backport_data_backup -v 2`
Expected: `AssertionError: 'pg_restore' not found in cmds` (or similar) because the current implementation uses `dumpdata`.

- [ ] **Step 9.3 — Rewrite the command**

Replace the entire `Command` class body in `apps/workflow/management/commands/backport_data_backup.py` with the block below. The `--analyze-fields` mode and its helpers (`analyze_fields`, `collect_field_samples`, `cannot_be_pii`, `is_uuid_string`) are preserved by moving them into the new class verbatim — keep those methods as they are today. Only `handle()`, and the dump/scrub pipeline helpers, change.

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
            # Unchanged legacy sub-mode — same signature as before.
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
                ["pg_restore", "--no-owner", "--no-privileges",
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
            self._run(
                ["rclone", "copy", scrubbed_dump, options["rclone_target"]],
            )
            self.stdout.write(self.style.SUCCESS(
                f"Scrubbed dump written: {scrubbed_dump}"
            ))
        except Exception as exc:
            persist_app_error(exc)
            # Ensure the raw (unscrubbed) dump is never left on disk.
            if os.path.exists(raw_dump):
                os.remove(raw_dump)
            raise

    def _run(self, cmd, env=None):
        subprocess.run(cmd, check=True, env=env, capture_output=True, text=True)

    # ---------- Legacy analyze_fields sub-mode (unchanged) ----------
    # Keep the current analyze_fields, collect_field_samples, cannot_be_pii,
    # is_uuid_string methods as they are today.
```

Keep the `analyze_fields`, `collect_field_samples`, `cannot_be_pii`, and `is_uuid_string` methods from the current file verbatim below this comment — and their module-level imports (`uuid`, `json`, `collections.defaultdict`, `django.db.connection`). The `Faker` import, `_used_company_names` state, `PII_CONFIG` dict, `_anonymize_staff`, `_set_field_by_path`, `_get_replacement_value`, `_filter_unlinked_accounting_records`, `_get_preserved_client_names`, `anonymize_item`, `create_schema_backup`, `create_migrations_snapshot`, and `create_combined_zip` — all go away.

- [ ] **Step 9.4 — Run tests, confirm they pass**

Run: `python manage.py test apps.workflow.tests.management.test_backport_data_backup -v 2`
Expected: `OK` (2 tests).

- [ ] **Step 9.5 — Commit**

```bash
git add apps/workflow/management/commands/backport_data_backup.py \
        apps/workflow/tests/management/test_backport_data_backup.py \
        apps/workflow/tests/management/__init__.py
git commit -m "feat(backport_data_backup): rewrite to pg_dump+pg_restore+db_scrubber"
```

---

## Task 10 — Rewrite `docs/restore-prod-to-nonprod.md` for the new 7-step dev flow

Keep the existing document as appendix `## Appendix: Legacy JSON path (deprecated)` for one release cycle — do not delete it.

**Files:**
- Modify: `docs/restore-prod-to-nonprod.md`

- [ ] **Step 10.1 — Insert the new body above the current content**

Replace lines 1–34 of `docs/restore-prod-to-nonprod.md` (from top through the `## Prerequisites` section's extracted-zip paragraph) with the new header + 7-step flow:

```markdown
# Restore Production to Non-Production

Restore a production backup to any non-production environment (dev or server
instance). Assume venv active, `.env` loaded, in the project root.

The scrubbed dump is produced on prod by `manage.py backport_data_backup` and
lives as `restore/scrubbed_<env>_<ts>.dump` on prod and at
`gdrive:dw_backups/scrubbed_<env>_<ts>.dump` on the rclone target.

## CRITICAL: audit log

As with the legacy flow, log every command and its key output to
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
   pg_restore --no-owner --no-privileges \
     -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" \
     ./restore/scrubbed_prod_<ts>.dump
   ```

4. **Apply any dev-side migrations prod hasn't seen yet**

   The `django_migrations` table came across in the dump, so this only
   runs migrations that exist locally beyond the prod state.
   ```bash
   python manage.py migrate
   ```

5. **Reload dev-only fixtures**

   Company defaults (shipped demo branding) and AI provider rows are
   deliberately excluded from prod scrubbing (they contain dev API keys).
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

Optional (dev): run `python scripts/recreate_jobfiles.py` to materialise
dummy files for the JobFile records.
```

Then insert `## Appendix: Legacy JSON path (deprecated)` above the current `## Prerequisites` block so the existing content lives beneath it unchanged. Add a one-line note at the top of the appendix:

> Deprecated — retained for one release cycle while the pg_dump flow beds in.

- [ ] **Step 10.2 — Smoke-render check**

Run: `grep -n '^#' docs/restore-prod-to-nonprod.md | head -20`
Expected: new H1 at top, `## Steps` below, `## Appendix: Legacy JSON path (deprecated)` present.

- [ ] **Step 10.3 — Commit**

```bash
git add docs/restore-prod-to-nonprod.md
git commit -m "docs(restore): rewrite for pg_dump flow; keep legacy as appendix"
```

---

## Task 11 — Extend `scripts/cleanup_backups.py` with `scrubbed_*.dump` retention

30-day window, same pattern as predeploy.

**Files:**
- Modify: `scripts/cleanup_backups.py`

- [ ] **Step 11.1 — Write the failing test**

Create `scripts/test_cleanup_backups.py` (standalone, pure-Python; run with `python -m unittest`):

```python
import os
import sys
import tempfile
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

- [ ] **Step 11.2 — Run, confirm it fails**

Run: `python -m unittest scripts.test_cleanup_backups -v`
Expected: `AttributeError: module 'cleanup_backups' has no attribute 'SCRUBBED_RE'`.

- [ ] **Step 11.3 — Add the pattern and keep function**

Edit `scripts/cleanup_backups.py`:

1. Add to the regexes block (around line 23, near `PREDEPLOY_RE`):

```python
SCRUBBED_RE = re.compile(r"^scrubbed_[a-z]+_(\d{8}_\d{6})\.dump$")
SCRUBBED_RETENTION_DAYS = 30
```

2. Add a new function below `compute_predeploy_keep` (around line 103):

```python
def compute_scrubbed_keep(entries, now):
    """Keep scrubbed_*.dump files whose timestamp is within the retention window."""
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

3. Extend `classify()` (around line 48) to recognise the new kind:

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

4. Update `main()` to track a `scrubbed_entries` bucket, compute `scrubbed_keep`, and include both in the `managed` set before computing deletions. The diff inside `main()`:

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

    # ...
    scrubbed_keep = compute_scrubbed_keep(scrubbed_entries, now)

    managed = set(ts_dir_entries) | set(predeploy_entries) | set(scrubbed_entries)
    to_delete = sorted(managed - ts_dir_keep - predeploy_keep - scrubbed_keep)

    print("Keeping (ts_dir):", sorted(ts_dir_keep))
    print("Keeping (predeploy):", sorted(predeploy_keep))
    print("Keeping (scrubbed):", sorted(scrubbed_keep))
```

- [ ] **Step 11.4 — Run the test, confirm it passes**

Run: `python -m unittest scripts.test_cleanup_backups -v`
Expected: `OK` (2 tests).

- [ ] **Step 11.5 — Commit**

```bash
git add scripts/cleanup_backups.py scripts/test_cleanup_backups.py
git commit -m "feat(cleanup_backups): 30-day retention for scrubbed_*.dump"
```

---

## Task 12 — Provision the scrub DB through `instance.sh` (no out-of-band ops step)

**Why this task exists:** the Django DB user does not hold `CREATEDB` privilege, so `manage.py backport_data_backup` cannot create the scrub DB on first run. The existing `instance.sh` already runs as `sudo -u postgres` when provisioning the main DB — it is the correct place to also ensure the scrub DB exists, and to tear it down on `instance.sh destroy`. After this task ships, spinning up a new instance (or re-running `instance.sh create <env>` on an existing one, which is idempotent) is the only thing ops needs to do — no separate runbook step.

**Files:**
- Modify: `scripts/server/instance.sh`
- Modify: `scripts/server/templates/env-instance.template`
- Modify: `docs/restore-prod-to-nonprod.md` (short note referring ops to `instance.sh` for pre-existing instances).

- [ ] **Step 12.1 — Add `SCRUB_DB_NAME` to the env template**

Edit `scripts/server/templates/env-instance.template`, directly after `DB_PORT=`:

```
DB_NAME=__DB_NAME__
DB_USER=__DB_USER__
DB_PASSWORD=__DB_PASSWORD__
DB_HOST=/var/run/postgresql
DB_PORT=
SCRUB_DB_NAME=__SCRUB_DB_NAME__
```

- [ ] **Step 12.2 — Derive `SCRUB_DB_NAME` and substitute it in `instance.sh`**

In `scripts/server/instance.sh` at line 164 (where `DB_NAME` / `DB_USER` are derived), add one line:

```bash
    local DB_NAME="dw_${CLIENT}_${ENV}"
    local DB_USER="dw_${CLIENT}_${ENV}"
    local SCRUB_DB_NAME="dw_${CLIENT}_${ENV}_scrub"
```

Then in the `sed` substitution block around line 274, add:

```bash
            -e "s|__DB_NAME__|$DB_NAME|g" \
            -e "s|__DB_USER__|$DB_USER|g" \
            -e "s|__SCRUB_DB_NAME__|$SCRUB_DB_NAME|g" \
```

Replicate the same additions wherever else the template is rendered — search for `__DB_NAME__` in the script and mirror each site.

- [ ] **Step 12.3 — Provision the scrub DB in the postgres bootstrap block**

Extend the `sudo -u postgres psql <<EOSQL ... EOSQL` block at `instance.sh:308-322`. The existing main-DB creation stays verbatim. Append before `EOSQL`:

```sql
SELECT 'CREATE DATABASE "$SCRUB_DB_NAME" OWNER "$DB_USER"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$SCRUB_DB_NAME')\gexec
GRANT ALL PRIVILEGES ON DATABASE "$SCRUB_DB_NAME" TO "$DB_USER";
```

Also update the `log` line at the start of the block:

```bash
    log "Ensuring databases $DB_NAME and $SCRUB_DB_NAME and user $DB_USER exist..."
```

- [ ] **Step 12.4 — Drop the scrub DB on `destroy`**

Around line 524 the destroy path does:

```bash
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS \"$DB_NAME\";" || true
    sudo -u postgres psql -c "DROP ROLE IF EXISTS \"$DB_USER\";" || true
```

Insert between the two lines:

```bash
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS \"$SCRUB_DB_NAME\";" || true
```

And ensure `SCRUB_DB_NAME` is derived at the top of the destroy function (mirror of step 12.2).

- [ ] **Step 12.5 — Runbook note for legacy instances**

Add at the top of `docs/restore-prod-to-nonprod.md`, before `## CRITICAL: audit log`:

```markdown
## First-time setup (existing instances only)

New instances pick up the scrub DB automatically via `scripts/server/instance.sh`.
Existing instances provisioned before this change need a one-off `instance.sh create`
re-run (idempotent — it skips anything that already exists and only adds the scrub DB).
No separate `createdb` command is needed; do not invent one.
```

- [ ] **Step 12.6 — Smoke-check `instance.sh` shellcheck-clean**

Run: `shellcheck scripts/server/instance.sh`
Expected: the additions introduce no new warnings beyond the baseline output on `main`.

- [ ] **Step 12.7 — Commit**

```bash
git add scripts/server/instance.sh \
        scripts/server/templates/env-instance.template \
        docs/restore-prod-to-nonprod.md
git commit -m "feat(instance.sh): provision and tear down scrub DB alongside main DB"
```

---

## Task 13 — End-to-end UAT verification

- [ ] **Step 13.1 — Provision or refresh a UAT instance**

Run: `sudo scripts/server/instance.sh create uat-<name>` (or re-run on an existing UAT instance).
Expected: log shows `Ensuring databases dw_<name>_uat and dw_<name>_uat_scrub and user dw_<name>_uat exist...`

Verify: `sudo -u postgres psql -lqt | awk -F'|' '{print $1}' | grep _scrub` includes the new scrub DB.

- [ ] **Step 13.2 — End-to-end dry run on UAT**

On a UAT instance (not prod), run:

```bash
python manage.py backport_data_backup
```

Expected: exits 0. A file `restore/scrubbed_<env>_<ts>.dump` is created.

- [ ] **Step 13.3 — Leak check on the produced dump**

Pick a known prod client name and staff email domain and assert they do not appear anywhere in the dump stream:

```bash
DUMP=restore/scrubbed_<env>_<ts>.dump
pg_restore -a -f - "$DUMP" \
  | grep -iE '<known prod client name>|@morrissheetmetal\.co\.nz' \
  && { echo "LEAK DETECTED"; exit 1; } \
  || echo "No leaks found"
```

Expected: `No leaks found`.

- [ ] **Step 13.4 — Restore into the dev DB via the new runbook**

Follow the 7-step runbook using the produced dump. Record wall-clock at step 3 (`pg_restore`). Compare against the legacy JSON path runbook's step 5 (`loaddata`): target ≥ 5× faster end-to-end.

- [ ] **Step 13.5 — Run the validators**

```bash
for s in scripts/restore_checks/check_*.py; do python "$s"; done
```

Expected: every script prints its expected output (see legacy runbook for the full list at steps 10–13).

No commit step — this task is verification only. If any check fails, stop and fix the underlying cause (do not add a workaround to the runbook).

---

## Spec coverage check

Mapping each spec deliverable to the task that implements it:

- Provision `dw_<client>_<env>_scrub` — **Task 12** (automated via `instance.sh`, no out-of-band ops step).
- `apps/workflow/services/db_scrubber.py` — **Tasks 2–8** (scaffold + per-table).
- Unit tests — **Tasks 2–8** (one test class per table group).
- Rewrite internals of `backport_data_backup.py` — **Task 9**.
- Add `scrub` DB alias + `.env.example` — **Task 1**.
- Rewrite `docs/restore-prod-to-nonprod.md` — **Task 10** (+ Task 12.5 for legacy-instance ops note).
- Extend `scripts/cleanup_backups.py` — **Task 11**.
- Spec deferred decisions (JobEvent untouched, commercial data in scope, no rename) — honoured in **Task 5** (leaves JobEvent) and **Task 6** (amounts preserved).

## Out of scope (explicit)

- Anonymising wage rates, invoice totals, supplier pricing (deferred — spec).
- Scrubbing `job_jobevent` (deferred — spec).
- Renaming the command away from `backport_data_backup` (deferred — spec).
- Granting `CREATEDB` to the Django DB user (conflicts with `feedback_db_reset_method.md`).

## Verification gates summary

1. Every task ends with a passing test run before commit.
2. Task 12.3 — grep leak check on the produced dump.
3. Task 12.4 — wall-clock regression check vs legacy path.
4. Task 12.5 — full `restore_checks/` validator suite green on the dev box.
