"""Guarantees of the production-dump scrubber.

The full pipeline (pg_dump | pg_restore, scrub, re-dump) only runs against a
real second database on the production host; what is testable here is the
safety refusal, the configuration contracts the consumer-side verifier
depends on, and the anonymisation behaviour of the individual scrub steps —
those take the pytest database as a stand-in for the restored copy by
repointing ``SCRUB_ALIAS`` at ``default``.
"""

import uuid

import django.apps
import pytest
from pytest_django.fixtures import SettingsWrapper

from apps.accounting.models import Bill, CreditNote, Invoice, Quote
from apps.accounts.models import SYSTEM_AUTOMATION_EMAIL, Staff
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
from scripts.ops.verify_scrubbed_backup import PRIVATE_CONFIG_TABLES


class TestScrubAliasSafety:
    def test_refuses_when_no_scrub_alias_is_configured(self, settings: SettingsWrapper) -> None:
        settings.DATABASES = {
            key: value for key, value in settings.DATABASES.items() if key != "scrub"
        }
        with pytest.raises(RuntimeError, match="SCRUB_DB_NAME"):
            db_scrubber._assert_scrub_alias_is_safe()

    def test_refuses_a_name_not_ending_in_scrub(self, settings: SettingsWrapper) -> None:
        settings.DATABASES = {
            **settings.DATABASES,
            "scrub": {"NAME": "dw_msm_prod"},
        }
        with pytest.raises(RuntimeError, match="_scrub"):
            db_scrubber._assert_scrub_alias_is_safe()

    def test_refuses_an_empty_name(self, settings: SettingsWrapper) -> None:
        settings.DATABASES = {
            **settings.DATABASES,
            "scrub": {"NAME": ""},
        }
        with pytest.raises(RuntimeError, match="_scrub"):
            db_scrubber._assert_scrub_alias_is_safe()

    def test_accepts_a_scrub_suffixed_name(self, settings: SettingsWrapper) -> None:
        settings.DATABASES = {
            **settings.DATABASES,
            "scrub": {"NAME": "dw_msm_prod_scrub"},
        }
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
    def test_identities_are_replaced_but_login_and_xero_links_survive(self) -> None:
        staff = Staff.objects.create_user(
            email="jane.real@customer-corp.example",
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
        assert staff.email != "jane.real@customer-corp.example"
        assert staff.email.endswith("@example.com")
        assert staff.first_name
        assert staff.last_name
        # Recorded v1 behaviour: the restore runbook resets passwords, and
        # xero_user_id is the marker the seed's employees phase re-reads.
        assert staff.password == original_password
        assert staff.xero_user_id == original_xero_user_id

    def test_the_system_automation_identity_is_preserved(self) -> None:
        # The row exists from the data migration; downstream consumers look
        # it up by canonical email, so the scrub must leave it alone.
        automation = Staff.objects.get(email=SYSTEM_AUTOMATION_EMAIL)
        original_first_name = automation.first_name

        db_scrubber._scrub_staff()

        automation.refresh_from_db()
        assert automation.email == SYSTEM_AUTOMATION_EMAIL
        assert automation.first_name == original_first_name

    def test_scrubbed_emails_are_unique(self) -> None:
        for index in range(4):
            Staff.objects.create_user(
                email=f"real-{index}@customer-corp.example",
                password="pw-1!",
                first_name="Real",
                last_name=f"Person{index}",
            )

        db_scrubber._scrub_staff()

        emails = list(Staff.objects.values_list("email", flat=True))
        assert len(emails) == len(set(emails))


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


@pytest.mark.django_db
@pytest.mark.usefixtures("_scrub_the_test_database")
class TestDeleteUnlinkedAccounting:
    def test_only_job_linked_invoices_and_quotes_survive(self) -> None:
        company = make_company("Docs Co")
        creator = Staff.objects.create_user(
            email="creator@example.com", password="pw-1!", first_name="Crea", last_name="Tor"
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
