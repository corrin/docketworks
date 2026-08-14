"""Light scrubber for dev database exports used in trusted-but-external demos.

Deliberately NOT the production anonymiser (the backport db_scrubber): prod
data has already been through that path before landing in dev, so this pass
only removes high-risk, low-demo-value operational data — credentials and
direct identifiers — while preserving warehouse signal. Coupling the two would
force the demo export through full anonymisation, destroying the data the demo
exists to show.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from django.apps import apps as django_apps
from django.contrib.sessions.models import Session
from django.db import connections, transaction

from apps.core.errors import persist_app_error
from apps.core.models import AppError, ServiceAPIKey
from apps.crm.models import (
    PhoneCallRecord,
    PhoneCallRecording,
    PhoneEndpoint,
    PhoneProviderSettings,
)
from apps.diagnostics.models import SessionReplayChunk, SessionReplayRecording
from apps.job.models import JobQuoteChat

SCRUB_ALIAS = "scrub"


@dataclass(frozen=True)
class ScrubResult:
    """One scrubbed table's name and affected row count."""

    name: str
    rows: int


def _stable_label(value: str | None, prefix: str) -> str:
    """Stable pseudonym for ``value``; "" when there is nothing to redact.

    Returns str because non-nullable columns (ServiceAPIKey.key,
    PhoneCallRecord.provider_call_id) also use it. Nullable columns convert
    the empty result to NULL at the call site.
    """
    if not value:
        return ""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _truncate_existing_tables(using: str, tables: tuple[str, ...]) -> list[ScrubResult]:
    """TRUNCATE each table that exists on the alias, reporting prior row counts."""
    results: list[ScrubResult] = []
    connection = connections[using]
    with connection.cursor() as cur:
        for table in tables:
            cur.execute("SELECT to_regclass(%s)", [table])
            row = cur.fetchone()
            if row is None or row[0] is None:
                continue
            cur.execute(f'SELECT COUNT(*) FROM "{table}"')  # noqa: S608 -- table names come from the fixed tuple below, never input
            count_row = cur.fetchone()
            rows = int(count_row[0]) if count_row is not None else 0
            cur.execute(f'TRUNCATE TABLE "{table}" RESTART IDENTITY CASCADE')
            results.append(ScrubResult(table, rows))
    return results


