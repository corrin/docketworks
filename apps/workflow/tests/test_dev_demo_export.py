import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.crm.models import PhoneCallRecord, PhoneCallRecording
from apps.workflow.enums import AIProviderTypes
from apps.workflow.models import (
    AIProvider,
    AppError,
    CompanyDefaults,
    SearchTelemetryEvent,
    ServiceAPIKey,
    SessionReplayChunk,
    SessionReplayRecording,
    XeroApp,
    XeroPayRun,
    XeroPaySlip,
)
from apps.workflow.services.dev_demo_export_scrubber import (
    ScrubResult,
    scrub_dev_demo_export,
)


@pytest.mark.django_db
def test_dev_demo_scrub_preserves_business_signal_and_redacts_risk():
    staff = Staff.objects.create_user(
        email="demo.staff@example.test",
        password="password",
        first_name="Demo",
        last_name="Staff",
    )
    client = Client.objects.create(
        name="Realistic Client Ltd",
        email="client@example.test",
        phone="+64211234567",
        xero_last_modified=timezone.now(),
        raw_json={"_name": "Realistic Client Ltd"},
    )
    CompanyDefaults.objects.create(
        company_name="Demo Co",
        shop_client=client,
        phone_call_downloads_enabled=True,
        phone_provider_recording_deletion_enabled=True,
        phone_provider_base_url="https://phone.example.test",
        phone_provider_username="user",
        phone_provider_password="secret",
        phone_provider_account_code="acct",
        phone_own_numbers=["+6491234567"],
    )
    XeroApp.objects.create(
        label="Demo Xero",
        client_id="client-id",
        client_secret="secret",
        redirect_uri="https://example.test/callback",
        webhook_key="webhook",
        is_active=True,
        access_token="access",
        refresh_token="refresh",
    )
    AIProvider.objects.create(
        name="Gemini",
        api_key="ai-secret",
        default=True,
        model_name="gemini-test",
        provider_type=AIProviderTypes.GOOGLE,
    )
    service_key = ServiceAPIKey.objects.create(name="Warehouse", key="secret-key")

    now = timezone.now()
    today = timezone.localdate()
    call = PhoneCallRecord.objects.create(
        provider_call_id="acct:provider-id",
        account_code="acct",
        call_datetime=now,
        call_date=today,
        call_time=now.time(),
        call_type="Outbound",
        status="Answered",
        description="Sensitive call note",
        origin="+6491111111",
        destination="+64212222222",
        duration_seconds=180,
        charge=Decimal("1.2300"),
        client=client,
        raw_json={"phone": "+64212222222", "provider": "payload"},
    )
    PhoneCallRecording.objects.create(
        call=call,
        provider_recording_id="recording-id",
        account_code="acct",
        filename="call.mp3",
        storage_path="calls/call.mp3",
    )
    AppError.objects.create(
        message="Authorization Bearer secret",
        data={"access_token": "secret"},
        app="workflow",
        file="xero.py",
        function="sync",
        user_id=staff.id,
    )
    recording = SessionReplayRecording.objects.create(
        user=staff,
        initial_path="/clients?email=client@example.test",
        latest_path="/jobs/secret",
        user_agent="Browser",
    )
    SessionReplayChunk.objects.create(
        recording=recording,
        sequence=1,
        first_event_timestamp_ms=1,
        last_event_timestamp_ms=2,
        event_count=3,
        compressed_bytes=4,
        storage_path="session-replays/chunk.bin",
        sha256="abc",
        path="/jobs/secret",
    )
    SearchTelemetryEvent.objects.create(
        event_type=SearchTelemetryEvent.EventType.CLICK,
        domain=SearchTelemetryEvent.Domain.CLIENT,
        query="client@example.test",
        normalized_query="client@example.test",
        selected_result_id=str(client.id),
        selected_label="Realistic Client Ltd",
        metadata={"email": "client@example.test"},
    )
    pay_run = XeroPayRun.objects.create(
        xero_id=uuid.uuid4(),
        xero_tenant_id="tenant",
        period_start_date=today,
        period_end_date=today,
        payment_date=today,
        total_cost=Decimal("100.00"),
        total_pay=Decimal("80.00"),
        raw_json={"employee": "Real Name"},
        xero_last_modified=now,
    )
    XeroPaySlip.objects.create(
        xero_id=uuid.uuid4(),
        xero_tenant_id="tenant",
        pay_run=pay_run,
        xero_employee_id=uuid.uuid4(),
        employee_name="Real Employee",
        gross_earnings=Decimal("100.00"),
        tax_amount=Decimal("20.00"),
        net_pay=Decimal("80.00"),
        timesheet_hours=Decimal("8.00"),
        raw_json={"ird": "secret"},
        xero_last_modified=now,
    )

    results = scrub_dev_demo_export(using="default")

    assert {result.name for result in results}
    client.refresh_from_db()
    assert client.name == "Realistic Client Ltd"
    assert client.email == "client@example.test"

    xero_app = XeroApp.objects.get()
    assert xero_app.client_id == "client-id"
    assert xero_app.client_secret == ""
    assert xero_app.access_token is None
    assert AIProvider.objects.get().api_key == ""

    service_key.refresh_from_db()
    assert service_key.key.startswith("redacted-key-")

    defaults = CompanyDefaults.objects.get()
    assert defaults.phone_call_downloads_enabled is False
    assert defaults.phone_provider_password == ""
    assert defaults.phone_own_numbers == []

    call.refresh_from_db()
    assert call.duration_seconds == 180
    assert call.charge == Decimal("1.2300")
    assert call.client == client
    assert call.origin.startswith("demo-number-")
    assert call.destination.startswith("demo-number-")
    assert call.raw_json == {}
    assert PhoneCallRecording.objects.count() == 0

    error = AppError.objects.get()
    assert error.app == "workflow"
    assert error.message == "Redacted for dev demo export"
    assert error.data == {}

    recording.refresh_from_db()
    assert recording.initial_path == "/redacted"
    assert recording.user == staff
    chunk = SessionReplayChunk.objects.get()
    assert chunk.storage_path == ""
    assert chunk.path == "/redacted"

    telemetry = SearchTelemetryEvent.objects.get()
    assert telemetry.domain == SearchTelemetryEvent.Domain.CLIENT
    assert telemetry.query == ""
    assert telemetry.metadata == {}

    pay_run.refresh_from_db()
    slip = XeroPaySlip.objects.get()
    assert pay_run.total_pay == Decimal("80.00")
    assert pay_run.raw_json == {}
    assert slip.employee_name == "Demo Employee 001"
    assert slip.net_pay == Decimal("80.00")
    assert slip.raw_json == {}


