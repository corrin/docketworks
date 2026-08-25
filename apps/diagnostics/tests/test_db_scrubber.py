"""Guarantees of the production-dump scrubber.

The full pipeline (pg_dump | pg_restore, scrub, re-dump) only runs against a
real second database on the production host; what is testable here is the
safety refusal, the configuration contracts the consumer-side verifier
depends on, and the anonymisation behaviour of the individual scrub steps —
those take the pytest database as a stand-in for the restored copy by
repointing ``SCRUB_ALIAS`` at ``default``.
"""

import uuid
from datetime import UTC, date, datetime

import django.apps
import pytest
from faker import Faker
from pytest_django.fixtures import SettingsWrapper

from apps.accounting.models import Bill, CreditNote, Invoice, Quote
from apps.accounts.models import SYSTEM_AUTOMATION_EMAIL, Staff
from apps.accounts.nonprod_credentials import STAFF_PASSWORD
from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.tests.job_fixtures import (
    make_bill,
    make_credit_note,
    make_invoice,
    make_job,
    make_quote,
)
from apps.core.models import CompanyDefaults, ServiceAPIKey
from apps.crm.tests.helpers import make_company
from apps.diagnostics.services import db_scrubber
from apps.diagnostics.services.staff_anonymization import create_staff_profile
from apps.process.models import Acknowledgement, Form, FormEntry, Procedure, ProcessEvent
from scripts.ops.verify_scrubbed_backup import PRIVATE_CONFIG_TABLES


class TestScrubAliasSafety:
    def test_refuses_when_no_scrub_alias_is_configured(self, settings: SettingsWrapper) -> None:
        settings.DATABASES = {
            key: value for key, value in settings.DATABASES.items() if key != "scrub"
        }
        with pytest.raises(RuntimeError, match="SCRUB_DB_NAME"):
            db_scrubber._assert_scrub_alias_is_safe()


