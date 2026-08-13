"""set_company_fields / sync_xero_phone_methods: the raw_json consumers.

Business risks pinned here: a malformed Xero payload must never silently
un-archive a company or re-open it for jobs; Xero owns a phone number's
existence while the CRM user owns its label and primary flag; and a phone
conflict must fail the company's sync atomically rather than half-apply it.
"""

from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks

from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.core.models import AppError
from apps.crm.models import PhoneCallRecord
from apps.crm.services.phone_call_service import rematch_calls_for_numbers
from apps.xero.raw_fields import set_company_fields, sync_xero_phone_methods

from .xero_fixtures import make_contact_raw_json


def _company_with_phone(
    name: str,
    number: str = "021 555 123",
    phone_type: str = "DEFAULT",
) -> Company:
    return Company.objects.create(
        name=name,
        xero_last_modified=timezone.now(),
        raw_json={
            "_contact_status": "ACTIVE",
            "_name": name,
            "_phones": [
                {
                    "_phone_type": phone_type,
                    "_phone_number": number,
                    "_phone_area_code": "",
                    "_phone_country_code": "",
                }
            ],
        },
    )


@pytest.mark.django_db
class TestSetCompanyFieldsRejectsBadPayloads:
    def test_empty_raw_json_raises(self) -> None:
        # v2 deviation from v1 (ledgered): v1 invented "Unnamed Company" here.
        # A company without raw_json on this path is a sync defect — fail it
        # rather than fabricate data (ADR 0015).
        company = Company.objects.create(name="No Payload Ltd", xero_last_modified=timezone.now())

        with pytest.raises(ValueError, match="raw_json"):
            set_company_fields(company)

        company.refresh_from_db()
        assert company.name == "No Payload Ltd"

    def test_missing_status_fails_rather_than_unarchiving(self) -> None:
        # A payload with no _contact_status must not be guessed as ACTIVE —
        # that would un-archive the company and re-open it for jobs.
        malformed = make_contact_raw_json("contact-r1", "Malformed Status Ltd")
        del malformed["_contact_status"]
        company = Company.objects.create(
            name="Malformed Status Ltd",
            xero_last_modified=timezone.now(),
            allow_jobs=False,
            xero_archived=True,
            raw_json=malformed,
        )

        with pytest.raises(ValueError, match="_contact_status"):
            set_company_fields(company)

        company.refresh_from_db()
        assert company.xero_archived
        assert not company.allow_jobs

    def test_gdprrequest_status_fails_rather_than_reenabling_jobs(self) -> None:
        # GDPRREQUEST is unhandled: treating an erased contact as active
        # would re-enable jobs for it. It must fail loudly instead.
        company = Company.objects.create(
            name="GDPR Erased Ltd",
            xero_last_modified=timezone.now(),
            allow_jobs=False,
            xero_archived=True,
            raw_json=make_contact_raw_json("contact-r2", "GDPR Erased Ltd", status="GDPRREQUEST"),
        )

        with pytest.raises(ValueError, match="_contact_status"):
            set_company_fields(company)

        company.refresh_from_db()
        assert company.xero_archived
        assert not company.allow_jobs


@pytest.mark.django_db
class TestPersonIdentityOwnership:
    def test_contact_person_payload_does_not_create_or_update_people(self) -> None:
        # Xero reads must not undo DocketWorks-owned Person cleanup.
        raw_json = make_contact_raw_json("contact-p1", "Acme")
        raw_json["_contact_persons"] = [
            {
                "_first_name": "Jane",
                "_last_name": "Smith",
                "_email_address": "xero@example.com",
            }
        ]
        company = Company.objects.create(
            name="Acme", xero_last_modified=timezone.now(), raw_json=raw_json
        )
        person = Person.objects.create(
            name="Jane Smith", email="local@example.com", is_active=False
        )
        link = CompanyPersonLink.objects.create(company=company, person=person, is_active=False)

        set_company_fields(company)

        person.refresh_from_db()
        link.refresh_from_db()
        assert Person.objects.count() == 1
        assert person.email == "local@example.com"
        assert not person.is_active
        assert not link.is_active


