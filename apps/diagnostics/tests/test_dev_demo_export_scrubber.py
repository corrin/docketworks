"""Execution tests for the dev-demo export scrub policy.

The policy normally runs against the scratch ``scrub`` alias, which test
settings deliberately drop; every function takes ``using``, so the pytest
database stands in for the restored copy.

``_redact_phone_provider_settings`` must clear credentials with NULL, never
"": the columns carry not-blank CHECK constraints (ADR 0040), so a "" write
raises IntegrityError on any dev DB whose solo row exists — which is every
real one. The row-present test below pins that.
"""

import uuid
from datetime import UTC, date, datetime

import pytest
from django.apps import apps as django_apps
from django.contrib.sessions.models import Session
from django.utils import timezone
from django.utils.connection import ConnectionDoesNotExist

from apps.core.models import AppError, ServiceAPIKey
from apps.crm.models import (
    PhoneCallRecord,
    PhoneCallRecording,
    PhoneEndpoint,
    PhoneProviderSettings,
)
from apps.crm.tests.helpers import make_call, make_company, make_recording
from apps.diagnostics.services.dev_demo_export_scrubber import (
    _redact_payroll_payloads,
    _redact_phone_calls,
    _redact_phone_endpoints,
    _redact_phone_provider_settings,
    _stable_label,
    _truncate_existing_tables,
    scrub_dev_demo_export,
)
from apps.quoting.models import SupplierCredential
from scripts.ops.verify_scrubbed_backup import PRIVATE_CONFIG_TABLES

pytestmark = pytest.mark.django_db

ORIGIN = "+6421555123"
DESTINATION = "+6496365131"


def _make_scrubbable_call(provider_id: str = "call-1") -> PhoneCallRecord:
    """A call carrying every party field the scrub must pseudonymise."""
    call = make_call(provider_id, origin=ORIGIN, destination=DESTINATION)
    PhoneCallRecord.objects.filter(pk=call.pk).update(
        normalized_origin=ORIGIN,
        normalized_destination=DESTINATION,
        description="Customer rang about the balustrade job",
        our_number=DESTINATION,
        external_number=ORIGIN,
    )
    call.refresh_from_db()
    return call


class TestStableLabel:
    def test_nothing_to_redact_yields_the_empty_string(self) -> None:
        assert _stable_label(None, "demo-number") == ""
        assert _stable_label("", "demo-number") == ""

    def test_labels_are_stable_prefixed_and_distinct(self) -> None:
        first = _stable_label(ORIGIN, "demo-number")
        assert first == _stable_label(ORIGIN, "demo-number")
        assert first.startswith("demo-number-")
        assert first != _stable_label(DESTINATION, "demo-number")


class TestRedactPhoneCalls:
    def test_normalized_origin_and_destination_are_scrubbed(self) -> None:
        # v1's demo scrubber left normalized_origin/normalized_destination
        # intact, shipping real numbers in a "scrubbed" dump. v2 pins the
        # fix: dropping either column from the redaction fails here.
        call = _make_scrubbable_call()

        result = _redact_phone_calls("default")

        assert result.rows == 1
        call.refresh_from_db()
        assert call.normalized_origin is not None
        assert call.normalized_origin != ORIGIN
        assert call.normalized_origin.startswith("demo-number-")
        assert call.normalized_destination is not None
        assert call.normalized_destination != DESTINATION
        assert call.normalized_destination.startswith("demo-number-")

    def test_every_party_field_is_pseudonymised_and_payloads_dropped(self) -> None:
        call = _make_scrubbable_call()

        _redact_phone_calls("default")

        call.refresh_from_db()
        for value, original in (
            (call.origin, ORIGIN),
            (call.destination, DESTINATION),
            (call.our_number, DESTINATION),
            (call.external_number, ORIGIN),
        ):
            assert value is not None
            assert value != original
            assert value.startswith("demo-number-")
        assert call.provider_call_id.startswith("demo-call-")
        assert call.account_code == "demo-account"
        assert call.description is None
        assert call.raw_json == {}

    def test_a_shared_number_keeps_the_same_pseudonym_across_calls(self) -> None:
        # Stable labels are the point: the demo warehouse must still join
        # calls by party even though the numbers are fake.
        first = _make_scrubbable_call("call-1")
        second = _make_scrubbable_call("call-2")

        _redact_phone_calls("default")

        first.refresh_from_db()
        second.refresh_from_db()
        assert first.normalized_origin == second.normalized_origin
        assert first.normalized_origin != first.normalized_destination


class TestRedactPhoneEndpoints:
    def test_numbers_and_provider_details_are_scrubbed(self) -> None:
        endpoint = PhoneEndpoint.objects.create(
            number=ORIGIN,
            normalized_number=ORIGIN,
            label="Main line",
            endpoint_type=PhoneEndpoint.EndpointType.MAIN_LINE,
            provider_account_code="acct-1",
            provider_metadata={"provider_id": "real-id"},
        )

        result = _redact_phone_endpoints("default")

        assert result.rows == 1
        endpoint.refresh_from_db()
        assert endpoint.number != ORIGIN
        assert endpoint.number.startswith("demo-endpoint-")
        assert endpoint.normalized_number.startswith("demo-endpoint-")
        assert endpoint.provider_account_code is None
        assert endpoint.provider_metadata == {}