class TestScrubConfigContracts:
    def test_private_tables_match_the_verifier(self) -> None:
        # The scrubber empties these tables and the verifier fails an archive
        # where any holds a row; the two lists ARE the credential-stripping
        # contract and must never drift apart.
        assert set(db_scrubber._PRIVATE_CONFIG_TABLES) == set(PRIVATE_CONFIG_TABLES)

    def test_every_private_table_is_truncated(self) -> None:
        assert set(db_scrubber._PRIVATE_CONFIG_TABLES) <= set(db_scrubber._EXCLUDED_TABLES)

    def test_every_excluded_table_is_a_real_table(self) -> None:
        # A renamed model would otherwise turn TRUNCATE into a runtime error
        # on the production host — or worse, silently stop excluding a table
        # that still exists under the old name in the restored dump.
        model_tables = {
            model._meta.db_table for model in django.apps.apps.get_models(include_auto_created=True)
        }
        missing = set(db_scrubber._EXCLUDED_TABLES) - model_tables
        assert not missing, f"Excluded tables with no backing model: {sorted(missing)}"

    def test_pay_items_are_not_truncated(self) -> None:
        # TRUNCATE ... CASCADE ignores on_delete=PROTECT: wiping xeropayitem
        # would cascade through Job.default_xero_pay_item and erase every Job.
        assert "workflow_xeropayitem" not in db_scrubber._EXCLUDED_TABLES

    def test_every_raw_json_accounting_model_gets_its_contact_scrubbed(self) -> None:
        # Job-linked rows survive the unlinked-delete, so any accounting model
        # carrying raw_json ships its Xero contact block in the dump unless it
        # is in the contact-scrub tuple. v1 omitted Quote and leaked real
        # customer names; this pin makes the next document model fail loudly
        # instead of joining the leak.
        raw_json_models = {
            model
            for model in django.apps.apps.get_app_config("accounting").get_models()
            if any(field.name == "raw_json" for field in model._meta.fields)
        }
        assert raw_json_models <= set(db_scrubber._CONTACT_SCRUB_MODELS)

    def test_every_crm_text_field_has_a_scrub_ruling(self) -> None:
        # A new free-text field on the contact models would otherwise ship its
        # content in every "scrubbed" dump — Company.address leaked exactly
        # this way, inherited from v1. Adding a field here means deciding:
        # scrub it in _scrub_companies, or record below why it is not PII.
        scrubbed = {
            (Company, "name"),
            (Company, "email"),
            (Company, "address"),
            (Company, "raw_json"),
            (Person, "name"),
            (Person, "email"),
            (CompanyPersonLink, "notes"),
            (ContactMethod, "value"),
            (ContactMethod, "normalized_value"),
            (ContactMethod, "label"),
        }
        not_pii = {
            (Company, "xero_contact_id"),  # Xero GUID
            (Company, "xero_tenant_id"),  # Xero GUID
            (Company, "xero_merged_into_id"),  # Xero GUID
            (CompanyPersonLink, "position"),  # job title, not an identity
            (ContactMethod, "method_type"),  # enum
            (ContactMethod, "source"),  # enum
        }
        text_types = ("CharField", "TextField", "JSONField")
        text_fields = {
            (model, field.name)
            for model in (Company, Person, CompanyPersonLink, ContactMethod)
            for field in model._meta.fields
            if field.get_internal_type() in text_types
        }
        unaccounted = {(model.__name__, name) for model, name in text_fields - scrubbed - not_pii}
        assert not unaccounted, f"CRM text fields with no scrub ruling: {sorted(unaccounted)}"

    def test_every_process_text_field_has_a_scrub_ruling(self) -> None:
        # A prose exemption with no gate is how the pay-slip leak happened
        # (ADR 0050): every text/JSON field on a process model is either
        # scrubbed or has a recorded reason it carries no PII.
        #
        # FormEntry.data is schema-driven, not a flat text field — its
        # text/textarea VALUES are redacted per-key in
        # _scrub_process_entries — but the field as a whole is still listed
        # here as "scrubbed" so a future free-text FormEntry column cannot
        # ride this pin unaccounted for.
        scrubbed = {
            (FormEntry, "data"),
            (Procedure, "site_location"),
            (ProcessEvent, "delta_before"),
            (ProcessEvent, "delta_after"),
            (ProcessEvent, "detail"),
        }
        not_pii = {
            (Form, "document_type"),  # enum
            (Form, "category"),  # enum
            (Form, "title"),  # document/template title, not a person's name
            (Form, "document_number"),  # internal numbering
            (Form, "tags"),  # free-text category tags, not an identity
            (Form, "status"),  # enum
            (Form, "form_schema"),  # field key/label/type structure, not user data
            (Procedure, "document_type"),  # enum
            (Procedure, "category"),  # enum
            (Procedure, "title"),  # document title, not a person's name
            (Procedure, "document_number"),  # internal numbering
            (Procedure, "tags"),  # free-text category tags, not an identity
            (Procedure, "status"),  # enum
            (Procedure, "google_doc_id"),  # Google Docs id, not PII
            (Procedure, "google_doc_url"),  # Google Docs URL, not free text
            (ProcessEvent, "event_type"),  # internal event-type key, not user text
        }
        # Acknowledgement carries no free text at all — staff/form/procedure
        # are id-only FKs and acknowledged_at is a timestamp — but it is
        # listed here anyway so a later free-text field on it cannot ride
        # this pin unaccounted for either.
        text_types = ("CharField", "TextField", "JSONField", "URLField")
        text_fields = {
            (model, field.name)
            for model in (Acknowledgement, Form, FormEntry, Procedure, ProcessEvent)
            for field in model._meta.fields
            if field.get_internal_type() in text_types
        }
        unaccounted = {(model.__name__, name) for model, name in text_fields - scrubbed - not_pii}
        assert not unaccounted, f"process text fields with no scrub ruling: {sorted(unaccounted)}"


