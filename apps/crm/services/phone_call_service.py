import hashlib
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import sleep
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote
from uuid import UUID

import requests
from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.client.models import Client, ClientContact, ClientContactMethod
from apps.crm.models import (
    PhoneCallRecord,
    PhoneCallRecording,
    PhoneEndpoint,
    PhoneProviderSettings,
)
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_app_error

if TYPE_CHECKING:
    from apps.accounts.models import Staff

logger = logging.getLogger("apps.crm.phone_calls")

CDR_ENDPOINT = "/json/account/getCdr"
RECORDING_ENDPOINT = "/account/dlrecording"
DELETE_MEDIA_ENDPOINT = "/json/account/deleteMedia"


def _uuid_or_client_error(value: str, message: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValueError(message) from exc


@dataclass(frozen=True)
class PhoneCallSyncResult:
    pages_fetched: int
    calls_seen: int
    calls_skipped: int
    calls_saved: int
    recordings_seen: int
    recordings_archived: int


@dataclass(frozen=True)
class PhoneCallDeleteResult:
    candidates: int
    deleted: int
    failed: int


@dataclass(frozen=True)
class PhoneProviderCallPage:
    page: int
    calls: list[dict[str, Any]]


def sync_recent_calls() -> PhoneCallSyncResult:
    latest_call_date = (
        PhoneCallRecord.objects.order_by("-call_date")
        .values_list("call_date", flat=True)
        .first()
    )
    if latest_call_date:
        start_date = latest_call_date - timedelta(days=1)
    else:
        start_date = None
    return sync_call_history(start_date=start_date, end_date=timezone.localdate())


def sync_call_history(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> PhoneCallSyncResult:
    config = _config()
    client = PhoneProviderPortalClient(config)
    client.login()

    pages_fetched = 0
    calls_seen = 0
    calls_skipped = 0
    calls_saved = 0
    recordings_seen = 0
    recordings_archived = 0
    matcher = PhoneMatcher()

    for page_result in client.iter_call_pages(start_date=start_date, end_date=end_date):
        pages_fetched += 1
        for payload in page_result.calls:
            if not is_call_payload(payload):
                calls_skipped += 1
                continue
            calls_seen += 1
            call, saved = upsert_call_record(
                payload=payload,
                account_code=config.account_code,
                matcher=matcher,
            )
            if saved:
                calls_saved += 1
            if payload.get("RecordingId"):
                recordings_seen += 1
                recording, _ = PhoneCallRecording.objects.get_or_create(
                    provider_recording_id=str(payload["RecordingId"]),
                    defaults={
                        "call": call,
                        "account_code": config.account_code,
                    },
                )
                if recording.call_id != call.id:
                    recording.call = call
                    recording.account_code = config.account_code
                    recording.save(update_fields=["call", "account_code", "updated_at"])
                if recording.archive_error and not recording.archived_at:
                    continue
                try:
                    archived = archive_recording(
                        client=client,
                        call=call,
                        recording=recording,
                    )
                except AlreadyLoggedException:
                    raise
                except Exception as exc:
                    persist_app_error(exc)
                    recording.archive_error = str(exc)
                    recording.save(update_fields=["archive_error", "updated_at"])
                else:
                    if archived:
                        recordings_archived += 1

    return PhoneCallSyncResult(
        pages_fetched=pages_fetched,
        calls_seen=calls_seen,
        calls_skipped=calls_skipped,
        calls_saved=calls_saved,
        recordings_seen=recordings_seen,
        recordings_archived=recordings_archived,
    )


def delete_archived_provider_recordings(*, limit: int = 100) -> PhoneCallDeleteResult:
    config = _config()
    cutoff_date = timezone.localdate() - timezone.timedelta(days=31)
    recordings = list(
        PhoneCallRecording.objects.select_related("call")
        .filter(
            archived_at__isnull=False,
            storage_path__gt="",
            call__call_date__lte=cutoff_date,
            provider_deleted_at__isnull=True,
        )
        .order_by("call__call_date", "call__call_time")[:limit]
    )
    if not recordings:
        return PhoneCallDeleteResult(candidates=0, deleted=0, failed=0)

    client = PhoneProviderPortalClient(config)
    client.login()
    deleted = 0
    failed = 0
    for recording in recordings:
        try:
            client.delete_recording(recording.provider_recording_id)
        except Exception as exc:
            persist_app_error(exc)
            failed += 1
            recording.provider_delete_error = str(exc)
            recording.save(update_fields=["provider_delete_error", "updated_at"])
        else:
            deleted += 1
            recording.provider_deleted_at = timezone.now()
            recording.provider_delete_error = ""
            recording.save(
                update_fields=[
                    "provider_deleted_at",
                    "provider_delete_error",
                    "updated_at",
                ]
            )

    return PhoneCallDeleteResult(
        candidates=len(recordings),
        deleted=deleted,
        failed=failed,
    )


def delete_local_recording(recording: PhoneCallRecording) -> None:
    if not recording.storage_path:
        recording.local_deleted_at = timezone.now()
        recording.save(update_fields=["local_deleted_at", "updated_at"])
        return

    _full_storage_path(recording.storage_path).unlink(missing_ok=True)
    recording.storage_path = ""
    recording.byte_size = None
    recording.sha256 = ""
    recording.local_deleted_at = timezone.now()
    recording.save(
        update_fields=[
            "storage_path",
            "byte_size",
            "sha256",
            "local_deleted_at",
            "updated_at",
        ]
    )


def provider_delete_recording(recording: PhoneCallRecording) -> None:
    if recording.provider_deleted_at:
        return
    client = PhoneProviderPortalClient(_config())
    client.login()
    client.delete_recording(recording.provider_recording_id)
    recording.provider_deleted_at = timezone.now()
    recording.provider_delete_error = ""
    recording.save(
        update_fields=["provider_deleted_at", "provider_delete_error", "updated_at"]
    )


def recording_file_path(recording: PhoneCallRecording) -> Path:
    if not recording.storage_path:
        raise ValueError("Recording has no archived file")
    return _full_storage_path(recording.storage_path)


def link_phone_call_to_job(
    *,
    call_id: str,
    job_id: str,
    linked_by: "Staff",
) -> PhoneCallRecord:
    from apps.job.models import Job

    call_uuid = _uuid_or_client_error(call_id, "Phone call not found")
    job_uuid = _uuid_or_client_error(job_id, "Job not found")

    with transaction.atomic():
        try:
            call = PhoneCallRecord.objects.select_for_update().get(id=call_uuid)
        except PhoneCallRecord.DoesNotExist as exc:
            raise ValueError("Phone call not found") from exc

        if not call.client_id:
            raise ValueError(
                "Phone call must be assigned to a client before linking a job"
            )

        try:
            job = Job.objects.select_for_update().get(id=job_uuid)
        except Job.DoesNotExist as exc:
            raise ValueError("Job not found") from exc

        if job.client_id != call.client_id:
            raise ValueError(
                "Phone call can only be linked to a job for the same client"
            )

        call.job = job
        call.job_linked_by = linked_by
        call.job_linked_at = timezone.now()
        call.save(
            update_fields=[
                "job",
                "job_linked_by",
                "job_linked_at",
                "updated_at",
            ]
        )
        return call


def unlink_phone_call_job(*, call_id: str) -> PhoneCallRecord:
    call_uuid = _uuid_or_client_error(call_id, "Phone call not found")
    try:
        call = PhoneCallRecord.objects.get(id=call_uuid)
    except PhoneCallRecord.DoesNotExist as exc:
        raise ValueError("Phone call not found") from exc

    call.job = None
    call.job_linked_by = None
    call.job_linked_at = None
    call.save(
        update_fields=[
            "job",
            "job_linked_by",
            "job_linked_at",
            "updated_at",
        ]
    )
    return call


def assign_phone_number_from_call(
    *,
    call_id: str,
    client_id: str,
    contact_id: str | None = None,
    label: str = "",
    is_primary: bool = False,
) -> PhoneCallRecord:
    call_uuid = _uuid_or_client_error(call_id, "Phone call not found")
    try:
        call = PhoneCallRecord.objects.get(id=call_uuid)
    except PhoneCallRecord.DoesNotExist as exc:
        raise ValueError("Phone call not found") from exc

    if not call.external_number:
        raise ValueError("Phone call has no external number to assign")

    assign_phone_number(
        phone_number=call.external_number,
        client_id=client_id,
        contact_id=contact_id,
        label=label,
        is_primary=is_primary,
    )
    call.refresh_from_db()
    return call


class PhoneProviderPortalClient:
    def __init__(self, config: "PhoneProviderConfig"):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"),
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            }
        )

    def login(self) -> None:
        response = self.session.post(
            f"{self.config.base_url}/",
            data={
                "username": self.config.username,
                "password": self.config.password,
            },
            timeout=30,
        )
        if response.status_code != 200 or "/account/status" not in response.url:
            raise ValueError(
                "provider login failed: "
                f"status={response.status_code} url={response.url}"
            )

    def iter_call_pages(
        self,
        *,
        page_delay: float = 0.0,
        start_date: date | None = None,
        end_date: date | None = None,
    ):
        page = 1
        consecutive_empty = 0
        while True:
            calls = self.fetch_cdr_page(
                page=page,
                start_date=start_date,
                end_date=end_date,
            )
            if not calls:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    break
                page += 1
                continue
            consecutive_empty = 0
            yield PhoneProviderCallPage(page=page, calls=calls)
            page += 1
            if page_delay:
                sleep(page_delay)

    def fetch_cdr_page(
        self,
        *,
        page: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        data = {
            "p": str(page),
            "accountcode": self.config.account_code,
        }
        if start_date:
            data["StartDate"] = start_date.isoformat()
        if end_date:
            data["EndDate"] = end_date.isoformat()
        response = self.session.post(
            f"{self.config.base_url}{CDR_ENDPOINT}",
            data=data,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError(f"Unexpected provider CDR response type: {type(data)}")
        if data and set(data[0].keys()) <= {"Detail", "Parameter", "Required"}:
            return []
        return data

    def download_recording(self, call: PhoneCallRecord) -> tuple[bytes, str, str]:
        raw = call.raw_json
        response = self.session.get(
            f"{self.config.base_url}{RECORDING_ENDPOINT}",
            params={
                "AccountCode": self.config.account_code,
                "rid": raw["RecordingId"],
                "aparty": raw.get("origin", ""),
                "bparty": raw.get("destination", ""),
                "date": f"{raw['calldate']} - {raw['calltime']}",
            },
            timeout=120,
        )
        response.raise_for_status()
        content = response.content
        if content[:3] == b"200":
            content = content[3:].lstrip(b"\r\n ")
        if not content:
            raise ValueError(f"phone call recording {raw['RecordingId']} was empty")
        return (
            content,
            _filename_from_response(response, call),
            response.headers.get("content-type", ""),
        )

    def delete_recording(self, provider_recording_id: str) -> None:
        response = self.session.post(
            f"{self.config.base_url}{DELETE_MEDIA_ENDPOINT}",
            data={
                "mediaId": provider_recording_id,
                "accountCode": self.config.account_code,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("status", {}).get("Result") != "1":
            raise ValueError(
                f"provider delete failed for recording {provider_recording_id}"
            )


@dataclass(frozen=True)
class PhoneProviderConfig:
    base_url: str
    username: str
    password: str
    account_code: str


def _config() -> PhoneProviderConfig:
    phone_settings = PhoneProviderSettings.get_solo()
    base_url = phone_settings.base_url
    username = phone_settings.username
    password = phone_settings.password
    # All three are required to log in to the provider portal; failing here
    # gives a clear config message instead of an opaque login failure later.
    if not base_url or not username or not password:
        missing = [
            name
            for name, value in (
                ("base URL", base_url),
                ("username", username),
                ("password", password),
            )
            if not value
        ]
        raise ValueError(
            f"phone provider settings missing {', '.join(missing)}; "
            "all are required to log in to the provider portal"
        )
    return PhoneProviderConfig(
        base_url=base_url.rstrip("/"),
        username=username,
        password=password,
        account_code=phone_settings.account_code,
    )


@transaction.atomic
def upsert_call_record(
    *,
    payload: dict[str, Any],
    account_code: str,
    matcher: "PhoneMatcher",
) -> tuple[PhoneCallRecord, bool]:
    provider_call_id = _provider_call_id(payload, account_code)
    call_datetime = _call_datetime(payload)
    origin = normalize_phone(payload.get("origin"))
    destination = normalize_phone(payload.get("destination"))
    classification = matcher.classify(origin, destination)
    defaults = {
        "account_code": account_code,
        "call_datetime": call_datetime,
        "call_date": call_datetime.date(),
        "call_time": call_datetime.time(),
        "call_type": str(payload.get("type") or ""),
        "status": str(payload.get("status") or ""),
        "description": str(payload.get("description") or ""),
        "origin": origin,
        "destination": destination,
        "direction": classification.direction,
        "our_number": classification.our_number,
        "external_number": classification.external_number,
        "origin_endpoint": classification.origin_endpoint,
        "destination_endpoint": classification.destination_endpoint,
        "duration_seconds": _positive_int(payload.get("seconds")),
        "charge": _decimal_or_none(payload.get("charge")),
        "client": classification.client,
        "contact": classification.contact,
        "raw_json": payload,
    }
    call = PhoneCallRecord.objects.filter(provider_call_id=provider_call_id).first()
    if not call:
        return (
            PhoneCallRecord.objects.create(
                provider_call_id=provider_call_id,
                **defaults,
            ),
            True,
        )

    changed_fields = []
    for field_name, value in defaults.items():
        if getattr(call, field_name) != value:
            setattr(call, field_name, value)
            changed_fields.append(field_name)
    if changed_fields:
        call.save(update_fields=[*changed_fields, "updated_at"])
    return call, False


def archive_recording(
    *,
    client: PhoneProviderPortalClient,
    call: PhoneCallRecord,
    recording: PhoneCallRecording,
) -> bool:
    if recording.archived_at and recording.storage_path:
        return False

    content, filename, content_type = client.download_recording(call)
    digest = hashlib.sha256(content).hexdigest()
    storage_path = _recording_storage_path(call=call, recording=recording)
    _write_file(storage_path=storage_path, payload=content)

    recording.filename = filename
    recording.storage_path = storage_path
    recording.content_type = content_type
    recording.byte_size = len(content)
    recording.sha256 = digest
    recording.archived_at = timezone.now()
    recording.archive_error = ""
    recording.local_deleted_at = None
    recording.account_code = call.account_code
    recording.save(
        update_fields=[
            "filename",
            "storage_path",
            "content_type",
            "byte_size",
            "sha256",
            "archived_at",
            "archive_error",
            "local_deleted_at",
            "account_code",
            "updated_at",
        ]
    )
    return True


@dataclass(frozen=True)
class CallClassification:
    direction: str
    our_number: str
    external_number: str
    origin_endpoint: PhoneEndpoint | None
    destination_endpoint: PhoneEndpoint | None
    client: Client | None
    contact: ClientContact | None


class PhoneMatcher:
    """Classifies calls against internal endpoints and client phone methods.

    With ``numbers=None`` the full phone book is indexed (ingest
    classification). Passing a set of normalized numbers restricts the index
    to those numbers only (the rematch path, which already knows every party
    it needs to look up).
    """

    def __init__(self, numbers: set[str] | None = None):
        self.phone_matches = _build_contact_method_phone_index(numbers)
        self.endpoints = {
            endpoint.normalized_number: endpoint
            for endpoint in PhoneEndpoint.objects.filter(is_active=True)
        }

    def match_customer(
        self, *values: str
    ) -> tuple[Client | None, ClientContact | None]:
        matches: set[tuple[str, str, str]] = set()
        for value in values:
            normalized = normalize_phone(value)
            if not normalized:
                continue
            matches.update(self.phone_matches.get(normalized, set()))

        if not matches:
            return None, None

        client_ids = {client_id for _, _, client_id in matches}
        if len(client_ids) != 1:
            return None, None

        if len(matches) != 1:
            client = Client.objects.get(id=next(iter(client_ids)))
            return client, None

        kind, object_id, _client_id = next(iter(matches))
        if kind == "contact":
            contact = ClientContact.objects.select_related("client").get(id=object_id)
            return contact.client, contact
        client = Client.objects.get(id=object_id)
        return client, None

    def classify(self, origin: str, destination: str) -> CallClassification:
        normalized_origin = normalize_phone(origin)
        normalized_destination = normalize_phone(destination)
        origin_endpoint = self.endpoints.get(normalized_origin)
        destination_endpoint = self.endpoints.get(normalized_destination)

        if origin_endpoint and destination_endpoint:
            return CallClassification(
                direction=PhoneCallRecord.Direction.INTERNAL,
                our_number=normalized_origin,
                external_number="",
                origin_endpoint=origin_endpoint,
                destination_endpoint=destination_endpoint,
                client=None,
                contact=None,
            )

        if origin_endpoint:
            client, contact = self.match_customer(normalized_destination)
            return CallClassification(
                direction=PhoneCallRecord.Direction.OUTBOUND,
                our_number=normalized_origin,
                external_number=normalized_destination,
                origin_endpoint=origin_endpoint,
                destination_endpoint=None,
                client=client,
                contact=contact,
            )

        if destination_endpoint:
            client, contact = self.match_customer(normalized_origin)
            return CallClassification(
                direction=PhoneCallRecord.Direction.INBOUND,
                our_number=normalized_destination,
                external_number=normalized_origin,
                origin_endpoint=None,
                destination_endpoint=destination_endpoint,
                client=client,
                contact=contact,
            )

        client, contact = self.match_customer(normalized_origin, normalized_destination)
        external_number = ""
        if normalized_origin and not normalized_destination:
            external_number = normalized_origin
        elif normalized_destination and not normalized_origin:
            external_number = normalized_destination
        else:
            pass  # zero or two candidates is not a strict assignable number.
        return CallClassification(
            direction=PhoneCallRecord.Direction.UNKNOWN,
            our_number="",
            external_number=external_number,
            origin_endpoint=None,
            destination_endpoint=None,
            client=client,
            contact=contact,
        )


def is_call_payload(payload: dict[str, Any]) -> bool:
    if not payload.get("calldate") or not payload.get("calltime"):
        return False
    origin = normalize_phone(payload.get("origin"))
    destination = normalize_phone(payload.get("destination"))
    return bool(origin or destination)


def normalize_phone(value: Any) -> str:
    return ClientContactMethod.normalize_phone(value)


def configured_own_numbers() -> set[str]:
    return set(
        PhoneEndpoint.objects.filter(is_active=True).values_list(
            "normalized_number", flat=True
        )
    )


_REMATCH_FK_FIELDS = frozenset(
    {"client", "contact", "origin_endpoint", "destination_endpoint"}
)


def _call_field_unchanged(call: PhoneCallRecord, name: str, value: object) -> bool:
    if name in _REMATCH_FK_FIELDS:
        current = getattr(call, f"{name}_id")
        target = value.pk if isinstance(value, models.Model) else None
        return bool(current == target)
    return bool(getattr(call, name) == value)


def rematch_calls_for_numbers(numbers: list[str]) -> None:
    normalized_numbers = {normalize_phone(number) for number in numbers}
    normalized_numbers.discard("")
    if not normalized_numbers:
        return

    calls = list(
        PhoneCallRecord.objects.filter(
            models.Q(normalized_origin__in=normalized_numbers)
            | models.Q(normalized_destination__in=normalized_numbers)
        )
    )
    if not calls:
        return

    # Classification looks at both parties of each affected call, so the index
    # must cover every origin/destination seen — but nothing beyond that.
    relevant_numbers = {call.normalized_origin for call in calls} | {
        call.normalized_destination for call in calls
    }
    relevant_numbers.discard("")
    matcher = PhoneMatcher(numbers=relevant_numbers)
    for call in calls:
        classification = matcher.classify(call.origin, call.destination)
        matched_client_id = classification.client.id if classification.client else None
        new_values: dict[str, object] = {
            "client": classification.client,
            "contact": classification.contact,
            "direction": classification.direction,
            "our_number": classification.our_number,
            "external_number": classification.external_number,
            "origin_endpoint": classification.origin_endpoint,
            "destination_endpoint": classification.destination_endpoint,
        }
        if all(
            _call_field_unchanged(call, name, value)
            for name, value in new_values.items()
        ):
            continue
        update_fields = [*new_values, "updated_at"]
        linked_job = call.job
        if linked_job is None:
            should_clear_job_link = False
        else:
            should_clear_job_link = linked_job.client_id != matched_client_id
        if should_clear_job_link:
            call.job = None
            call.job_linked_by = None
            call.job_linked_at = None
            update_fields.extend(["job", "job_linked_by", "job_linked_at"])
        else:
            pass  # No linked job, or the existing job is still on the matched client.
        for name, value in new_values.items():
            setattr(call, name, value)
        call.save(update_fields=update_fields)


def assign_phone_number(
    *,
    phone_number: str,
    client_id: str,
    contact_id: str | None = None,
    label: str = "",
    is_primary: bool = False,
) -> ClientContactMethod:
    normalized = normalize_phone(phone_number)
    if not normalized:
        raise ValueError("phone number is required")
    if normalized in configured_own_numbers():
        raise ValueError("internal phone endpoint cannot be assigned to a client")

    client_uuid = _uuid_or_client_error(client_id, "Client not found")
    if contact_id:
        contact_uuid = _uuid_or_client_error(contact_id, "Contact not found")
        try:
            contact = ClientContact.objects.select_related("client").get(
                id=contact_uuid,
                client_id=client_uuid,
                is_active=True,
            )
        except ClientContact.DoesNotExist as exc:
            raise ValueError("Contact not found") from exc
        owner_filter = {"contact": contact, "client": None}
        existing_primary = ClientContactMethod.objects.filter(
            contact=contact,
            method_type=ClientContactMethod.MethodType.PHONE,
            is_primary=True,
        ).exists()
    else:
        try:
            client = Client.objects.get(id=client_uuid)
        except Client.DoesNotExist as exc:
            raise ValueError("Client not found") from exc
        owner_filter = {"client": client, "contact": None}
        existing_primary = ClientContactMethod.objects.filter(
            client=client,
            contact__isnull=True,
            method_type=ClientContactMethod.MethodType.PHONE,
            is_primary=True,
        ).exists()

    should_be_primary = is_primary or not existing_primary
    conflict = ClientContactMethod.conflicting_client(normalized, client_uuid)
    if conflict:
        raise ValueError(
            f"phone number already belongs to {conflict.owner_display_name()}"
        )

    method, created = ClientContactMethod.objects.get_or_create(
        **owner_filter,
        method_type=ClientContactMethod.MethodType.PHONE,
        normalized_value=normalized,
        defaults={
            "value": phone_number.strip(),
            "label": label.strip(),
            "is_primary": should_be_primary,
            "source": ClientContactMethod.Source.LOCAL,
        },
    )
    if not created:
        method.value = phone_number.strip()
        method.label = label.strip()
        method.source = ClientContactMethod.Source.LOCAL
        method.is_primary = should_be_primary or method.is_primary
        method.save(
            update_fields=["value", "label", "source", "is_primary", "updated_at"]
        )

    rematch_calls_for_numbers([normalized])
    return method


def _build_contact_method_phone_index(
    numbers: set[str] | None = None,
) -> dict[str, set[tuple[str, str, str]]]:
    """Index phone methods by normalized number.

    ``numbers=None`` indexes the whole phone book; a set restricts the query
    to those normalized numbers (rematch path).
    """
    index: dict[str, set[tuple[str, str, str]]] = {}
    internal_numbers = configured_own_numbers()
    methods = ClientContactMethod.objects.select_related(
        "client",
        "contact",
        "contact__client",
    ).filter(method_type=ClientContactMethod.MethodType.PHONE)
    if numbers is not None:
        methods = methods.filter(normalized_value__in=numbers)
    for method in methods:
        normalized = method.normalized_value or normalize_phone(method.value)
        if not normalized or normalized in internal_numbers:
            continue
        if method.contact_id:
            if not method.contact.is_active:
                continue
            index.setdefault(normalized, set()).add(
                ("contact", str(method.contact_id), str(method.contact.client_id))
            )
        else:
            if not method.client.allow_jobs:
                continue
            index.setdefault(normalized, set()).add(
                ("client", str(method.client_id), str(method.client_id))
            )
    return index


def _provider_call_id(payload: dict[str, Any], account_code: str) -> str:
    if payload.get("id"):
        return f"{account_code}:{payload['id']}"
    raw = "|".join(
        str(payload.get(key) or "")
        for key in ["calldate", "calltime", "origin", "destination", "seconds", "type"]
    )
    return f"{account_code}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _call_datetime(payload: dict[str, Any]) -> datetime:
    parsed = datetime.fromisoformat(f"{payload['calldate']} {payload['calltime']}")
    return timezone.make_aware(parsed, timezone.get_current_timezone())


def _positive_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in [None, ""]:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _storage_root() -> Path:
    storage_root = settings.PHONE_RECORDING_STORAGE_ROOT
    if not storage_root:
        raise ValueError("phone recording storage root is not configured")
    return Path(storage_root).resolve()


def _full_storage_path(storage_path: str) -> Path:
    root = _storage_root()
    full_path = (root / storage_path).resolve()
    if not full_path.is_relative_to(root):
        raise ValueError("phone call recording storage path escapes storage root")
    return full_path


def _write_file(*, storage_path: str, payload: bytes) -> None:
    full_path = _full_storage_path(storage_path)
    full_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = full_path.with_name(f".{full_path.name}.{os.getpid()}.tmp")
    try:
        with open(temp_path, "xb") as destination:
            destination.write(payload)
        os.replace(temp_path, full_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _recording_storage_path(
    *,
    call: PhoneCallRecord,
    recording: PhoneCallRecording,
) -> str:
    return (
        f"{call.call_date:%Y/%m/%d}/"
        f"{_safe_filename(recording.provider_recording_id)}.mp3"
    )


def _filename_from_response(response: requests.Response, call: PhoneCallRecord) -> str:
    disposition = response.headers.get("content-disposition", "")
    match = re.search(r'filename[^;=]*=["\']?([^"\';\r\n]+)', disposition)
    if match:
        return _safe_filename(unquote(match.group(1)))
    raw = call.raw_json
    return _safe_filename(
        f"{raw['calldate']}_{raw['calltime']}_{raw.get('origin', 'unknown')}_"
        f"to_{raw.get('destination', 'unknown')}.mp3"
    )


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return safe[:180] or "recording.mp3"
