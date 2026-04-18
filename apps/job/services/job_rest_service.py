"""
Job REST Service Layer

Following SRP (Single Responsibility Principle) and clean code guidelines.
All business logic for Job REST operations should be implemented here.
"""

import json
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import singledispatch
from typing import Any, Dict, Iterable, Mapping
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.accounts.models import Staff
from apps.client.models import Client, ClientContact
from apps.job.models import Job, JobDeltaRejection, JobEvent
from apps.job.models.costing import CostLine
from apps.job.serializers import JobSerializer
from apps.job.serializers.job_serializer import (
    CompanyDefaultsJobDetailSerializer,
    InvoiceSerializer,
    JobEventSerializer,
    JobSummarySerializer,
    QuoteSerializer,
)
from apps.job.services.delta_checksum import compute_job_delta_checksum, normalise_value
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models import CompanyDefaults, XeroPayItem
from apps.workflow.services.error_persistence import persist_and_raise

logger = logging.getLogger(__name__)


class PreconditionFailed(Exception):
    """Raised when ETag precondition fails (HTTP 412)."""


class DeltaValidationError(PreconditionFailed):
    """Raised when the delta payload fails checksum or before-state validation."""

    def __init__(
        self,
        message: str,
        *,
        current_values: Dict[str, Any] | None = None,
        server_checksum: str | None = None,
    ) -> None:
        super().__init__(message)
        self.current_values = current_values or {}
        self.server_checksum = server_checksum


def _current_job_etag_value(job: Job) -> str:
    """
    Return normalized ETag value for comparison (without W/ and quotes).
    Mirrors BaseJobRestView._gen_job_etag but normalized.
    """
    try:
        ts_ms = int(job.updated_at.timestamp() * 1000)
    except Exception:
        ts_ms = 0
    return f"job:{job.id}:{ts_ms}"


