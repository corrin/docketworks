"""Phone-provider call ingestion, recording archive, and call/number curation.

EXACT-URL PIN (CLAUDE.md porting rules): ingestion is a *pull* — this service
logs in to the external phone provider's portal and polls it. The provider-side
URLs and auth semantics are held by the external party and must not drift:

- login:              POST ``{base_url}/`` with form fields ``username``/``password``
                      (session cookie auth; success == redirect to ``/account/status``)
- CDR poll:           POST ``{base_url}/json/account/getCdr``
- recording download: GET  ``{base_url}/account/dlrecording``
- recording delete:   POST ``{base_url}/json/account/deleteMedia``

There is no inbound webhook and no ServiceAPIKey involvement; credentials come
from the ``phone_provider_*`` columns of ``IntegrationSettings`` (plaintext by
decision — do not re-add encryption).
"""

import hashlib
import logging
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from math import isfinite
from pathlib import Path
from time import sleep
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote
from uuid import UUID

import requests
from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from tinytag import TinyTag, TinyTagException

from apps.company.models import Company, ContactMethod, Person
from apps.core.errors import persist_app_error
from apps.core.models import IntegrationSettings
from apps.crm.models import PhoneCallRecord, PhoneCallRecording, PhoneEndpoint

if TYPE_CHECKING:
    from apps.accounts.models import Staff

logger = logging.getLogger("apps.crm.phone_calls")

# Provider-portal paths — external party holds these; never change (see module
# docstring EXACT-URL PIN).
CDR_ENDPOINT = "/json/account/getCdr"
RECORDING_ENDPOINT = "/account/dlrecording"
DELETE_MEDIA_ENDPOINT = "/json/account/deleteMedia"

# Provider payloads are external JSON with no schema of their own; every value
# is stringified/validated at its use site, so dict[str, Any] is the honest type.
ProviderPayload = dict[str, Any]


@dataclass(frozen=True)
class PhoneCallSyncResult:
    """Counters describing one provider sync run."""

    pages_fetched: int
    calls_seen: int
    calls_skipped: int
    calls_saved: int
    recordings_seen: int
    recordings_archived: int


@dataclass(frozen=True)
class PhoneCallDeleteResult:
    """Counters describing one provider-side recording cleanup run."""

    candidates: int
    deleted: int
    failed: int


@dataclass(frozen=True)
class PhoneProviderCallPage:
    """One page of raw call payloads from the provider CDR endpoint."""

    page: int
    calls: list[ProviderPayload]


def sync_recent_calls() -> PhoneCallSyncResult:
    """Sync from the day before the latest imported call (full history if none)."""
    latest_call_date = (
        PhoneCallRecord.objects.order_by("-call_date").values_list("call_date", flat=True).first()
    )
    start_date = latest_call_date - timedelta(days=1) if latest_call_date else None
    return sync_call_history(start_date=start_date, end_date=timezone.localdate())