class TestRedactPhoneProviderSettings:
    def test_an_existing_row_has_credentials_nulled_not_blanked(self) -> None:
        # "" would violate the not-blank CHECK constraints (ADR 0040) and
        # abort the export mid-pipeline on every real dev DB.
        PhoneProviderSettings.objects.create(
            downloads_enabled=True,
            recording_deletion_enabled=True,
            base_url="https://portal.example.com",
            username="real-user",
            password="real-pass",
            account_code="acct-1",
        )

        result = _redact_phone_provider_settings("default")

        assert result.rows == 1
        settings_row = PhoneProviderSettings.objects.get()
        assert settings_row.username is None
        assert settings_row.password is None
        assert settings_row.base_url is None
        assert settings_row.account_code is None
        assert settings_row.downloads_enabled is False
        assert settings_row.recording_deletion_enabled is False


class TestTruncateExistingTables:
    def test_tables_absent_from_the_database_are_skipped(self) -> None:
        assert _truncate_existing_tables("default", ("diagnostics_no_such_table",)) == []


class TestRedactPayrollPayloads:
    def test_pay_slip_employees_are_renamed_and_raw_payloads_dropped(self) -> None:
        # Registry lookups: xero is a sibling integration app (layer contract).
        pay_run_model = django_apps.get_model("xero", "XeroPayRun")
        pay_slip_model = django_apps.get_model("xero", "XeroPaySlip")
        pay_run = pay_run_model._default_manager.create(
            xero_id=uuid.uuid4(),
            xero_tenant_id="tenant-1",
            period_start_date=date(2026, 5, 3),
            period_end_date=date(2026, 5, 9),
            payment_date=date(2026, 5, 9),
            pay_run_status="Posted",
            raw_json={"_pay_slips": ["real names"]},
            xero_last_modified=datetime(2026, 5, 13, tzinfo=UTC),
        )
        slips = [
            pay_slip_model._default_manager.create(
                xero_id=uuid.uuid4(),
                xero_tenant_id="tenant-1",
                pay_run=pay_run,
                xero_employee_id=uuid.uuid4(),
                employee_name=name,
                raw_json={"_earnings_lines": ["real amounts"]},
                xero_last_modified=datetime(2026, 5, 13, tzinfo=UTC),
            )
            for name in ("Jane Real", "Joe Real")
        ]

        results = _redact_payroll_payloads("default")

        assert {result.name: result.rows for result in results} == {
            "workflow_xeropayrun": 1,
            "workflow_xeropayslip": 2,
        }
        pay_run.refresh_from_db()
        assert pay_run.raw_json == {}
        renamed: set[str] = set()
        for slip in slips:
            slip.refresh_from_db()
            assert slip.raw_json == {}
            renamed.add(slip.employee_name)
        assert renamed == {"Demo Employee 001", "Demo Employee 002"}


class TestScrubDevDemoExport:
    def test_credentials_identifiers_and_operational_rows_are_scrubbed(self) -> None:
        Session.objects.create(
            session_key="demo-session",
            session_data="real-session-payload",
            expire_date=timezone.now(),
        )
        call = _make_scrubbable_call()
        make_recording(call, "rec-1", storage_path="recordings/rec-1.mp3")
        api_key = ServiceAPIKey.objects.create(name="Chatbot Service")
        original_key = api_key.key
        error = AppError.objects.create(
            message="Traceback naming a real customer",
            data={"customer": "Real Customer Ltd"},
        )

        results = scrub_dev_demo_export(using="default")

        by_name = {result.name: result.rows for result in results}
        assert by_name["django_session"] == 1
        assert Session.objects.count() == 0
        assert by_name["crm_phonecallrecord"] == 1
        assert by_name["crm_phonecallrecording"] == 1
        assert not PhoneCallRecording.objects.exists()
        api_key.refresh_from_db()
        assert api_key.key != original_key
        assert api_key.key.startswith("redacted-key-")
        assert api_key.last_used is None
        error.refresh_from_db()
        assert error.message == "Redacted for dev demo export"
        assert error.data == {}
        call.refresh_from_db()
        assert call.raw_json == {}
        assert call.description is None
        # Zero-row tables still report: the policy visibly covers every
        # credential table even when the source has nothing in it.
        assert by_name["workflow_xeroapp"] == 0
        assert by_name["workflow_aiprovider"] == 0
        assert by_name["crm_phoneprovidersettings"] == 0
        # Every credential table the backup verifier requires empty must be
        # covered by a demo-export redaction too — the two policies protect
        # the same secrets through different pipelines, and SupplierCredential
        # drifted out of this one until 2026-08-15.
        assert set(PRIVATE_CONFIG_TABLES) <= set(by_name)

    def test_supplier_credentials_lose_their_secrets_but_stay_joinable(self) -> None:
        supplier = make_company("Scraper Supplier Ltd")
        credential = SupplierCredential.objects.create(
            supplier=supplier,
            label="portal",
            credential_type=SupplierCredential.CredentialType.OAUTH2,
            username="real-login",
            password="real-password",
            api_key="real-key",
            extra_config={"client_secret": "real-oauth-secret"},
        )

        scrub_dev_demo_export(using="default")

        credential.refresh_from_db()
        assert credential.username is None
        assert credential.password is None
        assert credential.api_key is None
        assert credential.extra_config == {}
        assert credential.label == "portal"
        assert credential.supplier_id == supplier.pk

    def test_an_unexpected_failure_is_persisted_and_reraised(self) -> None:
        with pytest.raises(ConnectionDoesNotExist):
            scrub_dev_demo_export(using="no-such-alias")

        error = AppError.objects.get()
        assert "no-such-alias" in error.message