def _redact_xero_apps(using: str) -> ScrubResult:
    """Clear OAuth credentials and rate-limit telemetry from XeroApp rows.

    App-registry lookup instead of ``from apps.xero.models import XeroApp``:
    diagnostics and xero are independent siblings in the layer contract, so a
    direct import is off-limits even at function level.
    """
    xero_app = django_apps.get_model("xero", "XeroApp")
    rows = xero_app._default_manager.using(using).update(
        client_secret="",
        webhook_key=None,
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


def _redact_ai_providers(using: str) -> ScrubResult:
    """Blank every AI provider API key.

    Registry lookup: apps.ai sits beside apps.core in the bottom layer, which
    diagnostics could import — but AIProvider carries a not-blank CHECK on
    api_key, and NULL is the clearing value (ADR 0040), so the update is by
    kwargs either way; get_model keeps this module's cross-app access uniform.
    """
    ai_provider = django_apps.get_model("ai", "AIProvider")
    rows = ai_provider._default_manager.using(using).update(api_key=None)
    return ScrubResult("workflow_aiprovider", rows)


def _redact_service_api_keys(using: str) -> ScrubResult:
    """Replace every service API key with a stable pseudonym."""
    rows = 0
    for key_id in ServiceAPIKey.objects.using(using).values_list("id", flat=True):
        ServiceAPIKey.objects.using(using).filter(pk=key_id).update(
            key=_stable_label(str(key_id), "redacted-key"),
            last_used=None,
        )
        rows += 1
    return ScrubResult("workflow_serviceapikey", rows)


def _redact_phone_provider_settings(using: str) -> ScrubResult:
    """Remove phone-provider credentials and disable remote operations."""
    rows = PhoneProviderSettings.objects.using(using).update(
        downloads_enabled=False,
        recording_deletion_enabled=False,
        base_url=None,
        username="",
        password="",
        account_code=None,
    )
    return ScrubResult("crm_phoneprovidersettings", rows)


def _redact_phone_endpoints(using: str) -> ScrubResult:
    """Pseudonymise endpoint numbers, keeping rows distinct and joinable."""
    rows = 0
    for endpoint in PhoneEndpoint.objects.using(using).order_by("id").iterator():
        PhoneEndpoint.objects.using(using).filter(pk=endpoint.pk).update(
            number=_stable_label(endpoint.number, "demo-endpoint"),
            normalized_number=_stable_label(endpoint.normalized_number, "demo-endpoint"),
            provider_account_code=None,
            provider_metadata={},
        )
        rows += 1
    return ScrubResult("crm_phoneendpoint", rows)


def _redact_phone_calls(using: str) -> ScrubResult:
    """Pseudonymise call parties and drop free-text/raw payloads."""
    rows = 0
    for call in PhoneCallRecord.objects.using(using).all().iterator():
        PhoneCallRecord.objects.using(using).filter(pk=call.pk).update(
            provider_call_id=_stable_label(str(call.id), "demo-call"),
            account_code="demo-account",
            description=None,
            origin=_stable_label(call.origin, "demo-number") or None,
            destination=_stable_label(call.destination, "demo-number") or None,
            normalized_origin=_stable_label(call.normalized_origin, "demo-number") or None,
            normalized_destination=_stable_label(call.normalized_destination, "demo-number")
            or None,
            our_number=_stable_label(call.our_number, "demo-number") or None,
            external_number=_stable_label(call.external_number, "demo-number") or None,
            raw_json={},
        )
        rows += 1
    return ScrubResult("crm_phonecallrecord", rows)


def _delete_phone_recordings(using: str) -> ScrubResult:
    """Delete call recordings outright — audio is unredactable."""
    rows = PhoneCallRecording.objects.using(using).count()
    PhoneCallRecording.objects.using(using).all().delete()
    return ScrubResult("crm_phonecallrecording", rows)


def _redact_app_errors(using: str) -> ScrubResult:
    """Blank error messages and context payloads (tracebacks carry real data)."""
    rows = AppError.objects.using(using).update(
        message="Redacted for dev demo export",
        data={},
    )
    return ScrubResult("workflow_apperror", rows)


def _redact_session_replays(using: str) -> list[ScrubResult]:
    """Strip navigation paths and user agents from replay metadata."""
    recording_rows = SessionReplayRecording.objects.using(using).update(
        initial_path="/redacted",
        latest_path="/redacted",
        user_agent=None,
    )
    chunk_rows = SessionReplayChunk.objects.using(using).update(
        # NOT NULL: redaction clears these in place rather than nulling them.
        storage_path="",
        sha256="",
        path="/redacted",
    )
    return [
        ScrubResult("workflow_sessionreplayrecording", recording_rows),
        ScrubResult("workflow_sessionreplaychunk", chunk_rows),
    ]


def _redact_activity_payloads(using: str) -> list[ScrubResult]:
    """Drop search queries and quote-chat content, keeping event volumes."""
    # Registry lookup: search is a sibling integration app (layer contract).
    telemetry = django_apps.get_model("search", "SearchTelemetryEvent")
    search_rows = telemetry._default_manager.using(using).update(
        query=None,
        normalized_query=None,
        filters={},
        returned_result_ids=[],
        selected_result_id=None,
        selected_label=None,
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
    """Blank payroll raw payloads and rename pay-slip employees."""
    # Registry lookups: xero is a sibling integration app (layer contract).
    pay_run = django_apps.get_model("xero", "XeroPayRun")
    pay_slip = django_apps.get_model("xero", "XeroPaySlip")

    pay_run_rows = pay_run._default_manager.using(using).update(raw_json={})

    pay_slip_rows = 0
    for index, slip_pk in enumerate(
        pay_slip._default_manager.using(using).order_by("id").values_list("pk", flat=True),
        start=1,
    ):
        pay_slip._default_manager.using(using).filter(pk=slip_pk).update(
            employee_name=f"Demo Employee {index:03d}",
            raw_json={},
        )
        pay_slip_rows += 1

    return [
        ScrubResult("workflow_xeropayrun", pay_run_rows),
        ScrubResult("workflow_xeropayslip", pay_slip_rows),
    ]


def scrub_dev_demo_export(using: str = SCRUB_ALIAS) -> list[ScrubResult]:
    """Apply the minimal dev-demo export scrub policy to ``using``."""
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
            results.append(_redact_ai_providers(using))
            results.append(_redact_service_api_keys(using))
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