class TestStaffProfiles:
    def test_profiles_are_coherent(self) -> None:
        for _ in range(200):
            profile = create_staff_profile()
            assert profile["first_name"]
            assert profile["last_name"]
            assert profile["email"].endswith("@example.com")
            assert profile["preferred_name"] is None or profile["preferred_name"]


class TestValidatedRawJson:
    def test_returns_the_payload_unchanged(self) -> None:
        payload: dict[str, object] = {"_contact": {"_name": "Real Customer"}}
        assert db_scrubber._validated_raw_json(payload, "Invoice 1") is payload

    def test_null_means_nothing_to_scrub(self) -> None:
        assert db_scrubber._validated_raw_json(None, "Invoice 1") is None

    def test_refuses_a_non_object_payload(self) -> None:
        # Coercing to {} instead would let the row's PII paths survive the
        # scrub unvisited.
        with pytest.raises(TypeError, match=r"Invoice 42.*list"):
            db_scrubber._validated_raw_json(["not", "an", "object"], "Invoice 42")


@pytest.fixture
def _scrub_the_test_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the scrubber at the pytest DB, standing in for the restored copy."""
    monkeypatch.setattr(db_scrubber, "SCRUB_ALIAS", "default")


@pytest.mark.django_db
@pytest.mark.usefixtures("_scrub_the_test_database")
class TestScrubAccountingContacts:
    def test_contact_name_and_email_are_replaced_and_nothing_else(self) -> None:
        company = make_company("Contact Co")
        quote = make_quote(company)
        quote.raw_json = {
            "_contact": {
                "_name": "Real Customer Ltd",
                "_email_address": "accounts@realcustomer.example",
                "_contact_id": "abc-123",
            },
            "_reference": "Job 55 balustrade",
            "_line_items": [{"_description": "Balustrade"}],
        }
        quote.save(update_fields=["raw_json"])

        db_scrubber._scrub_accounting_contacts()

        quote.refresh_from_db()
        contact = quote.raw_json["_contact"]
        assert contact["_name"] != "Real Customer Ltd"
        assert contact["_email_address"] != "accounts@realcustomer.example"
        assert contact["_contact_id"] == "abc-123"
        assert quote.raw_json["_reference"] == "Job 55 balustrade"
        assert quote.raw_json["_line_items"] == [{"_description": "Balustrade"}]

    def test_rows_without_a_contact_block_are_untouched(self) -> None:
        company = make_company("No Contact Co")
        invoice = make_invoice(company)  # raw_json == {}
        quote = make_quote(company)  # raw_json is NULL

        db_scrubber._scrub_accounting_contacts()

        invoice.refresh_from_db()
        quote.refresh_from_db()
        assert invoice.raw_json == {}
        assert quote.raw_json is None

    def test_a_malformed_raw_json_stops_the_run(self) -> None:
        company = make_company("Broken Co")
        quote = make_quote(company)
        Quote.objects.filter(pk=quote.pk).update(raw_json=["broken"])

        with pytest.raises(TypeError, match="Quote"):
            db_scrubber._scrub_accounting_contacts()


@pytest.mark.django_db
@pytest.mark.usefixtures("_scrub_the_test_database")
class TestScrubStaff:
    def test_identities_and_passwords_are_replaced_but_xero_links_survive(self) -> None:
        staff = Staff.objects.create_user(
            office_email="jane.real@customer-corp.example",
            password="real-password-1!",
            first_name="Jane",
            last_name="Real",
            preferred_name="Janey",
            xero_user_id=str(uuid.uuid4()),
        )
        original_password = staff.password
        original_xero_user_id = staff.xero_user_id

        db_scrubber._scrub_staff()

        staff.refresh_from_db()
        assert staff.office_email != "jane.real@customer-corp.example"
        assert staff.office_email.endswith("@example.com")
        assert staff.first_name
        assert staff.last_name
        # The production hash must not survive into the archive: the runbook's
        # reset happens after the file has already been copied off the host.
        # This test asserted the opposite until 2026-08-15.
        assert staff.password != original_password
        assert staff.check_password(STAFF_PASSWORD)
        assert staff.password_needs_reset is True
        # xero_user_id is the marker the seed's employees phase re-reads.
        assert staff.xero_user_id == original_xero_user_id

    def test_no_staff_row_keeps_a_production_password(self) -> None:
        # The whole-table guarantee, not one row: a future carve-out that
        # skips somebody has to fail here.
        originals = {}
        for index in range(3):
            person = Staff.objects.create_user(
                office_email=f"real{index}@customer-corp.example",
                password=f"real-password-{index}!",
                first_name="Real",
                last_name=f"Person{index}",
            )
            originals[person.pk] = person.password

        db_scrubber._scrub_staff()

        for pk, original in originals.items():
            assert Staff.objects.get(pk=pk).password != original
        # Including the system account, which is excluded from the identity
        # scrub but must never keep a usable production password.
        automation = Staff.objects.get(office_email=SYSTEM_AUTOMATION_EMAIL)
        assert not automation.has_usable_password()

    def test_the_system_automation_identity_is_preserved(self) -> None:
        # The row exists from the data migration; downstream consumers look
        # it up by canonical email, so the scrub must leave it alone.
        automation = Staff.objects.get(office_email=SYSTEM_AUTOMATION_EMAIL)
        original_first_name = automation.first_name

        db_scrubber._scrub_staff()

        automation.refresh_from_db()
        assert automation.office_email == SYSTEM_AUTOMATION_EMAIL
        assert automation.first_name == original_first_name

    def test_scrubbed_emails_are_unique(self) -> None:
        for index in range(4):
            Staff.objects.create_user(
                office_email=f"real-{index}@customer-corp.example",
                password="pw-1!",
                first_name="Real",
                last_name=f"Person{index}",
            )

        db_scrubber._scrub_staff()

        emails = list(Staff.objects.values_list("office_email", flat=True))
        assert len(emails) == len(set(emails))


@pytest.mark.django_db
@pytest.mark.usefixtures("_scrub_the_test_database")
class TestScrubPaySlips:
    @staticmethod
    def _make_slip(employee_id: uuid.UUID, employee_name: str) -> uuid.UUID:
        # Registry lookups (and pk/values_list access below): xero is a
        # sibling integration app the layer contract bars from static import.
        pay_run_model = django.apps.apps.get_model("xero", "XeroPayRun")
        pay_slip_model = django.apps.apps.get_model("xero", "XeroPaySlip")
        pay_run = pay_run_model._default_manager.create(
            xero_id=uuid.uuid4(),
            xero_tenant_id="tenant-1",
            period_start_date=date(2026, 5, 3),
            period_end_date=date(2026, 5, 9),
            payment_date=date(2026, 5, 9),
            pay_run_status="Posted",
            raw_json={},
            xero_last_modified=datetime(2026, 5, 13, tzinfo=UTC),
        )
        slip = pay_slip_model._default_manager.create(
            xero_id=uuid.uuid4(),
            xero_tenant_id="tenant-1",
            pay_run=pay_run,
            xero_employee_id=employee_id,
            employee_name=employee_name,
            raw_json={
                "_first_name": employee_name.split(maxsplit=1)[0],
                "_last_name": employee_name.split()[1],
                "_timesheet_earnings_lines": [{"_display_name": "Ordinary Time"}],
            },
            xero_last_modified=datetime(2026, 5, 13, tzinfo=UTC),
        )
        slip_pk: uuid.UUID = slip.pk
        return slip_pk

    @staticmethod
    def _read_slip(slip_pk: uuid.UUID) -> tuple[str, dict[str, object]]:
        pay_slip_model = django.apps.apps.get_model("xero", "XeroPaySlip")
        name, raw_json = pay_slip_model._default_manager.values_list(
            "employee_name", "raw_json"
        ).get(pk=slip_pk)
        assert isinstance(name, str)
        assert isinstance(raw_json, dict)
        return name, raw_json

    def test_linked_slip_takes_the_scrubbed_staff_name(self) -> None:
        # The preserved xero_user_id joins the slip back to its Staff row, so
        # a real employee_name here would reverse the staff anonymisation.
        staff = Staff.objects.create_user(
            office_email="jane.real@customer-corp.example",
            password="pw-1!",
            first_name="Jane",
            last_name="Real",
            xero_user_id=str(uuid.uuid4()),
        )
        assert staff.xero_user_id is not None
        slip_pk = self._make_slip(uuid.UUID(staff.xero_user_id), "Jane Real")

        db_scrubber._scrub_staff()
        db_scrubber._scrub_payslips()

        staff.refresh_from_db()
        name, raw_json = self._read_slip(slip_pk)
        assert name == f"{staff.first_name} {staff.last_name}"
        assert "Real" not in name
        assert raw_json["_first_name"] == staff.first_name
        assert raw_json["_last_name"] == staff.last_name
        # Earnings lines survive: the timesheet repair commands read them.
        assert raw_json["_timesheet_earnings_lines"] == [{"_display_name": "Ordinary Time"}]

    def test_unlinked_slip_gets_a_generated_name(self) -> None:
        slip_pk = self._make_slip(uuid.uuid4(), "Departed Real")

        db_scrubber._scrub_payslips()

        name, raw_json = self._read_slip(slip_pk)
        assert name != "Departed Real"
        assert raw_json["_first_name"] != "Departed"
        assert raw_json["_last_name"] != "Real"


@pytest.mark.django_db
@pytest.mark.usefixtures("_scrub_the_test_database")
class TestScrubCompanies:
    def test_companies_people_and_contact_methods_are_anonymised(self) -> None:
        company = make_company("Real Customer Ltd")
        Company.objects.filter(pk=company.pk).update(
            email="info@realcustomer.example",
            address="12 Real Street\nPenrose\nAuckland 1061",
            raw_json={
                "_name": "Real Customer Ltd",
                "_email_address": "info@realcustomer.example",
                "_bank_account_details": "12-3456-7890123-00",
                "_phones": [{"_phone_number": "+6421555123"}],
                "_batch_payments": {
                    "_bank_account_number": "12-3456-7890123-00",
                    "_bank_account_name": "Real Customer Ltd",
                },
                "_addresses": [
                    {
                        "_address_line1": "12 Real Street",
                        "_city": "Auckland",
                        "_attention_to": "Real Person",
                    }
                ],
                "_contact_id": "abc-123",
            },
        )
        person = Person.objects.create(name="Real Person", email="real.person@example.org")
        link = CompanyPersonLink.objects.create(
            company=company, person=person, notes="Mates with the owner; call after 3pm"
        )
        phone = ContactMethod.objects.create(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
            label="Real Person's mobile",
        )

        db_scrubber._scrub_companies()

        company.refresh_from_db()
        assert company.name != "Real Customer Ltd"
        assert company.email != "info@realcustomer.example"
        assert company.address is not None
        assert "Real Street" not in company.address
        raw_json = company.raw_json
        assert raw_json is not None
        # The snapshot's _name must track the anonymised company name.
        assert raw_json["_name"] == company.name
        assert raw_json["_email_address"] != "info@realcustomer.example"
        assert raw_json["_bank_account_details"] != "12-3456-7890123-00"
        assert raw_json["_phones"][0]["_phone_number"] != "+6421555123"
        assert raw_json["_batch_payments"]["_bank_account_number"] != "12-3456-7890123-00"
        assert raw_json["_batch_payments"]["_bank_account_name"] != "Real Customer Ltd"
        assert raw_json["_addresses"][0]["_address_line1"] != "12 Real Street"
        assert raw_json["_addresses"][0]["_attention_to"] != "Real Person"
        # City stays: coarse, non-identifying shape the seed and tests rely on.
        assert raw_json["_addresses"][0]["_city"] == "Auckland"
        assert raw_json["_contact_id"] == "abc-123"
        person.refresh_from_db()
        assert person.name != "Real Person"
        assert person.email != "real.person@example.org"
        link.refresh_from_db()
        assert link.notes != "Mates with the owner; call after 3pm"
        phone.refresh_from_db()
        assert phone.value != "021 555 123"
        assert phone.label != "Real Person's mobile"
        assert phone.normalized_value == ContactMethod.normalize_value(
            ContactMethod.MethodType.PHONE, phone.value
        )

    def test_a_generated_name_never_collides_with_a_preserved_name(self) -> None:
        # A company renamed TO a preserved name would slip through the
        # notes/contact-method scrubs' company__name__in=preserved exclusions
        # and ship its real data — so the uniqueness set is seeded with the
        # preserved names, forcing the generator past the collision.
        shop_name = CompanyDefaults.objects.get().shop_company.name
        company = make_company("Collision Target Ltd")

        class CollidingFaker(Faker):
            def __init__(self) -> None:
                super().__init__()
                self._company_names = iter([shop_name, "Unique Replacement Co"])

            def company(self) -> str:
                return next(self._company_names)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(db_scrubber, "Faker", CollidingFaker)
            db_scrubber._scrub_companies()

        company.refresh_from_db()
        assert company.name == "Unique Replacement Co"

    def test_the_shop_company_keeps_its_name_and_contact_methods(self) -> None:
        shop = CompanyDefaults.objects.get().shop_company
        original_name = shop.name
        shop_phone = ContactMethod.objects.create(
            company=shop,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 636 5131",
        )

        db_scrubber._scrub_companies()

        shop.refresh_from_db()
        assert shop.name == original_name
        shop_phone.refresh_from_db()
        assert shop_phone.value == "09 636 5131"


def _incident_form(*, form_schema: dict[str, object]) -> Form:
    return Form.objects.create(
        document_type="form",
        category=Form.Category.INCIDENT,
        title="Incident Report",
        form_schema=form_schema,
    )


@pytest.mark.django_db
@pytest.mark.usefixtures("_scrub_the_test_database")
class TestScrubProcedures:
    def test_site_location_is_anonymised(self) -> None:
        procedure = Procedure.objects.create(
            document_type="procedure",
            category=Procedure.Category.SAFETY,
            title="Site Safety SOP",
            site_location="12 Real Street, Penrose, Auckland",
        )

        db_scrubber._scrub_procedures()

        procedure.refresh_from_db()
        assert procedure.site_location != "12 Real Street, Penrose, Auckland"

    def test_a_procedure_with_no_site_location_is_left_alone(self) -> None:
        procedure = Procedure.objects.create(
            document_type="reference", category=Procedure.Category.REFERENCE, title="Reference Doc"
        )

        db_scrubber._scrub_procedures()

        procedure.refresh_from_db()
        assert procedure.site_location is None


@pytest.mark.django_db
@pytest.mark.usefixtures("_scrub_the_test_database")
class TestScrubProcessEntries:
    def test_text_and_textarea_values_are_replaced_but_structured_values_survive(self) -> None:
        form = _incident_form(
            form_schema={
                "fields": [
                    {"key": "witness", "label": "Witness account", "type": "textarea"},
                    {"key": "summary", "label": "Summary", "type": "text"},
                    {
                        "key": "severity",
                        "label": "Severity",
                        "type": "select",
                        "options": ["low", "high"],
                    },
                    {"key": "occurred_on", "label": "Occurred on", "type": "date"},
                ]
            }
        )
        entry = FormEntry.objects.create(
            form=form,
            entry_date="2026-08-25",
            data={
                "witness": "Jane Smith saw the forklift tip over",
                "summary": "Forklift incident, minor injury to Jane Smith",
                "severity": "high",
                "occurred_on": "2026-08-25",
            },
        )

        db_scrubber._scrub_process_entries()

        entry.refresh_from_db()
        assert entry.data["witness"] == db_scrubber._TEXT_SCRUB_TOKEN
        assert entry.data["summary"] == db_scrubber._TEXT_SCRUB_TOKEN
        assert entry.data["severity"] == "high"
        assert entry.data["occurred_on"] == "2026-08-25"

    def test_an_unparseable_form_schema_wipes_the_entry_data_and_is_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        form = _incident_form(form_schema={"not_fields": []})
        entry = FormEntry.objects.create(
            form=form, entry_date="2026-08-25", data={"anything": "Real witness name here"}
        )

        with caplog.at_level("WARNING"):
            db_scrubber._scrub_process_entries()

        entry.refresh_from_db()
        assert entry.data == {}
        assert "1 form entries whose form schema would not parse" in caplog.text

    def test_an_entry_with_empty_data_is_left_alone(self) -> None:
        form = _incident_form(
            form_schema={"fields": [{"key": "witness", "label": "Witness", "type": "textarea"}]}
        )
        entry = FormEntry.objects.create(form=form, entry_date="2026-08-25", data={})

        db_scrubber._scrub_process_entries()

        entry.refresh_from_db()
        assert entry.data == {}

    def test_a_conforming_select_value_survives(self) -> None:
        form = _incident_form(
            form_schema={
                "fields": [
                    {
                        "key": "severity",
                        "label": "Severity",
                        "type": "select",
                        "options": ["low", "high"],
                    }
                ]
            }
        )
        entry = FormEntry.objects.create(
            form=form, entry_date="2026-08-25", data={"severity": "high"}
        )

        db_scrubber._scrub_process_entries()

        entry.refresh_from_db()
        assert entry.data["severity"] == "high"

    def test_free_text_in_a_select_field_is_redacted(self) -> None:
        # v1 accepted arbitrary JSON into FormEntry.data, so a restored row
        # can hold free text under a key the CURRENT schema types as select —
        # a value that is not one of the field's options is not a select
        # value at all, so it must not survive the scrub unredacted.
        form = _incident_form(
            form_schema={
                "fields": [
                    {
                        "key": "severity",
                        "label": "Severity",
                        "type": "select",
                        "options": ["low", "high"],
                    }
                ]
            }
        )
        entry = FormEntry.objects.create(
            form=form,
            entry_date="2026-08-25",
            data={"severity": "Jane Smith saw the forklift tip over"},
        )

        db_scrubber._scrub_process_entries()

        entry.refresh_from_db()
        assert entry.data["severity"] == db_scrubber._TEXT_SCRUB_TOKEN

    def test_a_key_absent_from_the_current_schema_is_redacted_not_kept(self) -> None:
        # A key an older schema version declared, since dropped or retyped,
        # is unaudited free text that would otherwise ride an unrelated
        # field's type check straight past the scrub — keeping it is the
        # unsafe default, so an unmatched key is redacted like free text,
        # not passed through like a matched structural field.
        form = _incident_form(
            form_schema={
                "fields": [
                    {
                        "key": "severity",
                        "label": "Severity",
                        "type": "select",
                        "options": ["low", "high"],
                    }
                ]
            }
        )
        entry = FormEntry.objects.create(
            form=form,
            entry_date="2026-08-25",
            data={"severity": "high", "old_witness_notes": "Jane Smith saw the forklift tip over"},
        )

        db_scrubber._scrub_process_entries()

        entry.refresh_from_db()
        assert entry.data["severity"] == "high"
        assert entry.data["old_witness_notes"] == db_scrubber._TEXT_SCRUB_TOKEN


@pytest.mark.django_db
@pytest.mark.usefixtures("_scrub_the_test_database")
class TestScrubProcessEvents:
    def test_deltas_are_nulled_and_changed_values_are_replaced(self, office_staff: Staff) -> None:
        form = _incident_form(
            form_schema={"fields": [{"key": "witness", "label": "Witness", "type": "textarea"}]}
        )
        entry = FormEntry.objects.create(form=form, entry_date="2026-08-25", data={})
        event = ProcessEvent.objects.create(
            form=form,
            form_entry=entry,
            staff=office_staff,
            event_type="entry_created",
            delta_before={"witness": ""},
            delta_after={"witness": "Jane Smith saw the forklift tip over"},
            detail={
                "changes": [
                    {
                        "field_name": "witness",
                        "old_value": "",
                        "new_value": "Jane Smith saw the forklift tip over",
                    }
                ]
            },
        )

        db_scrubber._scrub_process_events()

        event.refresh_from_db()
        assert event.delta_before is None
        assert event.delta_after is None
        change = event.detail["changes"][0]
        assert change["field_name"] == "witness"
        assert change["old_value"] == db_scrubber._TEXT_SCRUB_TOKEN
        assert change["new_value"] == db_scrubber._TEXT_SCRUB_TOKEN

    def test_an_event_with_no_changes_is_left_alone(self, office_staff: Staff) -> None:
        form = _incident_form(form_schema={"fields": []})
        event = ProcessEvent.objects.create(
            form=form,
            staff=office_staff,
            event_type="form_created",
        )

        db_scrubber._scrub_process_events()

        event.refresh_from_db()
        assert event.delta_before is None
        assert event.delta_after is None
        assert event.detail == {}

    def test_a_malformed_changes_value_is_replaced_with_an_empty_list(
        self, office_staff: Staff
    ) -> None:
        # A non-list `changes` cannot be redacted field-by-field, and passing
        # it through unredacted would ship whatever content it holds in a
        # "scrubbed" dump — scrub-by-default collapses it instead.
        form = _incident_form(form_schema={"fields": []})
        event = ProcessEvent.objects.create(
            form=form, staff=office_staff, event_type="form_updated", detail={"changes": "junk"}
        )

        db_scrubber._scrub_process_events()

        event.refresh_from_db()
        assert event.detail == {"changes": []}


@pytest.mark.django_db
@pytest.mark.usefixtures("_scrub_the_test_database")
class TestDeleteUnlinkedAccounting:
    def test_only_job_linked_invoices_and_quotes_survive(self) -> None:
        company = make_company("Docs Co")
        creator = Staff.objects.create_user(
            office_email="creator@example.com", password="pw-1!", first_name="Crea", last_name="Tor"
        )
        job = make_job(company, creator)
        linked_invoice = make_invoice(company, job=job)
        make_invoice(company)
        linked_quote = make_quote(company, job=job)
        make_quote(company)
        make_bill(company)
        make_credit_note(company)

        db_scrubber._delete_unlinked_accounting()

        assert set(Invoice.objects.values_list("pk", flat=True)) == {linked_invoice.pk}
        assert set(Quote.objects.values_list("pk", flat=True)) == {linked_quote.pk}
        assert not Bill.objects.exists()
        assert not CreditNote.objects.exists()


@pytest.mark.django_db
@pytest.mark.usefixtures("_scrub_the_test_database")
class TestPrivateConfigRemoval:
    def test_truncation_empties_the_credential_tables_and_the_check_passes(self) -> None:
        ServiceAPIKey.objects.create(name="Chatbot Service")

        db_scrubber._truncate_excluded_tables()
        db_scrubber._assert_private_config_removed()

        assert not ServiceAPIKey.objects.exists()

    def test_surviving_credentials_fail_closed(self) -> None:
        db_scrubber._truncate_excluded_tables()
        ServiceAPIKey.objects.create(name="Chatbot Service")

        with pytest.raises(RuntimeError, match="workflow_serviceapikey=1"):
            db_scrubber._assert_private_config_removed()