@pytest.mark.django_db
class TestPhoneMethodSync:
    """Xero owns a number's existence; the CRM user owns label/is_primary."""

    def test_duplicate_phone_owner_crashes_sync_with_named_owners(self) -> None:
        """The raised error names both companies and the number (ADR 0038).

        Persistence lives one level up in set_company_fields, AFTER its
        rollback — a row written here inside the caller's atomic block would
        vanish with the rollback (ledgered v1 fix).
        """
        existing = Company.objects.create(
            name="Existing Phone Owner", xero_last_modified=timezone.now()
        )
        imported = _company_with_phone("Imported Phone Owner")
        ContactMethod.objects.create(
            company=existing,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
        )

        with pytest.raises(ValidationError) as excinfo:
            sync_xero_phone_methods(imported)

        message = str(excinfo.value)
        assert "Imported Phone Owner" in message
        assert "+6421555123" in message
        assert "Existing Phone Owner" in message

    def test_phone_conflict_rolls_back_company_but_persists_the_app_error(self) -> None:
        # The company save and its phone sync are one atomic unit: a conflict
        # must not leave the company's fields updated without its numbers.
        # The AppError recording WHY must survive that rollback — it is
        # persisted after the atomic block unwinds (ledgered v1 fix: v1 wrote
        # it inside the block and lost it).
        existing = Company.objects.create(
            name="Existing Phone Owner", xero_last_modified=timezone.now()
        )
        ContactMethod.objects.create(
            company=existing,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        company = _company_with_phone("Original Name Ltd")
        assert company.raw_json is not None
        company.raw_json["_name"] = "Renamed By Xero Ltd"
        company.save()
        before = AppError.objects.count()

        with pytest.raises(ValidationError, match="already belongs to"):
            set_company_fields(company)

        company.refresh_from_db()
        assert company.name == "Original Name Ltd"
        assert AppError.objects.count() == before + 1
        app_error = AppError.objects.order_by("-timestamp").first()
        assert app_error is not None
        assert "Existing Phone Owner" in app_error.message
        assert "+6421555123" in app_error.message

    def test_merged_company_phones_are_not_synced(self) -> None:
        # A merged company's archived Xero contact keeps its phones, but they
        # now belong to the winner — syncing must skip, not collide.
        winner = Company.objects.create(name="Winner", xero_last_modified=timezone.now())
        ContactMethod.objects.create(
            company=winner,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        merged = _company_with_phone("Merged Loser")
        merged.merged_into = winner
        merged.save()
        before = AppError.objects.count()

        created = sync_xero_phone_methods(merged)  # must not raise

        assert created == []
        assert ContactMethod.objects.filter(company=merged).count() == 0
        assert AppError.objects.count() == before

    def test_resync_of_existing_number_is_grandfathered(self) -> None:
        # Re-syncing a company's own already-stored number must not raise.
        owner = _company_with_phone("Phone Owner")
        # A cross-company legacy row exists for the same number (grandfathered),
        # inserted bypassing the save guard as pre-guard data was.
        other = Company.objects.create(name="Legacy Other Owner", xero_last_modified=timezone.now())
        legacy = ContactMethod(
            company=other,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        legacy.normalized_value = ContactMethod.normalize_phone("021 555 123")
        ContactMethod.objects.bulk_create([legacy])
        # The owner already stores the number too (its own row).
        owner_method = ContactMethod(
            company=owner,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        owner_method.normalized_value = ContactMethod.normalize_phone("021 555 123")
        ContactMethod.objects.bulk_create([owner_method])

        created = sync_xero_phone_methods(owner)  # must not raise

        assert created == []
        owner_method.refresh_from_db()
        # Xero owns the number's existence only; the existing row is untouched.
        assert owner_method.label is None

    def test_user_edited_label_and_primary_survive_resync(self) -> None:
        owner = _company_with_phone("Phone Owner")
        created = sync_xero_phone_methods(owner)
        assert created == ["+6421555123"]
        imported_method = ContactMethod.objects.get(company=owner)
        assert imported_method.label == "DEFAULT"
        assert imported_method.is_primary

        # CRM user relabels the imported number and picks a LOCAL primary.
        imported_method.label = "Reception"
        imported_method.save()
        local_primary = ContactMethod.objects.create(
            company=owner,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 000",
            label="After hours",
            is_primary=True,
            source=ContactMethod.Source.LOCAL,
        )

        assert sync_xero_phone_methods(owner) == []

        imported_method.refresh_from_db()
        local_primary.refresh_from_db()
        assert imported_method.label == "Reception"
        assert not imported_method.is_primary
        assert local_primary.is_primary
        assert imported_method.source == ContactMethod.Source.IMPORTED

    def test_unchanged_resync_does_not_write_the_method_row(self) -> None:
        owner = _company_with_phone("Phone Owner")
        sync_xero_phone_methods(owner)
        method = ContactMethod.objects.get(company=owner)
        updated_at_before = method.updated_at

        with CaptureQueriesContext(connection) as ctx:
            sync_xero_phone_methods(owner)

        writes = [
            query["sql"] for query in ctx.captured_queries if not query["sql"].startswith("SELECT")
        ]
        assert writes == []
        method.refresh_from_db()
        assert method.updated_at == updated_at_before

    def test_explicit_null_phone_parts_do_not_leak_the_string_none(self) -> None:
        # Xero JSON often carries explicit nulls for unset optional parts; the
        # stored value must stay clean rather than embedding a literal "None".
        company = Company.objects.create(
            name="Null Parts Ltd",
            xero_last_modified=timezone.now(),
            raw_json={
                "_contact_status": "ACTIVE",
                "_name": "Null Parts Ltd",
                "_phones": [
                    {
                        "_phone_type": "DEFAULT",
                        "_phone_number": "5551234",
                        "_phone_area_code": None,
                        "_phone_country_code": None,
                    }
                ],
            },
        )

        sync_xero_phone_methods(company)

        method = ContactMethod.objects.get(company=company)
        assert method.value == "5551234"
        assert "None" not in method.value


@pytest.mark.django_db
class TestPhoneRematchDispatch:
    def test_new_xero_number_dispatches_rematch_of_historical_calls(
        self, django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks
    ) -> None:
        # Numbers imported from Xero must attach existing calls, like UI edits.
        company = _company_with_phone("Rematch Company")
        call_datetime = timezone.now()
        call = PhoneCallRecord.objects.create(
            provider_call_id="account:xero-rematch",
            account_code="account",
            call_datetime=call_datetime,
            call_date=timezone.localdate(),
            call_time=call_datetime.time(),
            origin="+6421555123",
            destination="+6490000000",
            raw_json={"id": "xero-rematch"},
        )
        with (
            patch(
                "apps.crm.tasks.rematch_phone_calls_task.delay",
                side_effect=rematch_calls_for_numbers,
            ) as rematch,
            django_capture_on_commit_callbacks(execute=True),
        ):
            set_company_fields(company)

        rematch.assert_called_once_with(["+6421555123"])
        call.refresh_from_db()
        assert call.company_id == company.id

        # An unchanged re-sync creates nothing and must not dispatch a rematch.
        # Asserted through the dispatch rather than by requiring an empty
        # callback list: a Company save also registers the data-version
        # publish (apps/operations/push.py), which is not this test's subject.
        with (
            patch(
                "apps.crm.tasks.rematch_phone_calls_task.delay",
                side_effect=rematch_calls_for_numbers,
            ) as unchanged_rematch,
            django_capture_on_commit_callbacks(execute=True),
        ):
            set_company_fields(company)

        unchanged_rematch.assert_not_called()