def test_export_dev_demo_dump_refuses_non_dev_source_db():
    with patch.dict(settings.DATABASES["default"], {"NAME": "dw_msm_prod"}):
        with pytest.raises(RuntimeError, match="must end in '_dev'"):
            call_command("export_dev_demo_dump")


def test_export_dev_demo_dump_runs_copy_scrub_dump_cleanup(tmp_path):
    output = tmp_path / "demo.dump"
    calls: list[str] = []

    def fake_run(self, cmd, env=None):
        calls.append(cmd[0])

    def fake_pipe(self, cmd_a, cmd_b, env=None):
        calls.append(f"{cmd_a[0]}|{cmd_b[0]}")

    with (
        patch.dict(
            settings.DATABASES["default"],
            {
                "NAME": "dw_msm_dev",
                "USER": "dw_msm_dev",
                "PASSWORD": "password",
                "HOST": "/var/run/postgresql",
            },
        ),
        patch.dict(
            settings.DATABASES["scrub"],
            {
                "NAME": "dw_msm_dev_scrub",
                "USER": "dw_msm_dev",
                "PASSWORD": "password",
                "HOST": "/var/run/postgresql",
            },
        ),
        patch(
            "apps.workflow.management.commands.export_dev_demo_dump.Command._run",
            new=fake_run,
        ),
        patch(
            "apps.workflow.management.commands.export_dev_demo_dump.Command._run_pipe",
            new=fake_pipe,
        ),
        patch(
            "apps.workflow.management.commands.export_dev_demo_dump."
            "dev_demo_export_scrubber.scrub_dev_demo_export",
            return_value=[ScrubResult("workflow_xeroapp", 2)],
        ) as scrubber,
    ):
        call_command("export_dev_demo_dump", output=str(output))

    assert calls == ["psql", "pg_dump|pg_restore", "pg_dump", "psql"]
    scrubber.assert_called_once_with()