def sync_call_history(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> PhoneCallSyncResult:
    """Import provider calls in the date window and archive their recordings."""
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
                if _ingest_recording(
                    client=client,
                    call=call,
                    payload=payload,
                    account_code=config.account_code,
                ):
                    recordings_archived += 1

    return PhoneCallSyncResult(
        pages_fetched=pages_fetched,
        calls_seen=calls_seen,
        calls_skipped=calls_skipped,
        calls_saved=calls_saved,
        recordings_seen=recordings_seen,
        recordings_archived=recordings_archived,
    )


def _ingest_recording(
    *,
    client: "PhoneProviderPortalClient",
    call: PhoneCallRecord,
    payload: ProviderPayload,
    account_code: str,
) -> bool:
    """Attach/refresh the recording row for a call and archive it; True when archived."""
    recording, _ = PhoneCallRecording.objects.get_or_create(
        provider_recording_id=str(payload["RecordingId"]),
        defaults={
            "call": call,
            "account_code": account_code,
        },
    )
    if recording.call_id != call.id:
        recording.call = call
        recording.account_code = account_code
        recording.save(update_fields=["call", "account_code", "updated_at"])
    if recording.archive_error and not recording.archived_at:
        return False
    try:
        archived = archive_recording(
            client=client,
            call=call,
            recording=recording,
        )
    except Exception as exc:  # noqa: BLE001 -- batch loop: one recording must not stop the sweep
        persist_app_error(exc)
        recording.archive_error = str(exc)
        recording.save(update_fields=["archive_error", "updated_at"])
        return False
    return archived


def delete_archived_provider_recordings(*, limit: int = 100) -> PhoneCallDeleteResult:
    """Delete provider-side recordings archived locally and past the 31-day window."""
    config = _config()
    cutoff_date = timezone.localdate() - timedelta(days=31)
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
        except Exception as exc:  # noqa: BLE001 -- batch loop: one recording must not stop the sweep
            persist_app_error(exc)
            failed += 1
            recording.provider_delete_error = str(exc)
            recording.save(update_fields=["provider_delete_error", "updated_at"])
        else:
            deleted += 1
            recording.provider_deleted_at = timezone.now()
            recording.provider_delete_error = None
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
    """Delete the locally archived file and clear the archive columns."""
    if not recording.storage_path:
        recording.local_deleted_at = timezone.now()
        recording.save(update_fields=["local_deleted_at", "updated_at"])
        return

    _full_storage_path(recording.storage_path).unlink(missing_ok=True)
    recording.storage_path = None
    recording.byte_size = None
    recording.duration_ms = None
    recording.sha256 = None
    recording.local_deleted_at = timezone.now()
    recording.save(
        update_fields=[
            "storage_path",
            "byte_size",
            "duration_ms",
            "sha256",
            "local_deleted_at",
            "updated_at",
        ]
    )


def provider_delete_recording(recording: PhoneCallRecording) -> None:
    """Delete the recording on the provider side (idempotent)."""
    if recording.provider_deleted_at:
        return
    client = PhoneProviderPortalClient(_config())
    client.login()
    client.delete_recording(recording.provider_recording_id)
    recording.provider_deleted_at = timezone.now()
    recording.provider_delete_error = None
    recording.save(update_fields=["provider_deleted_at", "provider_delete_error", "updated_at"])


def recording_file_path(recording: PhoneCallRecording) -> Path:
    """Return the absolute path of the locally archived recording file."""
    if not recording.storage_path:
        raise ValueError("Recording has no archived file")
    return _full_storage_path(recording.storage_path)


def link_phone_call_to_job(
    *,
    call_id: UUID,
    job_id: UUID,
    linked_by: "Staff",
) -> PhoneCallRecord:
    """Link a company-matched call to a job of the same company.

    ValueError is the client-error contract (rendered as a 400 by the API).
    """
    from apps.job.models import Job  # noqa: PLC0415 -- Avoid the job/CRM import cycle.

    with transaction.atomic():
        try:
            call = PhoneCallRecord.objects.select_for_update().get(id=call_id)
        except PhoneCallRecord.DoesNotExist as exc:
            raise ValueError("Phone call not found") from exc

        if not call.company_id:
            raise ValueError("Phone call must be assigned to a company before linking a job")

        try:
            job = Job.objects.select_for_update().get(id=job_id)
        except Job.DoesNotExist as exc:
            raise ValueError("Job not found") from exc

        if job.company_id != call.company_id:
            raise ValueError("Phone call can only be linked to a job for the same company")

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


def unlink_phone_call_job(*, call_id: UUID) -> PhoneCallRecord:
    """Clear a call's job link and its linkage metadata."""
    try:
        call = PhoneCallRecord.objects.get(id=call_id)
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
    call_id: UUID,
    company_id: UUID,
    person_id: UUID | None = None,
    label: str | None = None,
    is_primary: bool = False,
) -> PhoneCallRecord:
    """Assign a call's external number to a company (optionally a person) and rematch."""
    try:
        call = PhoneCallRecord.objects.get(id=call_id)
    except PhoneCallRecord.DoesNotExist as exc:
        raise ValueError("Phone call not found") from exc

    if not call.external_number:
        raise ValueError("Phone call has no external number to assign")

    assign_phone_number(
        phone_number=call.external_number,
        company_id=company_id,
        person_id=person_id,
        label=label,
        is_primary=is_primary,
    )
    call.refresh_from_db()
    return call


