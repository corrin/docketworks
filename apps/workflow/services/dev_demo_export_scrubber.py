"""
Light scrubber for dev database exports used in trusted-but-external demos.

This is intentionally not the prod-to-dev anonymiser. Prod data has already
been through that path before landing in dev; this pass removes high-risk,
low-demo-value dev operational data while preserving warehouse signal.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from django.contrib.sessions.models import Session
from django.db import connections, transaction

from apps.crm.models import (
    PhoneCallRecord,
    PhoneCallRecording,
    PhoneEndpoint,
    PhoneProviderSettings,
)
from apps.job.models import JobQuoteChat
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
from apps.workflow.services.error_persistence import persist_app_error

SCRUB_ALIAS = "scrub"


@dataclass(frozen=True)
class ScrubResult:
    name: str
    rows: int


def _stable_label(value: str, prefix: str) -> str:
    if not value:
        return ""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _truncate_existing_tables(using: str, tables: tuple[str, ...]) -> list[ScrubResult]:
    results: list[ScrubResult] = []
    connection = connections[using]
    with connection.cursor() as cur:
        for table in tables:
            cur.execute("SELECT to_regclass(%s)", [table])
            if cur.fetchone()[0] is None:
                continue
            cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            rows = cur.fetchone()[0]
            cur.execute(f'TRUNCATE TABLE "{table}" RESTART IDENTITY CASCADE')
            results.append(ScrubResult(table, rows))
    return results


def _redact_xero_apps(using: str) -> ScrubResult:
    rows = XeroApp.objects.using(using).update(
        client_secret="",
        webhook_key="",
        token_type=None,
        access_token=None,
        refresh_token=None,
        expires_at=None,
        scope=None,
        day_remaining=None,
        minute_remaining=None,
        snapshot_at=None,
        last_429_at=None,
    )
    return ScrubResult("workflow_xeroapp", rows)


def _redact_service_api_keys(using: str) -> ScrubResult:
    rows = 0
    for key in ServiceAPIKey.objects.using(using).all():
        key.key = _stable_label(str(key.id), "redacted-key")
        key.last_used = None
        key.save(using=using, update_fields=["key", "last_used"])
        rows += 1
    return ScrubResult("workflow_serviceapikey", rows)


def _redact_company_defaults(using: str) -> ScrubResult:
    rows = CompanyDefaults.objects.using(using).count()
    return ScrubResult("workflow_companydefaults", rows)


def _redact_phone_provider_settings(using: str) -> ScrubResult:
    rows = PhoneProviderSettings.objects.using(using).update(
        downloads_enabled=False,
        recording_deletion_enabled=False,
        base_url=None,
        username="",
        password="",
        account_code="",
    )
    return ScrubResult("crm_phoneprovidersettings", rows)


def _redact_phone_endpoints(using: str) -> ScrubResult:
    rows = 0
    for endpoint in PhoneEndpoint.objects.using(using).order_by("id").iterator():
        PhoneEndpoint.objects.using(using).filter(pk=endpoint.pk).update(
            number=_stable_label(endpoint.number, "demo-endpoint"),
            normalized_number=_stable_label(
                endpoint.normalized_number,
                "demo-endpoint",
            ),
            provider_account_code="",
            provider_metadata={},
        )
        rows += 1
    return ScrubResult("crm_phoneendpoint", rows)


def _redact_phone_calls(using: str) -> ScrubResult:
    rows = 0
    for call in PhoneCallRecord.objects.using(using).all().iterator():
        call.provider_call_id = _stable_label(str(call.id), "demo-call")
        call.account_code = "demo-account"
        call.description = ""
        call.origin = _stable_label(call.origin, "demo-number")
        call.destination = _stable_label(call.destination, "demo-number")
        call.our_number = _stable_label(call.our_number, "demo-number")
        call.external_number = _stable_label(call.external_number, "demo-number")
        call.raw_json = {}
        call.save(
            using=using,
            update_fields=[
                "provider_call_id",
                "account_code",
                "description",
                "origin",
                "destination",
                "our_number",
                "external_number",
                "raw_json",
            ],
        )
        rows += 1
    return ScrubResult("crm_phonecallrecord", rows)


def _delete_phone_recordings(using: str) -> ScrubResult:
    rows = PhoneCallRecording.objects.using(using).count()
    PhoneCallRecording.objects.using(using).all().delete()
    return ScrubResult("crm_phonecallrecording", rows)


def _redact_app_errors(using: str) -> ScrubResult:
    rows = AppError.objects.using(using).update(
        message="Redacted for dev demo export",
        data={},
    )
    return ScrubResult("workflow_apperror", rows)


def _redact_session_replays(using: str) -> list[ScrubResult]:
    recording_rows = SessionReplayRecording.objects.using(using).update(
        initial_path="/redacted",
        latest_path="/redacted",
        user_agent="",
    )
    chunk_rows = SessionReplayChunk.objects.using(using).update(
        storage_path="",
        sha256="",
        path="/redacted",
    )
    return [
        ScrubResult("workflow_sessionreplayrecording", recording_rows),
        ScrubResult("workflow_sessionreplaychunk", chunk_rows),
    ]


def _redact_activity_payloads(using: str) -> list[ScrubResult]:
    search_rows = SearchTelemetryEvent.objects.using(using).update(
        query="",
        normalized_query="",
        filters={},
        returned_result_ids=[],
        selected_result_id="",
        selected_label="",
        metadata={},
    )
    quote_chat_rows = JobQuoteChat.objects.using(using).update(
        content="Redacted for dev demo export",
        metadata={},
    )
    return [
        ScrubResult("workflow_searchtelemetryevent", search_rows),
        ScrubResult("job_jobquotechat", quote_chat_rows),
    ]


def _redact_payroll_payloads(using: str) -> list[ScrubResult]:
    pay_run_rows = XeroPayRun.objects.using(using).update(raw_json={})

    pay_slip_rows = 0
    for index, slip in enumerate(
        XeroPaySlip.objects.using(using).order_by("id").iterator(), start=1
    ):
        slip.employee_name = f"Demo Employee {index:03d}"
        slip.raw_json = {}
        slip.save(using=using, update_fields=["employee_name", "raw_json"])
        pay_slip_rows += 1

    return [
        ScrubResult("workflow_xeropayrun", pay_run_rows),
        ScrubResult("workflow_xeropayslip", pay_slip_rows),
    ]


def scrub_dev_demo_export(using: str = SCRUB_ALIAS) -> list[ScrubResult]:
    """Apply the minimal dev-demo export scrub policy to `using`."""
    results: list[ScrubResult] = []
    try:
        with transaction.atomic(using=using):
            results.extend(
                _truncate_existing_tables(
                    using,
                    (
                        Session._meta.db_table,
                        "django_admin_log",
                        "django_celery_results_taskresult",
                        "django_celery_results_groupresult",
                    ),
                )
            )
            results.append(_redact_xero_apps(using))
            results.append(
                ScrubResult(
                    "workflow_aiprovider",
                    AIProvider.objects.using(using).update(api_key=""),
                )
            )
            results.append(_redact_service_api_keys(using))
            results.append(_redact_company_defaults(using))
            results.append(_redact_phone_provider_settings(using))
            results.append(_redact_phone_endpoints(using))
            results.append(_delete_phone_recordings(using))
            results.append(_redact_phone_calls(using))
            results.append(_redact_app_errors(using))
            results.extend(_redact_session_replays(using))
            results.extend(_redact_activity_payloads(using))
            results.extend(_redact_payroll_payloads(using))
    except Exception as exc:
        persist_app_error(exc)
        raise
    return results