@dataclass
class JobDeltaPayload:
    """
    Structured representation of the delta envelope submitted by the client.

    We keep this lightweight dataclass (instead of passing DRF serializer
    instances around) so the service layer can remain decoupled from REST
    dependencies when used internally and always operate on a normalised,
    immutable structure regardless of the caller.
    """

    change_id: str
    fields: tuple[str, ...]
    before: Dict[str, Any]
    after: Dict[str, Any]
    before_checksum: str
    actor_id: str | None = None
    made_at: datetime | None = None
    job_id: str | None = None
    etag: str | None = None
    undo_of_change_id: str | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "JobDeltaPayload":
        required_keys = {"change_id", "fields", "before", "after", "before_checksum"}
        missing = required_keys - payload.keys()
        if missing:
            raise ValueError(
                f"Missing required delta fields: {', '.join(sorted(missing))}"
            )

        fields_value = payload.get("fields") or []
        if not isinstance(
            fields_value, Iterable
        ):  # guard scalar payloads before normalising
            raise ValueError("Delta 'fields' must be a list of field names")

        fields_tuple = tuple(str(field) for field in fields_value)
        if not fields_tuple:
            raise ValueError("Delta 'fields' cannot be empty")

        before = payload.get("before") or {}
        after = payload.get("after") or {}

        if not isinstance(before, Mapping) or not isinstance(
            after, Mapping
        ):  # ensure JSON objects, not strings/arrays
            raise ValueError("Delta 'before' and 'after' must be objects")

        return cls(
            change_id=str(payload["change_id"]),
            fields=fields_tuple,
            before=dict(before),
            after=dict(after),
            before_checksum=str(payload["before_checksum"]),
            actor_id=str(payload.get("actor_id")) if payload.get("actor_id") else None,
            made_at=payload.get("made_at"),
            job_id=str(payload.get("job_id")) if payload.get("job_id") else None,
            etag=str(payload.get("etag")) if payload.get("etag") else None,
            undo_of_change_id=(
                str(payload.get("undo_of_change_id"))
                if payload.get("undo_of_change_id")
                else None
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation of the payload contents."""
        return {
            "change_id": self.change_id,
            "fields": list(self.fields),
            "before": self.before,
            "after": self.after,
            "before_checksum": self.before_checksum,
            "actor_id": self.actor_id,
            "made_at": (
                self.made_at.isoformat()
                if isinstance(self.made_at, datetime)
                else self.made_at
            ),
            "job_id": self.job_id,
            "etag": self.etag,
            "undo_of_change_id": self.undo_of_change_id,
        }


@singledispatch
def _to_json_safe(value: Any) -> Any:
    """
    Convert value to JSON-serializable format.

    TODO: If this warning doesn't appear in production logs for 2+ weeks,
    remove this fallback entirely and raise TypeError instead.
    """
    logger.warning(
        f"[JSON_SERIALIZATION] Unhandled type in _to_json_safe: {type(value).__name__} "
        f"with value: {value!r} - returning as-is (may cause JSON encoding errors later)"
    )
    return value


@_to_json_safe.register(str)
def _json_from_str(value: str) -> str:
    return value


@_to_json_safe.register(int)
@_to_json_safe.register(float)
@_to_json_safe.register(bool)
def _json_from_primitive(value: int | float | bool) -> int | float | bool:
    return value


@_to_json_safe.register(type(None))
def _json_from_none(value: None) -> None:
    return value


@_to_json_safe.register(dict)
def _json_from_dict(value: Dict[Any, Any]) -> Dict[str, Any]:
    return {str(key): _to_json_safe(sub_value) for key, sub_value in value.items()}


@_to_json_safe.register(list)
@_to_json_safe.register(tuple)
@_to_json_safe.register(set)
def _json_from_iterable(value: Iterable[Any]) -> list[Any]:
    return [_to_json_safe(item) for item in value]


@_to_json_safe.register(datetime)
def _json_from_datetime(value: datetime) -> str:
    return value.isoformat()


@_to_json_safe.register(date)
def _json_from_date(value: date) -> str:
    return value.isoformat()


@_to_json_safe.register(Decimal)
def _json_from_decimal(value: Decimal) -> str:
    return format(value, "f")


@_to_json_safe.register(UUID)
def _json_from_uuid(value: UUID) -> str:
    return str(value)


class JobRestService:
    """
    Service layer for Job REST operations.
    Implements all business rules related to Job manipulation via REST API.
    """

    _FIELD_ATTRIBUTE_MAP = {
        # Map payload field names to model attribute names for validation
        "job_status": "status",
    }

    @staticmethod
    def _is_soft_fail_enabled() -> bool:
        """Return True when checksum/field mismatches should not raise.

        Controlled via env var JOB_DELTA_SOFT_FAIL (default: True).
        Only "True" enables soft-fail; any other value (including "False") disables it.
        """
        return settings.JOB_DELTA_SOFT_FAIL

    @staticmethod
    def create_job(data: Dict[str, Any], user: Staff) -> Job:
        """
        Creates a new Job with essential data.
        Applies early return for validations.

        Args:
            data: Form creation data
            user: User creating the job

        Returns:
            Job: Created job instance

        Raises:
            ValueError: If required data is missing
        """
        # Guard clauses - early return for validations
        if not data.get("name"):
            raise ValueError("Job name is required")

        if not data.get("client_id"):
            raise ValueError("Client is required")

        try:
            client = Client.objects.get(id=data["client_id"])
        except Client.DoesNotExist:
            raise ValueError("Client not found")

        job_data = {
            "name": data["name"],
            "client": client,
            "created_by": user,
        }

        # Optional fields - only if provided
        optional_fields = [
            "description",
            "order_number",
            "notes",
            "pricing_methodology",
        ]
        for field in optional_fields:
            if data.get(field):
                job_data[field] = data[field]

        # Contact (optional relationship)
        if contact_id := data.get("contact_id"):
            try:
                contact = ClientContact.objects.get(id=contact_id)
                job_data["contact"] = contact
            except ClientContact.DoesNotExist:
                raise ValueError(f"Contact with id {contact_id} not found")

        # Set default pay item to Ordinary Time for new jobs
        ordinary_time = XeroPayItem.get_ordinary_time()
        if not ordinary_time:
            raise ValueError(
                "Ordinary Time pay item not found. Sync Xero pay items first."
            )
        job_data["default_xero_pay_item"] = ordinary_time

        # Not needed for now, but needs to be discussed when we activate project sync
        # job_data["xero_last_modified"] = timezone.now()

        with transaction.atomic():
            job = Job(**job_data)
            job.save(staff=user)

            # Create job creation event (moved from Job.save() to prevent duplicates)
            client_name = job.client.name if job.client else "Shop Job"
            contact_info = f" (Contact: {job.contact.name})" if job.contact else ""
            JobEvent.objects.create(
                job=job,
                event_type="job_created",
                description=f"New job '{job.name}' created for client {client_name}{contact_info}. "
                f"Initial status: {job.get_status_display()}. "
                f"Pricing methodology: {job.get_pricing_methodology_display()}.",
                staff=user,
            )

            # Create initial estimate CostLines if provided
            estimated_materials = data.get("estimated_materials")
            estimated_time = data.get("estimated_time")

            if estimated_materials is None:
                raise ValueError("estimated_materials is required")
            if estimated_time is None:
                raise ValueError("estimated_time is required")

            # Get the estimate CostSet (already created by job.save())
            estimate_costset = job.cost_sets.get(kind="estimate")

            # Get company defaults for calculations
            company_defaults = CompanyDefaults.get_solo()
            if not company_defaults:
                raise ValueError("CompanyDefaults not found")

            wage_rate = company_defaults.wage_rate.quantize(Decimal("0.01"))
            charge_out_rate = company_defaults.charge_out_rate.quantize(Decimal("0.01"))

            # estimated_materials is entered as retail price (what customer pays)
            # Convert to cost price using the standard 20% materials markup (retail = cost * 1.2)
            MATERIALS_MARKUP_MULTIPLIER = Decimal("1.2")
            materials_cost = (
                estimated_materials / MATERIALS_MARKUP_MULTIPLIER
            ).quantize(Decimal("0.01"))

            # Create material cost line
            # unit_cost is the cost price, unit_rev is the retail price (original input)
            CostLine.objects.create(
                cost_set=estimate_costset,
                kind="material",
                desc="Estimated materials",
                quantity=Decimal("1.000"),
                unit_cost=materials_cost,
                unit_rev=estimated_materials,
                accounting_date=timezone.now().date(),
            )

            # Create workshop time cost line
            CostLine.objects.create(
                cost_set=estimate_costset,
                kind="time",
                desc="Estimated workshop time",
                quantity=estimated_time,
                unit_cost=wage_rate,
                unit_rev=charge_out_rate,
                accounting_date=timezone.now().date(),
                xero_pay_item=ordinary_time,
            )

            # Calculate office time (1:8 ratio, rounded up to quarter hours)
            office_time_decimal = float(estimated_time) / 8
            office_time_hours = Decimal(str(math.ceil(office_time_decimal * 4) / 4))

            CostLine.objects.create(
                cost_set=estimate_costset,
                kind="time",
                desc="Estimated office time",
                quantity=office_time_hours,
                unit_cost=wage_rate,
                unit_rev=charge_out_rate,
                accounting_date=timezone.now().date(),
                xero_pay_item=ordinary_time,
            )

            # For fixed_price jobs, copy estimate lines to quote CostSet
            if job.pricing_methodology == "fixed_price":
                quote_costset = job.cost_sets.get(kind="quote")
                for estimate_line in estimate_costset.cost_lines.all():
                    CostLine.objects.create(
                        cost_set=quote_costset,
                        kind=estimate_line.kind,
                        desc=estimate_line.desc,
                        quantity=estimate_line.quantity,
                        unit_cost=estimate_line.unit_cost,
                        unit_rev=estimate_line.unit_rev,
                        accounting_date=estimate_line.accounting_date,
                        ext_refs=(
                            estimate_line.ext_refs.copy()
                            if estimate_line.ext_refs
                            else {}
                        ),
                        meta=estimate_line.meta.copy() if estimate_line.meta else {},
                        xero_pay_item=estimate_line.xero_pay_item,
                    )

        return job

    @staticmethod
    def _record_delta_rejection(
        job: Job | None,
        staff: Staff | None,
        *,
        reason: str,
        detail: Any = "",
        envelope: Mapping[str, Any] | None = None,
        change_id: str | None = None,
        checksum: str | None = None,
        request_etag: str | None = None,
        request_ip: str | None = None,
    ) -> None:
        """Persist information about a rejected delta for forensic analysis."""
        try:
            change_uuid = JobRestService._safe_uuid(change_id)
            defaults = {
                "job": job,
                "staff": staff,
                "reason": (reason or "")[:255],
                "detail": JobRestService._serialise_detail(detail),
                "envelope": _to_json_safe(envelope or {}),
                "checksum": checksum or "",
                "request_etag": (request_etag or "")[:128],
                "request_ip": request_ip,
            }

            if job and change_uuid:
                JobDeltaRejection.objects.update_or_create(
                    job=job, change_id=change_uuid, defaults=defaults
                )
            else:
                JobDeltaRejection.objects.create(
                    job=job,
                    staff=staff,
                    change_id=change_uuid,
                    reason=defaults["reason"],
                    detail=defaults["detail"],
                    envelope=defaults["envelope"],
                    checksum=defaults["checksum"],
                    request_etag=defaults["request_etag"],
                    request_ip=request_ip,
                )
        except Exception as exc:  # pragma: no cover - defensive persistence
            persist_and_raise(exc)

    @staticmethod
    def _collect_soft_fail_context(
        *,
        job: Job | None,
        staff: Staff | None,
        delta_payload: JobDeltaPayload,
        request_etag: str | None,
    ) -> dict[str, Any] | None:
        """
        Build persistence payload for soft-failed checksum mismatches.

        The caller is responsible for invoking `_record_delta_rejection`
        outside of the main transaction so the entry survives rollbacks.
        """
        if not JobRestService._is_soft_fail_enabled():
            return None

        server_checksum = getattr(delta_payload, "_server_checksum", None)
        current_values = getattr(delta_payload, "_current_values", {})
        if server_checksum and server_checksum != delta_payload.before_checksum:
            return {
                "job": job,
                "staff": staff,
                "reason": "Delta checksum mismatch (soft-fail)",
                "detail": {
                    "server_checksum": server_checksum,
                    "current_values": current_values,
                },
                "envelope": delta_payload.to_dict(),
                "change_id": delta_payload.change_id,
                "checksum": delta_payload.before_checksum,
                "request_etag": delta_payload.etag or request_etag,
            }
        return None

    @staticmethod
    def _serialise_detail(detail: Any) -> str:
        if detail in (None, ""):
            return ""
        converted = _to_json_safe(detail)
        if isinstance(converted, (dict, list)):
            return json.dumps(converted)
        return str(converted)[:2000]

    @staticmethod
    def _safe_uuid(value: Any) -> UUID | None:
        if not value:
            return None
        try:
            return UUID(str(value))
        except (ValueError, TypeError, AttributeError):
            return None

    @staticmethod
    def _looks_like_delta_payload(data: Any) -> bool:
        if not isinstance(data, Mapping):
            return False
        required_keys = {"change_id", "fields", "before", "after", "before_checksum"}
        return required_keys.issubset(data.keys())

    @staticmethod
    def _validate_delta_payload(job: Job, delta: JobDeltaPayload) -> None:
        logger.debug(
            f"[DELTA_VALIDATION] Starting validation for job {job.id}, change_id: {delta.change_id}"
        )
        logger.debug(f"[DELTA_VALIDATION] Fields to validate: {list(delta.fields)}")

        fields = set(delta.fields)
        if not fields:
            raise ValueError("Delta payload must specify at least one field")

        before_keys = set(delta.before.keys())
        after_keys = set(delta.after.keys())

        missing_before = fields - before_keys
        missing_after = fields - after_keys

        if missing_before or missing_after:
            issues: list[str] = []
            if missing_before:
                issues.append(f"missing 'before' values for {sorted(missing_before)}")
            if missing_after:
                issues.append(f"missing 'after' values for {sorted(missing_after)}")
            raise ValueError("Delta payload is inconsistent: " + "; ".join(issues))

        logger.debug(
            "[DELTA_VALIDATION] Payload structure validated. Getting current job values..."
        )

        current_values: Dict[str, Any] = {}
        for field in fields:
            current_values[field] = JobRestService._get_job_field_value(job, field)
            logger.debug(
                f"[DELTA_VALIDATION] Current value for '{field}': {current_values[field]} (type: {type(current_values[field])})"
            )

        logger.debug(f"[DELTA_VALIDATION] Current job values: {current_values}")
        logger.debug(f"[DELTA_VALIDATION] Delta before values: {delta.before}")
        logger.debug(f"[DELTA_VALIDATION] Client checksum: {delta.before_checksum}")

        # Compute server checksum
        server_checksum = compute_job_delta_checksum(job.id, current_values, fields)
        logger.debug(f"[DELTA_VALIDATION] Server computed checksum: {server_checksum}")

        soft_fail = JobRestService._is_soft_fail_enabled()

        if server_checksum != delta.before_checksum:
            if soft_fail:
                logger.warning(
                    "[DELTA_VALIDATION] CHECKSUM MISMATCH (soft-fail): "
                    f"job_id={job.id} change_id={delta.change_id} "
                    f"server_checksum={server_checksum} client_checksum={delta.before_checksum} "
                    f"fields={sorted(fields)} current_values={current_values} delta_before={delta.before}"
                )
            else:
                logger.error("[DELTA_VALIDATION] CHECKSUM MISMATCH!")
                logger.error(f"[DELTA_VALIDATION] Server checksum: {server_checksum}")
                logger.error(
                    f"[DELTA_VALIDATION] Client checksum: {delta.before_checksum}"
                )
                logger.error(f"[DELTA_VALIDATION] Job ID: {job.id}")
                logger.error(f"[DELTA_VALIDATION] Fields: {sorted(fields)}")
                logger.error(f"[DELTA_VALIDATION] Current values: {current_values}")
                logger.error(f"[DELTA_VALIDATION] Delta before: {delta.before}")
                raise DeltaValidationError(
                    "Delta checksum mismatch: job has changed since the delta was generated",
                    current_values=current_values,
                    server_checksum=server_checksum,
                )

        if not soft_fail:
            logger.debug(
                "[DELTA_VALIDATION] Checksum validation passed. Checking individual field values..."
            )
            # Validate field values strictly only when not in soft-fail mode
            for field in fields:
                current_value = current_values[field]
                before_value = delta.before[field]
                current_norm = normalise_value(current_value)
                before_norm = normalise_value(before_value)
                if current_norm != before_norm:
                    logger.error(
                        f"[DELTA_VALIDATION] FIELD MISMATCH for '{field}'! "
                        f"current_norm={current_norm} before_norm={before_norm}"
                    )
                    raise DeltaValidationError(
                        f"Delta before state mismatch for field '{field}'",
                        current_values=current_values,
                        server_checksum=server_checksum,
                    )

        logger.info(
            f"[DELTA_VALIDATION] Passed for job {job.id}, fields: {sorted(fields)}"
        )

        # Attach telemetry for callers (soft-fail persistence path)
        setattr(delta, "_current_values", current_values)
        setattr(delta, "_server_checksum", server_checksum)

    @staticmethod
    def _get_job_field_value(job: Job, field: str) -> Any:
        """
        Get the value of a job field from the Job model.

        TODO: If warning doesn't appear in prod logs for 2+ weeks, remove fallback and fail early.
        """
        attribute_name = JobRestService._FIELD_ATTRIBUTE_MAP.get(field, field)

        if hasattr(job, attribute_name):
            return getattr(job, attribute_name)

        # Fallback - this code path should not be triggered
        if attribute_name.endswith("_id") and hasattr(job, attribute_name):
            logger.warning(
                f"[FALLBACK_TRIGGERED] _id suffix fallback used for field '{field}'"
            )
            return getattr(job, attribute_name)

        raise ValueError(f"Unsupported field '{field}' in delta payload")

    @staticmethod
    def get_job_for_edit(job_id: UUID, request) -> Dict[str, Any]:
        """
        Fetches complete Job data for editing.

        Args:
            job_id: Job UUID

        Returns:
            Dict with job data (pricing data removed - use CostSet endpoints)

        Raises:
            ValueError: If job is not found.
        """
        try:
            job = Job.objects.select_related("client").get(id=job_id)
        except Job.DoesNotExist:
            raise ValueError(f"Job with id {job_id} not found")

        # Serialise main data
        job_data = JobSerializer(job, context={"request": request}).data

        events = JobEvent.objects.filter(job=job).order_by("-timestamp")
        events_data = JobEventSerializer(
            events, many=True, context={"request": request}
        ).data

        company_defaults = JobRestService._get_company_defaults()
        company_data = CompanyDefaultsJobDetailSerializer(
            company_defaults, context={"request": request}
        ).data

        return {
            "job": job_data,
            "events": events_data,
            "company_defaults": company_data,
        }

    @staticmethod
    def get_job_summary(job_id: UUID, request) -> Dict[str, Any]:
        """
        Fetches Job data with cost set summaries only (no cost lines or events).

        Returns the same response shape as get_job_for_edit but with
        cost_lines: [] in each cost set and events: [].

        Args:
            job_id: Job UUID
            request: HTTP request (for serializer context)

        Returns:
            Dict with job summary data

        Raises:
            ValueError: If job is not found.
        """
        try:
            job = Job.objects.select_related("client").get(id=job_id)
        except Job.DoesNotExist:
            raise ValueError(f"Job with id {job_id} not found")

        job_data = JobSummarySerializer(job, context={"request": request}).data

        company_defaults = JobRestService._get_company_defaults()
        company_data = CompanyDefaultsJobDetailSerializer(
            company_defaults, context={"request": request}
        ).data

        return {
            "job": job_data,
            "events": [],
            "company_defaults": company_data,
        }

    @staticmethod
    def get_job_quote(job_id: UUID) -> list[Dict[str, Any]]:
        """
        Fetches quotes for a specific job.

        Args:
            job_id: Job UUID

        Returns:
            List of quote data

        Raises:
            ValueError: If job is not found
        """
        try:
            job = Job.objects.get(id=job_id)
        except Job.DoesNotExist:
            raise ValueError(f"Job with id {job_id} not found")

        if job.quoted:
            return QuoteSerializer(job.quote).data

    @staticmethod
    def get_job_invoices(job_id: UUID) -> list[Dict[str, Any]]:
        """
        Fetches invoices for a specific job.

        Args:
            job_id: Job UUID

        Returns:
            List of invoice data

        Raises:
            ValueError: If job is not found
        """
        try:
            job = Job.objects.get(id=job_id)
        except Job.DoesNotExist:
            raise ValueError(f"Job with id {job_id} not found")

        invoices = job.invoices.all().order_by("-date")
        return InvoiceSerializer(invoices, many=True).data

    @staticmethod
    def get_job_basic_information(job_id: UUID) -> Dict[str, Any]:
        """
        Fetches basic information for a specific job.

        Args:
            job_id: Job UUID

        Returns:
            Dict with basic job information

        Raises:
            ValueError: If job is not found
        """
        try:
            job = Job.objects.get(id=job_id)
        except Job.DoesNotExist:
            raise ValueError(f"Job with id {job_id} not found")

        return {
            "description": job.description or "",
            "delivery_date": (
                job.delivery_date.isoformat() if job.delivery_date else None
            ),
            "order_number": job.order_number or "",
            "notes": job.notes or "",
        }

    @staticmethod
    def list_job_delta_rejections(
        *, job_id: UUID | str | None = None, limit: int = 50, offset: int = 0
    ) -> Dict[str, Any]:
        """Return paginated delta rejection records, optionally filtered by job."""
        if limit <= 0:
            limit = 1
        limit = min(limit, 200)
        offset = max(offset, 0)

        queryset = (
            JobDeltaRejection.objects.select_related("job")
            .all()
            .order_by("-created_at")
        )
        if job_id:
            queryset = queryset.filter(job_id=job_id)
        total = queryset.count()
        results = list(queryset[offset : offset + limit])

        next_offset: str | None = None
        prev_offset: str | None = None
        if offset + limit < total:
            next_offset = str(offset + limit)
        if offset > 0:
            prev_offset = str(max(offset - limit, 0))

        return {
            "count": total,
            "next": next_offset,
            "previous": prev_offset,
            "results": results,
        }

    @classmethod
    def list_grouped_job_delta_rejections(
        cls,
        *,
        limit: int = 50,
        offset: int = 0,
        job_id: str | None = None,
        resolved: bool | None = None,
    ) -> Dict[str, Any]:
        import hashlib

        from django.db.models import Count, Max, Min, OuterRef, Subquery

        if limit <= 0:
            limit = 1
        limit = min(limit, 200)
        offset = max(offset, 0)

        queryset = JobDeltaRejection.objects.all()
        if resolved is None:
            queryset = queryset.filter(resolved=False)
        else:
            queryset = queryset.filter(resolved=resolved)
        if job_id:
            queryset = queryset.filter(job_id=job_id)

        # Subquery is intentionally unfiltered: latest_id is an informational
        # pointer to the most-recent row by created_at for this reason, across
        # all resolved states.
        latest_id_sq = (
            JobDeltaRejection.objects.filter(reason=OuterRef("reason"))
            .order_by("-created_at")
            .values("id")[:1]
        )

        aggregated = (
            queryset.values("reason")
            .annotate(
                occurrence_count=Count("id"),
                first_seen=Min("created_at"),
                last_seen=Max("created_at"),
                latest_id=Subquery(latest_id_sq),
            )
            .order_by("-last_seen")
        )
        total = aggregated.count()
        rows = list(aggregated[offset : offset + limit])

        results = [
            {
                "fingerprint": hashlib.sha256(
                    row["reason"].encode("utf-8")
                ).hexdigest(),
                "reason": row["reason"],
                "occurrence_count": row["occurrence_count"],
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
                "latest_id": row["latest_id"],
            }
            for row in rows
        ]

        next_offset = str(offset + limit) if offset + limit < total else None
        prev_offset = str(max(offset - limit, 0)) if offset > 0 else None

        return {
            "count": total,
            "next": next_offset,
            "previous": prev_offset,
            "results": results,
        }

    @classmethod
    def mark_job_delta_rejection_group_resolved(cls, reason: str, staff: Staff) -> int:
        return JobDeltaRejection.objects.filter(reason=reason).update(
            resolved=True,
            resolved_by=staff,
            resolved_timestamp=timezone.now(),
        )

    @classmethod
    def mark_job_delta_rejection_group_unresolved(
        cls, reason: str, staff: Staff
    ) -> int:
        return JobDeltaRejection.objects.filter(reason=reason).update(
            resolved=False,
            resolved_by=None,
            resolved_timestamp=None,
        )

    @staticmethod
    def update_job(
        job_id: UUID, data: Dict[str, Any], user: Staff, if_match: str | None = None
    ) -> Job:
        """
        Updates an existing Job with optimistic concurrency control (ETag).
        Requires If-Match header to match current resource version.
        """
        if not JobRestService._looks_like_delta_payload(data):
            raise ValueError("Delta envelope is required for job updates")

        try:
            delta_payload = JobDeltaPayload.from_dict(data)
        except ValueError as exc:
            raise ValueError(f"Invalid delta payload: {exc}") from exc

        # Transform delta payload fields to serializer field names
        job_data: Dict[str, Any] = {}
        for key, value in delta_payload.after.items():
            # Keep job_status as job_status for serializer compatibility
            job_data[key] = value

        logger.info(
            f"[JOB_UPDATE] Starting job update for job {job_id}, change_id: {delta_payload.change_id}"
        )
        logger.info(f"[JOB_UPDATE] Fields being updated: {list(delta_payload.fields)}")
        logger.info(f"[JOB_UPDATE] If-Match header: {if_match}")

        job: Job | None = None
        result_job: Job | None = None
        soft_fail_context: dict[str, Any] | None = None
        try:
            with transaction.atomic():
                # Lock the row to avoid race between compare and update
                logger.debug("[JOB_UPDATE] Locking job row for update...")
                job = get_object_or_404(Job.objects.select_for_update(), id=job_id)
                logger.debug(
                    f"[JOB_UPDATE] Job locked. Current updated_at: {job.updated_at}"
                )

                # **VALIDATE DELTA FIRST** - before any other checks that might modify the job
                logger.debug("[JOB_UPDATE] Starting delta payload validation...")
                try:
                    JobRestService._validate_delta_payload(job, delta_payload)
                    logger.info("[JOB_UPDATE] Delta validation passed successfully")
                except DeltaValidationError as exc:
                    logger.error(f"[JOB_UPDATE] Delta validation failed: {exc}")
                    # Always persist via outer handler; re-raise if hard-fail
                    if not JobRestService._is_soft_fail_enabled():
                        raise
                except ValueError as exc:
                    logger.error(f"[JOB_UPDATE] Delta validation error: {exc}")
                    exc.delta_rejection_context = {
                        "reason": "Invalid delta payload",
                        "detail": {"error": str(exc), "stage": "validation"},
                    }
                    raise
                # Capture soft-fail context for persistence outside the transaction
                soft_fail_context = JobRestService._collect_soft_fail_context(
                    job=job,
                    staff=user,
                    delta_payload=delta_payload,
                    request_etag=if_match,
                )

                # Concurrency check using normalized ETag value - AFTER delta validation
                logger.debug("[JOB_UPDATE] Checking ETag precondition...")
                if not if_match:
                    logger.warning(
                        "[JOB_UPDATE] No If-Match header provided - skipping ETag validation"
                    )
                else:
                    current_norm = _current_job_etag_value(job)
                    logger.debug(f"[JOB_UPDATE] Current ETag: {current_norm}")
                    logger.debug(f"[JOB_UPDATE] Client ETag: {if_match}")
                    if current_norm != if_match:
                        logger.error(
                            f"[JOB_UPDATE] ETag mismatch! Current: {current_norm}, Expected: {if_match}"
                        )
                        raise PreconditionFailed("ETag mismatch: resource has changed")
                    logger.debug("[JOB_UPDATE] ETag validation passed")

                # DEBUG: Log incoming data
                logger.debug(f"JobRestService.update_job - Incoming data: {data}")
                logger.debug(
                    f"JobRestService.update_job - Current job contact: {job.contact}"
                )
                logger.debug(
                    f"JobRestService.update_job - Current job contact_id: {job.contact.id if job.contact else None}"
                )

                # Store original values for comparison
                original_values = {
                    "name": job.name,
                    "description": job.description,
                    "status": job.status,
                    "priority": job.priority,
                    "client_id": job.client_id,
                    "charge_out_rate": job.charge_out_rate,
                    "order_number": job.order_number,
                    "notes": job.notes,
                    "contact_id": job.contact.id if job.contact else None,
                    "contact_name": job.contact.name if job.contact else None,
                    "contact_email": job.contact.email if job.contact else None,
                    "contact_phone": job.contact.phone if job.contact else None,
                    "speed_quality_tradeoff": job.speed_quality_tradeoff,
                    "pricing_methodology": job.pricing_methodology,
                    "price_cap": job.price_cap,
                    "fully_invoiced": job.fully_invoiced,
                    "quote_acceptance_date": job.quote_acceptance_date,
                    "paid": job.paid,
                    "rejected_flag": job.rejected_flag,
                    "rdti_type": job.rdti_type,
                    "min_people": job.min_people,
                    "max_people": job.max_people,
                }

                logger.debug(
                    f"JobRestService.update_job - Original values: {original_values}"
                )

                if delta_payload.job_id and str(job.id) != delta_payload.job_id:
                    detail = {
                        "delta_job_id": delta_payload.job_id,
                        "target_job_id": str(job.id),
                    }
                    exc = ValueError(
                        f"Delta job_id {delta_payload.job_id} does not match target job {job.id}"
                    )
                    exc.delta_rejection_context = {
                        "reason": "Delta job_id mismatch",
                        "detail": detail,
                    }
                    raise exc

                # Use serializer for validation and updating
                serializer = JobSerializer(
                    instance=job,
                    data=job_data,  # Use extracted job_data instead of raw data
                    partial=True,
                    context={"request": type("MockRequest", (), {"user": user})()},
                )

                if not serializer.is_valid():
                    logger.error(
                        "JobRestService.update_job - Serializer validation failed: "
                        f"{serializer.errors}"
                    )
                    raise ValueError(f"Invalid data: {serializer.errors}")

                logger.debug(
                    f"JobRestService.update_job - Validated data: {serializer.validated_data}"
                )

                job = serializer.save(staff=user)

                # When status changes via edit, place job at top of new column
                if (
                    "job_status" in delta_payload.fields
                    and job.status != original_values["status"]
                ):
                    job.priority = Job._calculate_next_priority_for_status(job.status)
                    job.save(update_fields=["priority", "updated_at"])

                # When client changes, auto-set contact to new client's primary contact.
                # This eliminates the need for frontend to make a separate API call.
                # Only do this if contact_id was NOT explicitly provided in the update.
                original_client_id = original_values.get("client_id")
                contact_explicitly_updated = "contact_id" in delta_payload.fields
                try:
                    if (
                        job.client
                        and original_client_id != job.client_id
                        and not contact_explicitly_updated
                    ):
                        # Client changed - set contact to new client's primary contact
                        primary_contact = ClientContact.objects.filter(
                            client_id=job.client_id,
                            is_primary=True,
                            is_active=True,
                        ).first()
                        job.contact = primary_contact  # May be None if no primary
                        job.save(staff=user)
                        logger.info(
                            f"Auto-set contact to primary contact after client change: "
                            f"job.client_id={job.client_id}, "
                            f"contact={'None' if not primary_contact else primary_contact.id}"
                        )
                    elif (
                        job.contact
                        and job.client
                        and job.contact.client_id != job.client_id
                    ):
                        # Fallback guard: if contact doesn't belong to client, clear it
                        logger.warning(
                            "Clearing mismatched contact after client change: "
                            f"contact.client_id={job.contact.client_id} != job.client_id={job.client_id}"
                        )
                        job.contact = None
                        job.save(staff=user)
                except Exception as _e:
                    # Persist the error but do not mask the main operation
                    try:
                        persist_and_raise(_e)
                    except AlreadyLoggedException:
                        pass

                # Generate descriptive update message
                description = JobRestService._generate_update_description(
                    original_values, delta_payload.after
                )

                # Log the update with descriptive message
                meta_payload = {
                    "fields": list(delta_payload.fields),
                    "actor_id": delta_payload.actor_id,
                    "made_at": delta_payload.made_at,
                    "etag": delta_payload.etag,
                }
                if delta_payload.undo_of_change_id:
                    meta_payload["undo_of_change_id"] = delta_payload.undo_of_change_id
                JobEvent.objects.create(
                    job=job,
                    staff=user,
                    event_type="job_updated",
                    description=description,
                    schema_version=1,
                    change_id=JobRestService._safe_uuid(delta_payload.change_id),
                    delta_before=_to_json_safe(delta_payload.before),
                    delta_after=_to_json_safe(delta_payload.after),
                    delta_meta=_to_json_safe(meta_payload),
                    delta_checksum=delta_payload.before_checksum or "",
                )

                result_job = job
        except PreconditionFailed:
            if soft_fail_context:
                JobRestService._record_delta_rejection(**soft_fail_context)
            raise
        except DeltaValidationError as exc:
            JobRestService._record_delta_rejection(
                job=job,
                staff=user,
                reason=getattr(exc, "delta_rejection_context", {}).get(
                    "reason", str(exc)
                ),
                detail=getattr(exc, "delta_rejection_context", {}).get("detail"),
                envelope=delta_payload.to_dict(),
                change_id=delta_payload.change_id,
                checksum=delta_payload.before_checksum,
                request_etag=delta_payload.etag or if_match,
            )
            raise
        except ValueError as exc:
            context = getattr(exc, "delta_rejection_context", None)
            if context is not None:
                JobRestService._record_delta_rejection(
                    job=job,
                    staff=user,
                    reason=context.get("reason", "Invalid delta payload"),
                    detail=context.get("detail"),
                    envelope=delta_payload.to_dict(),
                    change_id=delta_payload.change_id,
                    checksum=delta_payload.before_checksum,
                    request_etag=delta_payload.etag or if_match,
                )
            raise
        else:
            if soft_fail_context:
                JobRestService._record_delta_rejection(**soft_fail_context)
            if result_job is None:  # Defensive guard
                return job
            return result_job

    @staticmethod
    def undo_job_change(
        job_id: UUID,
        change_id: UUID,
        user: Staff,
        if_match: str | None = None,
        undo_change_id: UUID | None = None,
    ) -> Job:
        """Undo a previously recorded delta by reverting to its before state."""
        job = get_object_or_404(Job, id=job_id)

        event = (
            JobEvent.objects.filter(job_id=job_id, change_id=change_id)
            .order_by("-timestamp")
            .first()
        )
        if not event:
            raise ValueError(f"Job event with change_id {change_id} not found")
        if event.schema_version != 1:
            raise ValueError("Undo is only supported for schema_version=1 events")
        if not event.delta_before or not event.delta_after:
            raise ValueError("Stored event does not contain delta_before/delta_after")

        meta = event.delta_meta or {}
        fields = meta.get("fields") or list(event.delta_before.keys())
        if not fields:
            raise ValueError("Event metadata missing target fields for undo")
        fields = [str(field) for field in fields]

        current_values: Dict[str, Any] = {}
        for field in fields:
            current_values[field] = JobRestService._get_job_field_value(job, field)

        mismatch_fields = []
        for field in fields:
            current_norm = normalise_value(current_values[field])
            expected_norm = normalise_value(event.delta_after.get(field))
            if current_norm != expected_norm:
                mismatch_fields.append(field)

        if mismatch_fields:
            JobRestService._record_delta_rejection(
                job=job,
                staff=user,
                reason="Undo delta mismatch",
                detail={
                    "fields": mismatch_fields,
                    "expected_after": event.delta_after,
                    "current_values": current_values,
                },
                envelope=event.delta_after,
                change_id=str(change_id),
                checksum=event.delta_checksum,
            )
            raise PreconditionFailed(
                "Cannot undo change because the current job state no longer matches the original delta"
            )

        checksum = compute_job_delta_checksum(job.id, current_values, fields)
        undo_identifier = undo_change_id or uuid4()
        payload: Dict[str, Any] = {
            "change_id": str(undo_identifier),
            "job_id": str(job.id),
            "fields": fields,
            "before": current_values,
            "after": event.delta_before,
            "before_checksum": checksum,
            "actor_id": str(user.id),
            "made_at": timezone.now().isoformat(),
            "etag": _current_job_etag_value(job),
            "undo_of_change_id": str(change_id),
        }

        return JobRestService.update_job(job_id, payload, user, if_match=if_match)

    @staticmethod
    def toggle_complex_job(
        job_id: UUID, complex_job: bool, user: Staff
    ) -> Dict[str, Any]:
        """
        Toggles the complex_job mode of a Job.
        Implements specific validation rules.

        Args:
            job_id: Job UUID
            complex_job: New boolean value
            user: User making the change

        Returns:
            Dict with operation result
        """
        # Early return - type validation
        if not isinstance(complex_job, bool):
            raise ValueError("complex_job must be a boolean value")

        job = get_object_or_404(Job, id=job_id)

        # Guard clause - check if can disable complex mode
        if not complex_job and job.complex_job:
            validation_result = JobRestService._validate_can_disable_complex_mode(job)
            if not validation_result["can_disable"]:
                raise ValueError(validation_result["reason"])

        with transaction.atomic():
            job.complex_job = complex_job
            job.save()
            # Log the change
            mode_action = "enabled" if complex_job else "disabled"
            JobEvent.objects.create(
                job=job,
                staff=user,
                event_type="setting_changed",
                description=f"Itemised billing {mode_action}",
            )

        return {
            "success": True,
            "job_id": str(job_id),
            "complex_job": complex_job,
            "message": "Job updated successfully",
        }

    @staticmethod
    @transaction.atomic
    def add_job_event(job_id: UUID, description: str, user: Staff) -> Dict[str, Any]:
        """
        Adds a manual event to the Job with duplicate prevention.

        Args:
            job_id: Job UUID
            description: Event description
            user: User creating the event

        Returns:
            Dict with created event data
        """
        try:
            # Guard clause - input validation
            if not description or not description.strip():
                raise ValueError("Event description is required")

            # Lock the job to prevent race conditions
            job = Job.objects.select_for_update().get(id=job_id)

            description_clean = description.strip()

            # Check for recent duplicates (last 5 seconds)
            recent_threshold = timezone.now() - timedelta(seconds=5)

            existing_event = JobEvent.objects.filter(
                job=job,
                staff=user,
                description=description_clean,
                event_type="manual_note",
                timestamp__gte=recent_threshold,
            ).first()

            if existing_event:
                logger.warning(
                    f"Duplicate event prevented for job {job_id} by user {user.email}. "
                    f"Existing event: {existing_event.id}"
                )
                # Return existing event instead of creating duplicate
                return {
                    "success": True,
                    "event": existing_event,
                    "duplicate_prevented": True,
                }

            # Create new event using safe method
            event, created = JobEvent.create_safe(
                job=job,
                staff=user,
                description=description_clean,
                event_type="manual_note",
            )

            if not created:
                logger.warning(
                    f"Event already exists for job {job_id} by user {user.email}. "
                    f"Returning existing event: {event.id}"
                )

            logger.info(
                f"Event {event.id} {'created' if created else 'found'} "
                f"for job {job_id} by {user.email}",
                extra={
                    "job_id": str(job_id),
                    "event_id": str(event.id),
                    "user_id": str(user.id),
                    # renamed this field so we don’t collide with LogRecord.created
                    "was_created": created,
                    "operation": "add_job_event",
                },
            )

            return {
                "success": True,
                "event": event,
                "duplicate_prevented": not created,
            }

        except Job.DoesNotExist:
            error_msg = f"Job {job_id} not found"
            logger.error(error_msg)
            raise ValueError(error_msg)

        except (ValidationError, IntegrityError) as e:
            # Handle duplicate constraint violations
            logger.warning(
                f"Duplicate event constraint violation for job {job_id} by user {user.email}: {e}"
            )

            # If we can't find existing event, re-raise
            raise ValueError("Unable to create event due to duplicate constraint")

        except Exception as e:
            # Persist error for debugging
            persist_and_raise(
                exception=e,
                app="JobRestService",
                file=__file__,
                function="add_job_event",
                severity=logging.ERROR,
                job_id=str(job_id),
                user_id=str(user.id),
                additional_context={
                    "description": description,
                    "operation": "add_job_event",
                },
            )

    @staticmethod
    def delete_job(
        job_id: UUID, user: Staff, if_match: str | None = None
    ) -> Dict[str, Any]:
        """
        Deletes a Job if allowed by business rules and ETag precondition matches.
        """
        # Lock row during deletion checks
        job = get_object_or_404(Job.objects.select_for_update(), id=job_id)

        # Concurrency check
        if if_match:
            current_norm = _current_job_etag_value(job)
            if current_norm != if_match:
                raise PreconditionFailed("ETag mismatch: resource has changed")

        actual_cost_set = job.latest_actual

        if actual_cost_set and (
            actual_cost_set.summary.get("cost", 0) > 0
            or actual_cost_set.summary.get("rev", 0) > 0
        ):
            raise ValueError(
                "Cannot delete this job because it has real costs or revenue."
            )

        job_name = job.name
        job_number = job.job_number
        with transaction.atomic():
            job.delete()

            logger.info(f"Job {job_number} '{job_name}' deleted by {user.email}")

        return {"success": True, "message": f"Job {job_number} deleted successfully"}

    @staticmethod
    def accept_quote(
        job_id: UUID, user: Staff, if_match: str | None = None
    ) -> Dict[str, Any]:
        """
        Accept a quote for a job by setting the quote_acceptance_date and changing status to approved.
        Enforces optimistic concurrency via If-Match (ETag) precondition.
        """
        with transaction.atomic():
            job = get_object_or_404(Job.objects.select_for_update(), id=job_id)

            if if_match:
                current_norm = _current_job_etag_value(job)
                if current_norm != if_match:
                    raise PreconditionFailed("ETag mismatch: resource has changed")

            if not job.latest_quote:
                raise ValueError("No quote found for this job")

            if job.quote_acceptance_date:
                raise ValueError("Quote has already been accepted")

            if job.status not in ["draft", "awaiting_approval"]:
                raise ValueError(
                    f"Cannot accept quote when job status is '{job.status}'. Job must be in 'draft' or 'awaiting_approval' state."
                )

            job.quote_acceptance_date = timezone.now()
            job.status = "approved"
            job.save()

            # Log the acceptance
            JobEvent.objects.create(
                job=job,
                staff=user,
                event_type="quote_accepted",
                description="Quote accepted - status changed to approved",
            )

        logger.info(
            f"Quote accepted for job {job.job_number} by {user.email} - status changed to approved"
        )

        return {
            "success": True,
            "job_id": str(job_id),
            "quote_acceptance_date": job.quote_acceptance_date.isoformat(),
            "status": job.status,
            "message": "Quote accepted successfully",
        }

    @staticmethod
    def get_job_timeline(job_id: UUID) -> list[Dict[str, Any]]:
        """
        Fetches unified timeline combining JobEvents and CostLine data.

        Args:
            job_id: Job UUID

        Returns:
            List of timeline entries sorted by timestamp

        Raises:
            ValueError: If job is not found
        """
        try:
            job = Job.objects.get(id=job_id)
        except Job.DoesNotExist:
            raise ValueError(f"Job with id {job_id} not found")

        timeline_entries = []

        # Get all JobEvents
        events = JobEvent.objects.filter(job=job).select_related("staff")
        for event in events:
            # Calculate undo support for this event
            can_undo = (
                event.schema_version == 1
                and event.change_id is not None
                and event.delta_before is not None
                and event.delta_after is not None
            )

            undo_description = None
            if can_undo:
                # Extract field information from delta_meta if available
                meta = event.delta_meta or {}
                fields = meta.get("fields", [])

                if not fields:
                    undo_description = f"Undo '{event.description}'"
                else:
                    field_names = []
                    for field in fields:
                        # Map internal field names to user-friendly labels
                        field_labels = {
                            "name": "job name",
                            "description": "description",
                            "status": "status",
                            "order_number": "order number",
                            "notes": "notes",
                            "client_id": "client",
                            "contact_id": "contact",
                            "delivery_date": "delivery date",
                            "charge_out_rate": "charge out rate",
                            "job_status": "status",
                            "paid": "payment status",
                            "job_is_valid": "validity",
                            "rejected_flag": "rejection status",
                            "pricing_methodology": "pricing method",
                        }
                        field_names.append(
                            field_labels.get(field, field.replace("_", " "))
                        )

                    if len(field_names) == 1:
                        undo_description = f"Undo change to {field_names[0]}"
                    elif len(field_names) <= 3:
                        undo_description = f"Undo changes to {', '.join(field_names[:-1])} and {field_names[-1]}"
                    else:
                        undo_description = f"Undo changes to {len(field_names)} fields"

            timeline_entries.append(
                {
                    "id": event.id,
                    "timestamp": event.timestamp,
                    "entry_type": "event",
                    "description": event.description,
                    "staff": (
                        event.staff.get_display_full_name() if event.staff else None
                    ),
                    "event_type": event.event_type,
                    "can_undo": can_undo,
                    "undo_description": undo_description,
                    # Include additional fields for undo support
                    "schema_version": event.schema_version,
                    "change_id": str(event.change_id) if event.change_id else None,
                    "delta_before": event.delta_before,
                    "delta_after": event.delta_after,
                    "delta_meta": event.delta_meta,
                    "delta_checksum": event.delta_checksum,
                }
            )

        # Get all CostLines from all CostSets for this job
        cost_sets = job.cost_sets.all().prefetch_related("cost_lines")

        # Collect all unique staff IDs from cost lines to fetch in bulk (avoid N+1)
        staff_ids = set()
        for cost_set in cost_sets:
            for cost_line in cost_set.cost_lines.all():
                if staff_id := cost_line.ext_refs.get("staff_id"):
                    # FAIL EARLY: Invalid staff_id indicates data corruption
                    try:
                        staff_ids.add(UUID(str(staff_id)))
                    except (ValueError, TypeError):
                        error_msg = (
                            f"Invalid staff_id in cost_line {cost_line.id}: {staff_id}"
                        )
                        logger.error(error_msg)
                        persist_and_raise(
                            ValueError(error_msg),
                            additional_context={
                                "cost_line_id": str(cost_line.id),
                                "staff_id": staff_id,
                                "job_id": str(job.id),
                            },
                        )

        # Fetch all staff members in bulk
        staff_map = Staff.objects.in_bulk(staff_ids) if staff_ids else {}

        # Build timeline entries for cost lines
        for cost_set in cost_sets:
            for cost_line in cost_set.cost_lines.all():
                # Get staff name from bulk-fetched map
                staff_name = None
                if staff_id := cost_line.ext_refs.get("staff_id"):
                    try:
                        staff_uuid = UUID(str(staff_id))
                        if staff := staff_map.get(staff_uuid):
                            staff_name = staff.get_display_full_name()
                    except (ValueError, TypeError):
                        pass  # Already logged warning above

                # Build description based on cost line kind
                description = cost_line.desc
                if cost_line.kind == "time":
                    hours = float(cost_line.quantity)
                    description = f"{description} ({hours:.2f} hours)"
                elif cost_line.kind == "material":
                    qty = float(cost_line.quantity)
                    description = f"{description} (qty: {qty:.3f})"

                # Common fields for both created and updated entries
                common_fields = {
                    "id": cost_line.id,
                    "description": description,
                    "staff": staff_name,
                    "event_type": None,
                    "cost_set_kind": cost_set.kind,
                    "costline_kind": cost_line.kind,
                    "quantity": cost_line.quantity,
                    "unit_cost": cost_line.unit_cost,
                    "unit_rev": cost_line.unit_rev,
                    "total_cost": cost_line.total_cost,
                    "total_rev": cost_line.total_rev,
                    "created_at": cost_line.created_at,
                    "updated_at": cost_line.updated_at,
                }

                # Create entry for costline creation
                timeline_entries.append(
                    {
                        **common_fields,
                        "timestamp": cost_line.created_at,
                        "entry_type": "costline_created",
                    }
                )

                # Create separate entry for update if it's different from creation
                # (allowing 1 second tolerance for auto-save timestamps)
                if (
                    cost_line.updated_at
                    and (cost_line.updated_at - cost_line.created_at).total_seconds()
                    > 1
                ):
                    timeline_entries.append(
                        {
                            **common_fields,
                            "timestamp": cost_line.updated_at,
                            "entry_type": "costline_updated",
                        }
                    )

        # Sort by timestamp descending (newest first)
        timeline_entries.sort(key=lambda x: x["timestamp"], reverse=True)

        return timeline_entries

    @staticmethod
    def get_weekly_metrics(week: date = None) -> list[Dict[str, Any]]:
        """
        Fetches weekly metrics for all active jobs.
        Fails early if any job processing error occurs.

        Args:
            week: Optional date parameter (ignored for now, but can be used for calculations)

        Returns:
            List of dicts with weekly metrics data, including:
                - Job information
                - Estimated hours
                - Actual hours
                - Total profit

        Raises:
            ValueError: If a job is missing data or an error occurs during processing.
        """
        if week is None:
            week = date.today()
        week_start = week - timedelta(days=week.weekday())
        week_end = week_start + timedelta(days=6)

        # Debug logging
        logger.info(
            f"Getting weekly metrics for week {week} ({week_start} to {week_end})"
        )

        job_ids_with_time_entries = (
            CostLine.objects.filter(
                cost_set__kind="actual",
                kind="time",
                accounting_date__gte=week_start,
                accounting_date__lte=week_end,
            )
            .values_list("cost_set__job_id", flat=True)
            .distinct()
        )

        # Debug logging
        job_ids_list = list(job_ids_with_time_entries)
        logger.info(
            f"Found {len(job_ids_list)} job IDs with time entries: {job_ids_list[:10]}..."
        )

        jobs = (
            Job.objects.filter(id__in=job_ids_with_time_entries)
            .select_related("client")
            .prefetch_related("people")
        )

        # Debug logging
        logger.info(f"Found {jobs.count()} jobs in database")

        # If no jobs found, check if job IDs exist at all
        if jobs.count() == 0 and len(job_ids_list) > 0:
            logger.warning(
                f"No jobs found for {len(job_ids_list)} job IDs. Checking if jobs exist..."
            )
            existing_job_count = Job.objects.filter(id__in=job_ids_list).count()
            logger.warning(
                f"Only {existing_job_count} of {len(job_ids_list)} job IDs exist in Job table"
            )

        metrics = []
        for job in jobs:
            try:
                # Get latest actual cost set summary
                latest_actual = job.latest_actual
                if not latest_actual:
                    raise ValueError(
                        f"Job {job.id} ({job.name}) has no latest_actual cost set"
                    )

                summary = latest_actual.summary or {}

                # Get estimated hours from latest estimate
                estimated_hours = 0
                if job.latest_estimate and job.latest_estimate.summary:
                    estimated_hours = job.latest_estimate.summary.get("hours", 0)

                # Get actual metrics from summary
                actual_hours = summary.get("hours", 0)
                actual_rev = summary.get("rev", 0)
                actual_cost = summary.get("cost", 0)

                profit = actual_rev - actual_cost

                job_metrics = {
                    "job_id": str(job.id),
                    "name": job.name,
                    "job_number": job.job_number,
                    "client": job.client.name if job.client else None,
                    "description": job.description,
                    "status": job.status,
                    "price_cap": job.price_cap,
                    "people": [
                        {"name": person.get_display_full_name(), "id": str(person.id)}
                        for person in job.people.all()
                    ],
                    "estimated_hours": estimated_hours,
                    "actual_hours": actual_hours,
                    "profit": profit,
                }
                metrics.append(job_metrics)

            except Exception as e:
                logger.error(f"Error processing job {job.id}: {e}")
                # Re-raise exception to fail early
                raise ValueError(f"Error processing job {job.id}: {e}") from e

        logger.info(f"Returning {len(metrics)} job metrics")
        return metrics

    @staticmethod
    def _validate_can_disable_complex_mode(job: Job) -> Dict[str, Any]:
        """
        Validates if the job can have complex mode disabled.

        Args:
            job: Job instance

        Returns:
            Dict with validation result
        """
        for pricing in job.pricings.all():
            if not pricing:
                continue

            # Check if there are multiple entries
            if (
                pricing.time_entries.count() > 1
                or pricing.material_entries.count() > 1
                or pricing.adjustment_entries.count() > 1
            ):
                return {
                    "can_disable": False,
                    "reason": (
                        "Cannot disable complex mode with multiple pricing entries"
                    ),
                }

        return {"can_disable": True, "reason": ""}

    @staticmethod
    def _get_company_defaults() -> Dict[str, Any]:
        """
        Fetches company default settings.

        Returns:
            Dict with default settings
        """
        from apps.workflow.models import CompanyDefaults

        defaults = CompanyDefaults.get_solo()
        return {
            "materials_markup": float(defaults.materials_markup),
            "time_markup": float(defaults.time_markup),
            "charge_out_rate": float(defaults.charge_out_rate),
            "wage_rate": float(defaults.wage_rate),
        }

    @staticmethod
    def _generate_update_description(
        original_values: Dict[str, Any], updated_data: Dict[str, Any]
    ) -> str:
        """
        Generates user-friendly description of job updates.
        Based on actual Job model fields.

        Args:
            original_values: Original field values before update
            updated_data: New data provided for update

        Returns:
            str: Human-readable description of changes
        """
        # Early return if no data to compare
        if not updated_data:
            return "Job details updated"

        changes = []

        # Field mappings based on actual Job model
        field_labels = {
            "name": "Job name",
            "description": "Description",
            "status": "Status",
            "priority": "Priority",
            "client_id": "Client",
            "charge_out_rate": "Charge out rate",
            "order_number": "Order number",
            "notes": "Notes",
            "contact_id": "Contact person",
            "contact_name": "Contact name",
            "contact_email": "Contact email",
            "contact_phone": "Contact phone",
            "complex_job": "Itemised billing",
            "rdti_type": "RDTI classification",
            "delivery_date": "Delivery date",
            "quote_acceptance_date": "Quote acceptance date",
            "job_is_valid": "Job validity",
            "collected": "Collection status",
            "paid": "Payment status",
        }

        # Process each updated field
        for field, new_value in updated_data.items():
            # Guard clause - skip fields not in original values
            if field not in original_values:
                continue

            original_value = original_values[field]

            # Guard clause - skip unchanged values
            if original_value == new_value:
                continue

            label = field_labels.get(field, field.replace("_", " ").title())

            # Handle specific field types with switch-case pattern
            if field == "status":
                changes.append(
                    JobRestService._format_status_change(
                        label, original_value, new_value
                    )
                )
            elif field in ["charge_out_rate"]:
                changes.append(
                    JobRestService._format_currency_change(
                        label, original_value, new_value
                    )
                )
            elif field in ["complex_job", "job_is_valid", "collected", "paid"]:
                changes.append(
                    JobRestService._format_boolean_change(
                        label, original_value, new_value
                    )
                )
            else:
                changes.append(
                    JobRestService._format_generic_change(
                        label, original_value, new_value
                    )
                )

        # Return formatted result
        if changes:
            return ", ".join(changes)
        else:
            return "Job details updated"

    @staticmethod
    def _format_status_change(label: str, old_value: str, new_value: str) -> str:
        """Formats status change with proper labels."""
        # Status labels from Job model
        status_labels = {
            "quoting": "Quoting",
            "accepted_quote": "Accepted Quote",
            "awaiting_materials": "Awaiting Materials",
            "in_progress": "In Progress",
            "on_hold": "On Hold",
            "special": "Special",
            "completed": "Completed",
            "rejected": "Rejected",
            "archived": "Archived",
        }

        old_label = status_labels.get(old_value, old_value.replace("_", " ").title())
        new_label = status_labels.get(new_value, new_value.replace("_", " ").title())

        return f"{label} changed from {old_label} to {new_label}"

    @staticmethod
    def _format_currency_change(label: str, old_value: Any, new_value: Any) -> str:
        """Formats currency field changes."""
        if old_value and new_value:
            return f"{label} updated from ${old_value} to ${new_value}"
        elif new_value:
            return f"{label} set to ${new_value}"
        else:
            return f"{label} cleared"

    @staticmethod
    def _format_boolean_change(label: str, old_value: bool, new_value: bool) -> str:
        """Formats boolean field changes."""
        if new_value:
            return f"{label} enabled"
        else:
            return f"{label} disabled"

    @staticmethod
    def _format_generic_change(label: str, old_value: Any, new_value: Any) -> str:
        """Formats generic field changes."""
        if old_value and new_value:
            return f"{label} updated"
        elif new_value:
            return f"{label} added"
        else:
            return f"{label} removed"