class PhoneProviderPortalClient:
    """Session-authenticated client for the provider portal (see module docstring)."""

    def __init__(self, config: "PhoneProviderConfig"):
        """Bind the provider config and prepare an anonymous portal session."""
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
        """Log in with the configured credentials; success is the status-page redirect."""
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
                f"provider login failed: status={response.status_code} url={response.url}"
            )

    def iter_call_pages(
        self,
        *,
        page_delay: float = 0.0,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> Iterator[PhoneProviderCallPage]:
        """Yield CDR pages, stopping after two consecutive empty pages.

        The provider can return intermittent empty pages mid-export; stopping at
        the first empty page would silently miss later calls.
        """
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
    ) -> list[ProviderPayload]:
        """Fetch one CDR page as a list of raw call payloads."""
        form = {
            "p": str(page),
            "accountcode": self.config.account_code,
        }
        if start_date:
            form["StartDate"] = start_date.isoformat()
        if end_date:
            form["EndDate"] = end_date.isoformat()
        response = self.session.post(
            f"{self.config.base_url}{CDR_ENDPOINT}",
            data=form,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(  # noqa: TRY004 -- Malformed provider value, not a Python type error.
                f"Unexpected provider CDR response type: {type(payload)}"
            )
        if payload and set(payload[0].keys()) <= {"Detail", "Parameter", "Required"}:
            return []
        return payload

    def download_recording(self, call: PhoneCallRecord) -> tuple[bytes, str, str]:
        """Download a call's recording; returns (content, filename, content type)."""
        raw = call.raw_json
        response = self.session.get(
            f"{self.config.base_url}{RECORDING_ENDPOINT}",
            params={
                "AccountCode": self.config.account_code,
                "rid": str(raw["RecordingId"]),
                # A withheld party is sent as an EMPTY parameter (``aparty=``):
                # requests drops only None, and 2talk serves the recording that
                # way (proven on the real portal 2026-08-23). Stringifying None
                # would send the literal "None".
                "aparty": str(raw.get("origin") or ""),
                "bparty": str(raw.get("destination") or ""),
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
            _filename_from_response(response.headers.get("content-disposition", ""), call),
            response.headers.get("content-type", ""),
        )

    def delete_recording(self, provider_recording_id: str) -> None:
        """Delete a recording on the provider side; the portal reports Result=1."""
        response = self.session.post(
            f"{self.config.base_url}{DELETE_MEDIA_ENDPOINT}",
            data={
                "mediaId": provider_recording_id,
                "accountCode": self.config.account_code,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        status_block = payload.get("status") if isinstance(payload, dict) else None
        result = status_block.get("Result") if isinstance(status_block, dict) else None
        if result != "1":
            raise ValueError(f"provider delete failed for recording {provider_recording_id}")


def verify_portal_login() -> None:
    """Log in to the provider portal with the stored settings; raises on any failure.

    The restore check's proof that the phone integration works: the same
    config resolution and the same login the sync task performs.
    """
    PhoneProviderPortalClient(_config()).login()


@dataclass(frozen=True)
class PhoneProviderConfig:
    """The four values required to log in to the provider portal."""

    base_url: str
    username: str
    password: str
    account_code: str


def _config() -> PhoneProviderConfig:
    integration_settings = IntegrationSettings.get_solo()
    base_url = integration_settings.phone_provider_base_url
    username = integration_settings.phone_provider_username
    password = integration_settings.phone_provider_password
    account_code = integration_settings.phone_provider_account_code
    # All four are required to log in and to stamp the records we import;
    # failing here gives a clear config message instead of an opaque login
    # failure later.
    if not base_url or not username or not password or not account_code:
        missing = [
            name
            for name, value in (
                ("base URL", base_url),
                ("username", username),
                ("password", password),
                ("account code", account_code),
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
        account_code=account_code,
    )


@transaction.atomic
def upsert_call_record(
    *,
    payload: ProviderPayload,
    account_code: str,
    matcher: "PhoneMatcher",
) -> tuple[PhoneCallRecord, bool]:
    """Create or update the call row for a provider payload; True when created."""
    provider_call_id = _provider_call_id(payload, account_code)
    call_datetime = _call_datetime(payload)
    origin = normalize_phone(payload.get("origin"))
    destination = normalize_phone(payload.get("destination"))
    classification = matcher.classify(origin, destination)
    defaults: dict[str, object] = {
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
        "company": classification.company,
        "person": classification.person,
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
    """Download and store a recording locally; False when already archived."""
    if recording.archived_at and recording.storage_path:
        return False

    content, filename, content_type = client.download_recording(call)
    store_recording_bytes(
        call=call,
        recording=recording,
        content=content,
        filename=filename,
        content_type=content_type,
    )
    return True


def store_recording_bytes(
    *,
    call: PhoneCallRecord,
    recording: PhoneCallRecording,
    content: bytes,
    filename: str,
    content_type: str,
) -> None:
    """Write recording audio into the local archive and record it on the row.

    Public because the provider download is not the only producer: the E2E
    seed hands over bytes it generated. Rejected giving the seed its own
    writer — the storage root, path layout and atomic-write rules are one
    implementation (ADR 0039), and a second one drifts from what the download
    endpoint reads.
    """
    digest = hashlib.sha256(content).hexdigest()
    # Measured before anything is written: bytes that are not audio are an
    # archive failure, and the caller records it as one.
    duration_ms = measure_audio_duration_ms(content)
    storage_path = _recording_storage_path(call=call, recording=recording, filename=filename)
    _write_file(storage_path=storage_path, payload=content)

    recording.filename = filename
    recording.storage_path = storage_path
    recording.content_type = content_type
    recording.byte_size = len(content)
    recording.duration_ms = duration_ms
    recording.sha256 = digest
    recording.archived_at = timezone.now()
    recording.archive_error = None
    recording.local_deleted_at = None
    recording.account_code = call.account_code
    recording.save(
        update_fields=[
            "filename",
            "storage_path",
            "content_type",
            "byte_size",
            "duration_ms",
            "sha256",
            "archived_at",
            "archive_error",
            "local_deleted_at",
            "account_code",
            "updated_at",
        ]
    )


def measure_audio_duration_ms(content: bytes) -> int:
    """Length of an audio file's playback, in whole milliseconds.

    Measured here, at archive time, because nothing else knows it: the
    provider's CDR ``seconds`` is billed per started minute, and the browser
    only learns a length once it has fetched the file, which the calls page
    deliberately does not do until play. tinytag rather than a frame parser
    of our own (ADR 0032); it reads the provider's header-less CBR MP3 and the
    E2E seed's WAV alike. Bytes it cannot read are not a recording.
    """
    # Both failures are one fact to the caller: tinytag raises on some junk
    # and answers a None duration on the rest.
    try:
        tag = TinyTag.get(file_obj=BytesIO(content))
    except TinyTagException as exc:
        raise ValueError("recording bytes are not audio tinytag can measure") from exc
    if not tag.duration:
        raise ValueError("recording bytes are not audio tinytag can measure")
    return round(tag.duration * 1000)


@dataclass(frozen=True)
class CallClassification:
    """How a call relates to our endpoints and the company phone book."""

    direction: str
    # NULL is the only unset: an internal call has no external number, and an
    # unattributable one has neither.
    our_number: str | None
    external_number: str | None
    origin_endpoint: PhoneEndpoint | None
    destination_endpoint: PhoneEndpoint | None
    company: Company | None
    person: Person | None


class PhoneMatcher:
    """Classifies calls against internal endpoints and company phone methods.

    With ``numbers=None`` the full phone book is indexed (ingest
    classification). Passing a set of normalized numbers restricts the index
    to those numbers only (the rematch path, which already knows every party
    it needs to look up).
    """

    def __init__(self, numbers: set[str | None] | None = None):
        """Build the phone-book index (full, or restricted to ``numbers``)."""
        self.phone_matches = _build_contact_method_phone_index(numbers)
        self.endpoints = {
            endpoint.normalized_number: endpoint
            for endpoint in PhoneEndpoint.objects.filter(is_active=True)
        }

    def match_customer(self, *values: str | None) -> tuple[Company | None, Person | None]:
        """Resolve numbers to a single owning company (and person when unambiguous)."""
        matches: set[tuple[str, str, str]] = set()
        for value in values:
            normalized = normalize_phone(value)
            if not normalized:
                continue
            matches.update(self.phone_matches.get(normalized, set()))

        if not matches:
            return None, None

        company_ids = {company_id for _, _, company_id in matches}
        if len(company_ids) != 1:
            return None, None

        if len(matches) != 1:
            company = Company.objects.get(id=next(iter(company_ids)))
            return company, None

        kind, object_id, _company_id = next(iter(matches))
        if kind == "person":
            person = Person.objects.get(id=object_id)
            company = Company.objects.get(id=next(iter(company_ids)))
            return company, person
        company = Company.objects.get(id=object_id)
        return company, None

    def classify(self, origin: str | None, destination: str | None) -> CallClassification:
        """Classify a call's direction and parties from its two numbers."""
        normalized_origin = normalize_phone(origin)
        normalized_destination = normalize_phone(destination)
        origin_endpoint = self.endpoints.get(normalized_origin) if normalized_origin else None
        destination_endpoint = (
            self.endpoints.get(normalized_destination) if normalized_destination else None
        )

        if origin_endpoint and destination_endpoint:
            return CallClassification(
                direction=PhoneCallRecord.Direction.INTERNAL,
                our_number=normalized_origin,
                external_number=None,
                origin_endpoint=origin_endpoint,
                destination_endpoint=destination_endpoint,
                company=None,
                person=None,
            )

        if origin_endpoint:
            company, person = self.match_customer(normalized_destination)
            return CallClassification(
                direction=PhoneCallRecord.Direction.OUTBOUND,
                our_number=normalized_origin,
                external_number=normalized_destination,
                origin_endpoint=origin_endpoint,
                destination_endpoint=None,
                company=company,
                person=person,
            )

        if destination_endpoint:
            company, person = self.match_customer(normalized_origin)
            return CallClassification(
                direction=PhoneCallRecord.Direction.INBOUND,
                our_number=normalized_destination,
                external_number=normalized_origin,
                origin_endpoint=None,
                destination_endpoint=destination_endpoint,
                company=company,
                person=person,
            )

        company, person = self.match_customer(normalized_origin, normalized_destination)
        external_number = None
        if normalized_origin and not normalized_destination:
            external_number = normalized_origin
        elif normalized_destination and not normalized_origin:
            external_number = normalized_destination
        else:
            pass  # zero or two candidates is not a strict assignable number.
        return CallClassification(
            direction=PhoneCallRecord.Direction.UNKNOWN,
            our_number=None,
            external_number=external_number,
            origin_endpoint=None,
            destination_endpoint=None,
            company=company,
            person=person,
        )


def is_call_payload(payload: ProviderPayload) -> bool:
    """Report whether the payload looks like a call row (has a date/time and a party)."""
    if not payload.get("calldate") or not payload.get("calltime"):
        return False
    origin = normalize_phone(payload.get("origin"))
    destination = normalize_phone(payload.get("destination"))
    return bool(origin or destination)


def normalize_phone(value: object) -> str | None:
    """Delegate to the one phone-normalization implementation (ContactMethod's).

    None, not "", for "no number": ContactMethod.normalize_phone answers ""
    because its own column is NOT NULL, but every number column on a call is
    nullable with a not-blank check (ADR 0040). 2talk reports a withheld
    caller as origin "", and the first real sync failed on exactly that row
    when "" reached external_number.
    """
    if not value:
        return None
    return ContactMethod.normalize_phone(str(value)) or None


def configured_own_numbers() -> set[str]:
    """Return the normalized numbers of all active internal phone endpoints."""
    return set(
        PhoneEndpoint.objects.filter(is_active=True).values_list("normalized_number", flat=True)
    )


_REMATCH_FK_FIELDS = frozenset({"company", "person", "origin_endpoint", "destination_endpoint"})


def _call_field_unchanged(call: PhoneCallRecord, name: str, value: object) -> bool:
    if name in _REMATCH_FK_FIELDS:
        current = getattr(call, f"{name}_id")
        target = value.pk if isinstance(value, models.Model) else None
        return bool(current == target)
    return bool(getattr(call, name) == value)


def rematch_calls_for_numbers(numbers: list[str]) -> None:
    """Reclassify historical calls touching the given numbers (idempotent)."""
    normalized_numbers: set[str | None] = {normalize_phone(number) for number in numbers}
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
    relevant_numbers: set[str | None] = {call.normalized_origin for call in calls} | {
        call.normalized_destination for call in calls
    }
    relevant_numbers.discard(None)
    matcher = PhoneMatcher(numbers=relevant_numbers)
    for call in calls:
        classification = matcher.classify(call.origin, call.destination)
        matched_company_id = classification.company.id if classification.company else None
        new_values: dict[str, object] = {
            "company": classification.company,
            "person": classification.person,
            "direction": classification.direction,
            "our_number": classification.our_number,
            "external_number": classification.external_number,
            "origin_endpoint": classification.origin_endpoint,
            "destination_endpoint": classification.destination_endpoint,
        }
        if all(_call_field_unchanged(call, name, value) for name, value in new_values.items()):
            continue
        update_fields = [*new_values, "updated_at"]
        linked_job = call.job
        if linked_job is None:
            should_clear_job_link = False
        else:
            should_clear_job_link = linked_job.company_id != matched_company_id
        if should_clear_job_link:
            call.job = None
            call.job_linked_by = None
            call.job_linked_at = None
            update_fields.extend(["job", "job_linked_by", "job_linked_at"])
        else:
            pass  # No linked job, or the existing job is still on the matched company.
        for name, value in new_values.items():
            setattr(call, name, value)
        call.save(update_fields=update_fields)


def assign_phone_number(
    *,
    phone_number: str,
    company_id: UUID,
    person_id: UUID | None = None,
    label: str | None = None,
    is_primary: bool = False,
) -> ContactMethod:
    """Attach a phone number to a company/person contact method and rematch calls.

    ValueError is the client-error contract (rendered as a 400 by the API).
    """
    normalized = normalize_phone(phone_number)
    if not normalized:
        raise ValueError("phone number is required")
    if normalized in configured_own_numbers():
        raise ValueError("internal phone endpoint cannot be assigned to a company")

    owner_filter: dict[str, Company | Person | None]
    if person_id:
        try:
            person = Person.objects.get(id=person_id, is_active=True)
        except Person.DoesNotExist as exc:
            raise ValueError("Person not found") from exc
        if not person.company_links.filter(company_id=company_id, is_active=True).exists():
            raise ValueError("Person is not linked to the selected company")
        owner_filter = {
            "person": person,
            "company": None,
        }
        existing_primary = ContactMethod.objects.filter(
            person=person,
            method_type=ContactMethod.MethodType.PHONE,
            is_primary=True,
        ).exists()
    else:
        try:
            company = Company.objects.get(id=company_id)
        except Company.DoesNotExist as exc:
            raise ValueError("Company not found") from exc
        owner_filter = {"company": company, "person": None}
        existing_primary = ContactMethod.objects.filter(
            company=company,
            person__isnull=True,
            method_type=ContactMethod.MethodType.PHONE,
            is_primary=True,
        ).exists()

    should_be_primary = is_primary or not existing_primary
    conflict = ContactMethod.conflicting_company(normalized, {company_id})
    if conflict:
        raise ValueError(f"phone number already belongs to {conflict.owner_display_name()}")

    method, created = ContactMethod.objects.get_or_create(
        **owner_filter,
        method_type=ContactMethod.MethodType.PHONE,
        normalized_value=normalized,
        defaults={
            "value": phone_number.strip(),
            "label": label,
            "is_primary": should_be_primary,
            "source": ContactMethod.Source.LOCAL,
        },
    )
    if not created:
        method.value = phone_number.strip()
        method.label = label
        method.source = ContactMethod.Source.LOCAL
        method.is_primary = should_be_primary or method.is_primary
        method.save(update_fields=["value", "label", "source", "is_primary", "updated_at"])

    rematch_calls_for_numbers([normalized])
    return method


def _build_contact_method_phone_index(
    numbers: set[str | None] | None = None,
) -> dict[str, set[tuple[str, str, str]]]:
    """Index phone methods by normalized number.

    ``numbers=None`` indexes the whole phone book; a set restricts the query
    to those normalized numbers (rematch path).
    """
    index: dict[str, set[tuple[str, str, str]]] = {}
    internal_numbers = configured_own_numbers()
    methods = ContactMethod.objects.select_related(
        "company",
        "person",
    ).filter(method_type=ContactMethod.MethodType.PHONE)
    if numbers is not None:
        methods = methods.filter(normalized_value__in=numbers)
    for method in methods:
        normalized = method.normalized_value or normalize_phone(method.value)
        if not normalized or normalized in internal_numbers:
            continue
        if method.person_id:
            person = method.person
            if person is None:
                raise RuntimeError(f"Contact method {method.id} has no person")
            if not person.is_active:
                continue
            company_ids = method.owner_company_ids()
            for company_id in company_ids:
                index.setdefault(normalized, set()).add(
                    ("person", str(method.person_id), str(company_id))
                )
        else:
            company = method.company
            if company is None:
                raise RuntimeError(f"Contact method {method.id} has no company")
            if not company.allow_jobs:
                continue
            index.setdefault(normalized, set()).add(
                ("company", str(method.company_id), str(method.company_id))
            )
    return index


def _provider_call_id(payload: ProviderPayload, account_code: str) -> str:
    if payload.get("id"):
        return f"{account_code}:{payload['id']}"
    raw = "|".join(
        str(payload.get(key) or "")
        for key in ["calldate", "calltime", "origin", "destination", "seconds", "type"]
    )
    return f"{account_code}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _call_datetime(payload: ProviderPayload) -> datetime:
    parsed = datetime.fromisoformat(f"{payload['calldate']} {payload['calltime']}")
    return timezone.make_aware(parsed, timezone.get_current_timezone())


def _positive_int(value: object) -> int:
    # Accept anything ``int`` accepts and map every failure to zero; the
    # isinstance gate expresses the same contract without a blind int(object).
    if not isinstance(value, int | float | str):
        return 0
    # inf/nan are rejected here rather than by widening the except below: only
    # ValueError is a parse failure, and int(float("inf")) raises OverflowError,
    # so the documented "unparseable duration is zero" contract was false and a
    # provider payload carrying Infinity crashed the sync instead.
    if isinstance(value, float) and not isfinite(value):
        return 0
    try:
        return max(int(value), 0)
    # deliberate-swallow: documented coercion: unparseable duration is zero
    except ValueError:
        return 0


def _decimal_or_none(value: object) -> Decimal | None:
    if value in [None, ""]:
        return None
    try:
        return Decimal(str(value))
    # deliberate-swallow: unparseable charge is unset; backlog 9 covers the is_finite gap
    except (InvalidOperation, ValueError):
        return None


def _storage_root() -> Path:
    storage_root = getattr(settings, "PHONE_RECORDING_STORAGE_ROOT", None)
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
        with temp_path.open("xb") as destination:
            destination.write(payload)
        temp_path.replace(full_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _recording_storage_path(
    *,
    call: PhoneCallRecord,
    recording: PhoneCallRecording,
    filename: str,
) -> str:
    # The stored suffix is the served Content-Type: the download endpoint
    # guesses it from this path with mimetypes. Rejected pinning ".mp3" (what
    # the provider always sends) — a WAV stored under it is served as
    # audio/mpeg and no browser plays it.
    suffix = Path(filename).suffix.lower() or ".mp3"
    return f"{call.call_date:%Y/%m/%d}/{_safe_filename(recording.provider_recording_id)}{suffix}"


def _filename_from_response(content_disposition: str, call: PhoneCallRecord) -> str:
    match = re.search(r'filename[^;=]*=["\']?([^"\';\r\n]+)', content_disposition)
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
