"""THE job service: CRUD, delta envelope, undo, events, timeline, rejections.

One implementation per concept (ADR 0039). v1 carried two overlapping
siblings, merged here:

- ``apps/job/services/job_rest_service.py`` (1,830 lines, class
  ``JobRestService``): job CRUD, the delta-envelope validation pipeline
  (ADR 0004), undo, manual events, timeline, delta-rejection listing and
  resolution, weekly metrics, quote acceptance. Ported: everything the
  job-core API surface needs (create/update/delete, get_job_for_edit,
  get_job_summary, basic info, events, timeline, undo, accept-quote,
  rejection listing/grouping/resolution). Deferred to later sub-slices:
  ``get_weekly_metrics`` (costing reports), ``toggle_complex_job`` (no v1
  route), ``get_job_quote``/``get_job_invoices`` endpoints (accounting
  slice — their serialisation lives here already for the job payload).
- ``apps/job/services/job_service.py`` (156 lines, module functions):
  ``get_paid_complete_jobs``/``archive_complete_jobs`` (month-end archive
  screen), ``update_completion_checklist`` (finish endpoint),
  ``recalculate_job_invoicing_state``/``get_job_total_value`` (accounting),
  ``JobStaffService`` (kanban assignment — ported in 3b-3 as
  ``assign_staff_to_job``/``remove_staff_from_job`` below). The remaining
  functions are consumers of later sub-slices and port here with them.

Serialisation note: v1 shaped responses with DRF serializers
(``job_serializer.py``, ``costing_serializer.py``). v2 keeps response shaping
in this service as plain data builders (house pattern:
``apps/company/services``); the pydantic schemas in ``apps/job/schemas.py``
are the wire contract. v1 duplicated the undo-description logic in three
places (JobEventSerializer, TimelineEntrySerializer, get_job_timeline); v2
has exactly one ``_undo_info`` (ADR 0039).
"""

import hashlib
import json
import logging
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import singledispatch
from typing import TypedDict
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import (
    Case,
    Count,
    F,
    IntegerField,
    Max,
    Min,
    OuterRef,
    Prefetch,
    Subquery,
    Value,
    When,
)
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.accounting.models import Invoice, Quote
from apps.accounts.models import Staff
from apps.core.errors import AppErrorContext, persist_app_error
from apps.core.etag import (
    PreconditionFailedError,
    generate_updated_at_etag,
    if_match_satisfied,
    updated_at_etag_value,
)
from apps.core.models import CompanyDefaults
from apps.job.enums import RDTIType, SpeedQualityTradeoff
from apps.job.models import (
    Job,
    JobDeltaRejection,
    JobEvent,
    JobFile,
    JobLabourRate,
    LabourSubtype,
    QuoteSpreadsheet,
)
from apps.job.models.costing import CostLine, CostSet
from apps.job.services.delta_checksum import compute_job_delta_checksum, normalise_value
from apps.job.services.time_entry_rates import price_time_entry
from apps.purchasing.models import Stock

logger = logging.getLogger(__name__)


class DeltaValidationError(PreconditionFailedError):
    """Raised when the delta payload fails checksum or before-state validation."""

    def __init__(
        self,
        message: str,
        *,
        current_values: dict[str, object] | None = None,
        server_checksum: str | None = None,
    ) -> None:
        """Carry the server-side state so the rejection record can explain itself."""
        super().__init__(message)
        self.current_values = current_values or {}
        self.server_checksum = server_checksum


class InvalidDeltaError(ValueError):
    """A structurally invalid delta payload, carrying rejection context."""

    def __init__(self, message: str, *, reason: str, detail: dict[str, object]) -> None:
        """Store the reason/detail persisted to JobDeltaRejection."""
        super().__init__(message)
        self.reason = reason
        self.detail = detail


@dataclass
class JobDeltaPayload:
    """Structured representation of the delta envelope submitted by the client.

    A lightweight dataclass (instead of passing schema instances around) so the
    service layer operates on a normalised structure regardless of the caller.
    ``server_checksum``/``current_values`` are validation telemetry filled in by
    ``_validate_delta_payload`` (v1 smuggled these via ``setattr``).
    """

    change_id: str
    fields: tuple[str, ...]
    before: dict[str, object]
    after: dict[str, object]
    before_checksum: str
    actor_id: str | None = None
    made_at: datetime | str | None = None
    job_id: str | None = None
    etag: str | None = None
    undo_of_change_id: str | None = None
    server_checksum: str | None = None
    current_values: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "JobDeltaPayload":
        """Build a payload from a JSON mapping, failing early on bad structure."""
        required_keys = {"change_id", "fields", "before", "after", "before_checksum"}
        missing = required_keys - payload.keys()
        if missing:
            raise ValueError(f"Missing required delta fields: {', '.join(sorted(missing))}")

        fields_value = payload.get("fields") or []
        if not isinstance(fields_value, Iterable) or isinstance(fields_value, (str, bytes)):
            # ValueError (not TypeError): payload validation answers 400.
            raise ValueError("Delta 'fields' must be a list of field names")  # noqa: TRY004

        fields_tuple = tuple(str(field_name) for field_name in fields_value)
        if not fields_tuple:
            raise ValueError("Delta 'fields' cannot be empty")

        before = payload.get("before") or {}
        after = payload.get("after") or {}
        if not isinstance(before, Mapping) or not isinstance(after, Mapping):
            # ValueError (not TypeError): payload validation answers 400.
            raise ValueError("Delta 'before' and 'after' must be objects")  # noqa: TRY004

        made_at = payload.get("made_at")
        if made_at is not None and not isinstance(made_at, (datetime, str)):
            # ValueError (not TypeError): payload validation answers 400.
            raise ValueError("Delta 'made_at' must be a datetime or ISO string")

        return cls(
            change_id=str(payload["change_id"]),
            fields=fields_tuple,
            before={str(k): v for k, v in before.items()},
            after={str(k): v for k, v in after.items()},
            before_checksum=str(payload["before_checksum"]),
            actor_id=str(payload["actor_id"]) if payload.get("actor_id") else None,
            made_at=made_at,
            job_id=str(payload["job_id"]) if payload.get("job_id") else None,
            etag=str(payload["etag"]) if payload.get("etag") else None,
            undo_of_change_id=(
                str(payload["undo_of_change_id"]) if payload.get("undo_of_change_id") else None
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation of the envelope contents."""
        return {
            "change_id": self.change_id,
            "fields": list(self.fields),
            "before": self.before,
            "after": self.after,
            "before_checksum": self.before_checksum,
            "actor_id": self.actor_id,
            "made_at": (
                self.made_at.isoformat() if isinstance(self.made_at, datetime) else self.made_at
            ),
            "job_id": self.job_id,
            "etag": self.etag,
            "undo_of_change_id": self.undo_of_change_id,
        }


@singledispatch
def _to_json_safe(value: object) -> object:
    """Convert a value to a JSON-serialisable form (v1 parity fallback)."""
    logger.warning(
        "[JSON_SERIALIZATION] Unhandled type in _to_json_safe: %s with value: %r",
        type(value).__name__,
        value,
    )
    return value


@_to_json_safe.register(str)
@_to_json_safe.register(int)
@_to_json_safe.register(float)
@_to_json_safe.register(bool)
@_to_json_safe.register(type(None))
def _json_from_primitive(value: str | int | float | bool | None) -> object:
    return value


@_to_json_safe.register(dict)
def _json_from_dict(value: dict[object, object]) -> dict[str, object]:
    return {str(key): _to_json_safe(sub_value) for key, sub_value in value.items()}


@_to_json_safe.register(list)
@_to_json_safe.register(tuple)
@_to_json_safe.register(set)
def _json_from_iterable(value: Iterable[object]) -> list[object]:
    return [_to_json_safe(item) for item in value]


@_to_json_safe.register(datetime)
@_to_json_safe.register(date)
def _json_from_date(value: datetime | date) -> str:
    return value.isoformat()


@_to_json_safe.register(Decimal)
def _json_from_decimal(value: Decimal) -> str:
    return format(value, "f")


@_to_json_safe.register(UUID)
def _json_from_uuid(value: UUID) -> str:
    return str(value)


# ── Serialisation data shapes (v1 DRF serializer output, verbatim keys) ──


class CompanyDefaultsJobDetailData(TypedDict):
    """v1 CompanyDefaultsJobDetailSerializer row."""

    materials_markup: float
    time_markup: float
    wage_rate: float


class CostLineData(TypedDict):
    """v1 CostLineSerializer row (COSTLINE_API_FIELDS + totals)."""

    id: UUID
    kind: str
    desc: str | None
    quantity: Decimal
    unit_cost: Decimal
    unit_rev: Decimal
    ext_refs: dict[str, object]
    meta: dict[str, object]
    created_at: datetime
    updated_at: datetime
    accounting_date: date
    xero_time_id: str | None
    xero_expense_id: str | None
    xero_last_modified: datetime | None
    xero_last_synced: datetime | None
    approved: bool
    xero_pay_item: UUID | None
    staff: UUID | None
    entry_seq: int | None
    labour_subtype: UUID | None
    total_cost: float
    total_rev: float


class CostSetSummaryData(TypedDict):
    """The served cost-set summary: exactly these four keys.

    v1 CostSetSummarySerializer / JobCostSetSummarySerializer. Internal
    summary keys (notably ``revisions``, the archived quote history) are
    storage-only and must never appear on cost-set/job-detail reads
    (adversarial review 2026-08-02); revisions are served only by the
    quote-revise GET.
    """

    cost: float
    rev: float
    hours: float
    profitMargin: float | None


class CostSetData(TypedDict):
    """v1 CostSetSerializer row (summary enriched with profitMargin)."""

    id: str
    job: UUID
    kind: str
    rev: int
    summary: CostSetSummaryData
    created: datetime
    cost_lines: list[CostLineData]


class JobFileData(TypedDict):
    """v1 JobFileSerializer row."""

    id: UUID
    filename: str
    mime_type: str | None
    uploaded_at: datetime
    status: str
    print_on_jobsheet: bool
    size: int | None
    download_url: str
    thumbnail_url: str | None


class QuoteSheetData(TypedDict):
    """v1 QuoteSpreadsheetSerializer row."""

    id: UUID
    sheet_id: str | None
    sheet_url: str | None
    tab: str | None
    job_id: str
    job_number: int
    job_name: str


class InvoiceData(TypedDict):
    """v1 InvoiceSerializer row."""

    id: UUID
    xero_id: UUID
    number: str
    status: str
    date: date
    due_date: date | None
    total_excl_tax: float
    total_incl_tax: float
    amount_due: float
    tax: float
    online_url: str | None


class QuoteData(TypedDict):
    """v1 QuoteSerializer row."""

    id: UUID
    xero_id: UUID
    status: str
    date: date
    total_excl_tax: float
    total_incl_tax: float
    online_url: str | None


class XeroQuoteData(TypedDict):
    """v1 XeroQuoteSerializer row (status and URL only)."""

    status: str
    online_url: str | None


class XeroInvoiceData(TypedDict):
    """v1 XeroInvoiceSerializer row (number, status, URL only)."""

    number: str
    status: str
    online_url: str | None


class JobEventData(TypedDict):
    """v1 JobEventSerializer row (fields + computed undo support)."""

    id: UUID
    timestamp: datetime
    staff: str | None
    event_type: str
    schema_version: int
    change_id: UUID | None
    delta_before: dict[str, object] | None
    delta_after: dict[str, object] | None
    delta_meta: dict[str, object] | None
    delta_checksum: str | None
    detail: dict[str, object]
    description: str
    can_undo: bool
    undo_description: str | None


class JobDetailData(TypedDict):
    """v1 JobSerializer row."""

    id: UUID
    name: str
    company_id: UUID | None
    company_name: str | None
    person_id: UUID | None
    person_name: str | None
    job_number: int
    notes: str | None
    order_number: str | None
    created_at: datetime
    updated_at: datetime
    description: str | None
    latest_estimate: CostSetData | None
    latest_quote: CostSetData | None
    latest_actual: CostSetData | None
    job_status: str
    delivery_date: date | None
    paid: bool
    quote_acceptance_date: datetime | None
    job_is_valid: bool
    job_files: list[JobFileData]
    pricing_methodology: str
    price_cap: Decimal | None
    speed_quality_tradeoff: str
    quote_sheet: QuoteSheetData | None
    quoted: bool
    fully_invoiced: bool
    quote: QuoteData | None
    invoices: list[InvoiceData]
    xero_quote: XeroQuoteData | None
    xero_invoices: list[XeroInvoiceData]
    shop_job: bool
    rejected_flag: bool
    rdti_type: str | None
    default_xero_pay_item_id: UUID | None
    default_xero_pay_item_name: str | None
    min_people: int
    max_people: int
    is_urgent: bool


class JobEditData(TypedDict):
    """v1 JobDataSerializer payload (the ``data`` of getFullJob)."""

    job: JobDetailData
    events: list[JobEventData]
    company_defaults: CompanyDefaultsJobDetailData


class JobHeaderData(TypedDict):
    """v1 JobHeaderResponseSerializer row (JOB_DIRECT_FIELDS + joins)."""

    job_id: UUID
    company_id: UUID | None
    company_name: str | None
    person_id: UUID | None
    person_name: str | None
    quoted: bool
    default_xero_pay_item_id: UUID | None
    default_xero_pay_item_name: str | None
    job_number: int
    name: str
    description: str | None
    status: str
    order_number: str | None
    delivery_date: date | None
    notes: str | None
    pricing_methodology: str
    price_cap: Decimal | None
    speed_quality_tradeoff: str
    fully_invoiced: bool
    quote_acceptance_date: datetime | None
    paid: bool
    rejected_flag: bool
    rdti_type: str | None
    min_people: int
    max_people: int
    is_urgent: bool


class JobBasicInformationData(TypedDict):
    """v1 JobBasicInformationResponseSerializer row."""

    description: str
    delivery_date: str | None
    order_number: str
    notes: str


# ── Serialisation builders ───────────────────────────────────────────────

# Map internal field names to user-friendly labels for undo descriptions.
_UNDO_FIELD_LABELS: dict[str, str] = {
    "name": "job name",
    "description": "description",
    "status": "status",
    "order_number": "order number",
    "notes": "notes",
    "company_id": "company",
    "person_id": "person",
    "delivery_date": "delivery date",
    "job_status": "status",
    "paid": "payment status",
    "job_is_valid": "validity",
    "rejected_flag": "rejection status",
    "rdti_type": "RDTI classification",
    "pricing_methodology": "pricing method",
}


def _undo_info(event: JobEvent) -> tuple[bool, str | None]:
    """Return (can_undo, undo_description) for an event (single implementation)."""
    can_undo = (
        event.schema_version == 1
        and event.change_id is not None
        and event.delta_before is not None
        and event.delta_after is not None
    )
    if not can_undo:
        return False, None

    meta = event.delta_meta or {}
    fields = meta.get("fields", [])
    if not fields:
        return True, f"Undo '{event.description}'"

    field_names = [
        _UNDO_FIELD_LABELS.get(str(field_name), str(field_name).replace("_", " "))
        for field_name in fields
    ]
    if len(field_names) == 1:
        return True, f"Undo change to {field_names[0]}"
    if len(field_names) <= 3:
        return True, f"Undo changes to {', '.join(field_names[:-1])} and {field_names[-1]}"
    return True, f"Undo changes to {len(field_names)} fields"


def job_event_data(event: JobEvent) -> JobEventData:
    """Serialise one JobEvent (v1 JobEventSerializer shape)."""
    can_undo, undo_description = _undo_info(event)
    return {
        "id": event.id,
        "timestamp": event.timestamp,
        "staff": event.staff.get_display_full_name() if event.staff else None,
        "event_type": event.event_type,
        "schema_version": event.schema_version,
        "change_id": event.change_id,
        "delta_before": event.delta_before,
        "delta_after": event.delta_after,
        "delta_meta": event.delta_meta,
        "delta_checksum": event.delta_checksum,
        "detail": event.detail,
        "description": event.description,
        "can_undo": can_undo,
        "undo_description": undo_description,
    }


def _summary_with_margin(cost_set: CostSet) -> CostSetSummaryData:
    """Serve exactly {cost, rev, hours, profitMargin} from the stored summary.

    The single margin implementation: (rev - cost) / rev * 100, 0.0 on a zero
    denominator (v1 CostSetSummarySerializer; costs/summary standardised onto
    it by user decision 2026-08-02). Storage-only keys such as ``revisions``
    never leak (adversarial review 2026-08-02).
    """
    summary_raw = cost_set.summary
    if not summary_raw:
        logger.error("CostSet %s missing required summary data", cost_set.id)
        return {"cost": 0.0, "rev": 0.0, "hours": 0.0, "profitMargin": 0.0}
    rev_raw = summary_raw.get("rev", 0)
    cost_raw = summary_raw.get("cost", 0)
    hours_raw = summary_raw.get("hours", 0)
    rev = float(rev_raw) if isinstance(rev_raw, (int, float)) else 0.0
    cost = float(cost_raw) if isinstance(cost_raw, (int, float)) else 0.0
    hours = float(hours_raw) if isinstance(hours_raw, (int, float)) else 0.0
    return {
        "cost": cost,
        "rev": rev,
        "hours": hours,
        "profitMargin": ((rev - cost) / rev) * 100 if rev > 0 else 0.0,
    }


def cost_line_data(line: CostLine) -> CostLineData:
    """Serialise one CostLine (v1 CostLineSerializer shape)."""
    return {
        "id": line.id,
        "kind": line.kind,
        "desc": line.desc,
        "quantity": line.quantity,
        "unit_cost": line.unit_cost,
        "unit_rev": line.unit_rev,
        "ext_refs": line.ext_refs,
        "meta": line.meta,
        "created_at": line.created_at,
        "updated_at": line.updated_at,
        "accounting_date": line.accounting_date,
        "xero_time_id": line.xero_time_id,
        "xero_expense_id": line.xero_expense_id,
        "xero_last_modified": line.xero_last_modified,
        "xero_last_synced": line.xero_last_synced,
        "approved": line.approved,
        "xero_pay_item": line.xero_pay_item_id,
        "staff": line.staff_id,
        "entry_seq": line.entry_seq,
        "labour_subtype": line.labour_subtype_id,
        "total_cost": float(line.total_cost),
        "total_rev": float(line.total_rev),
    }


def cost_set_data(cost_set: CostSet, *, include_lines: bool = True) -> CostSetData:
    """Serialise one CostSet (v1 CostSetSerializer / CostSetSummaryOnlySerializer)."""
    lines = [cost_line_data(line) for line in cost_set.cost_lines.all()] if include_lines else []
    return {
        "id": str(cost_set.id),
        "job": cost_set.job_id,
        "kind": cost_set.kind,
        "rev": cost_set.rev,
        "summary": _summary_with_margin(cost_set),
        "created": cost_set.created,
        "cost_lines": lines,
    }


def job_file_data(job_file: JobFile) -> JobFileData:
    """Serialise one JobFile (v1 JobFileSerializer shape; file endpoints in api.py)."""
    # v1 built the URLs with reverse("jobs:job_file_detail"); v2 emits the
    # same shape literally (the ninja routes below serve these paths).
    thumbnail_path = job_file.thumbnail_path
    return {
        "id": job_file.id,
        "filename": job_file.filename,
        "mime_type": job_file.mime_type,
        "uploaded_at": job_file.uploaded_at,
        "status": job_file.status,
        "print_on_jobsheet": job_file.print_on_jobsheet,
        "size": job_file.size,
        "download_url": f"/api/job/jobs/{job_file.job_id}/files/{job_file.id}/",
        "thumbnail_url": (
            f"/api/job/jobs/{job_file.job_id}/files/{job_file.id}/thumbnail/"
            if thumbnail_path
            else None
        ),
    }


def _quote_sheet_data(sheet: QuoteSpreadsheet) -> QuoteSheetData:
    sheet_job = sheet.job
    if sheet_job is None:
        raise ValueError(f"QuoteSpreadsheet {sheet.id} has no job; cannot serialise it")
    return {
        "id": sheet.id,
        "sheet_id": sheet.sheet_id,
        "sheet_url": sheet.sheet_url,
        "tab": sheet.tab,
        "job_id": str(sheet_job.id),
        "job_number": sheet_job.job_number,
        "job_name": sheet_job.name,
    }


def _invoice_data(invoice: Invoice) -> InvoiceData:
    return {
        "id": invoice.id,
        "xero_id": invoice.xero_id,
        "number": invoice.number,
        "status": invoice.status,
        "date": invoice.date,
        "due_date": invoice.due_date,
        "total_excl_tax": float(invoice.total_excl_tax),
        "total_incl_tax": float(invoice.total_incl_tax),
        "amount_due": float(invoice.amount_due),
        "tax": float(invoice.tax),
        "online_url": invoice.online_url,
    }


def _quote_data(quote: Quote) -> QuoteData:
    return {
        "id": quote.id,
        "xero_id": quote.xero_id,
        "status": quote.status,
        "date": quote.date,
        "total_excl_tax": float(quote.total_excl_tax),
        "total_incl_tax": float(quote.total_incl_tax),
        "online_url": quote.online_url,
    }


def _job_quote(job: Job) -> Quote | None:
    try:
        return job.quote
    except Quote.DoesNotExist:
        return None


def job_detail_data(job: Job, *, summary_only: bool = False) -> JobDetailData:
    """Serialise one Job (v1 JobSerializer / JobSummarySerializer shape)."""
    quote = _job_quote(job)
    invoices = list(job.invoices.all())
    quote_sheet = getattr(job, "quote_sheet", None)
    return {
        "id": job.id,
        "name": job.name,
        "company_id": job.company_id,
        "company_name": job.company.name if job.company else None,
        "person_id": job.person_id,
        "person_name": job.person.name if job.person else None,
        "job_number": job.job_number,
        "notes": job.notes,
        "order_number": job.order_number,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "description": job.description,
        "latest_estimate": cost_set_data(job.latest_estimate, include_lines=not summary_only),
        "latest_quote": cost_set_data(job.latest_quote, include_lines=not summary_only),
        "latest_actual": cost_set_data(job.latest_actual, include_lines=not summary_only),
        "job_status": job.status,
        "delivery_date": job.delivery_date,
        "paid": job.paid,
        "quote_acceptance_date": job.quote_acceptance_date,
        "job_is_valid": job.job_is_valid,
        "job_files": [job_file_data(job_file) for job_file in job.files.all()],
        "pricing_methodology": job.pricing_methodology,
        "price_cap": job.price_cap,
        "speed_quality_tradeoff": job.speed_quality_tradeoff,
        "quote_sheet": _quote_sheet_data(quote_sheet) if quote_sheet else None,
        "quoted": job.quoted,
        "fully_invoiced": job.fully_invoiced,
        "quote": _quote_data(quote) if quote else None,
        "invoices": [_invoice_data(invoice) for invoice in invoices],
        "xero_quote": ({"status": quote.status, "online_url": quote.online_url} if quote else None),
        "xero_invoices": [
            {"number": invoice.number, "status": invoice.status, "online_url": invoice.online_url}
            for invoice in invoices
        ],
        "shop_job": job.shop_job,
        "rejected_flag": job.rejected_flag,
        "rdti_type": job.rdti_type,
        "default_xero_pay_item_id": job.default_xero_pay_item_id,
        "default_xero_pay_item_name": (
            job.default_xero_pay_item.name if job.default_xero_pay_item else None
        ),
        "min_people": job.min_people,
        "max_people": job.max_people,
        "is_urgent": job.is_urgent,
    }


def _company_defaults_job_detail() -> CompanyDefaultsJobDetailData:
    defaults = CompanyDefaults.get_solo()
    return {
        "materials_markup": float(defaults.materials_markup),
        "time_markup": float(defaults.time_markup),
        "wage_rate": float(defaults.wage_rate),
    }


def job_header_data(job: Job) -> JobHeaderData:
    """Serialise the header payload (v1 JobHeaderResponseSerializer shape)."""
    return {
        "job_id": job.id,
        "company_id": job.company_id,
        "company_name": job.company.name if job.company else None,
        "person_id": job.person_id,
        "person_name": job.person.name if job.person else None,
        "quoted": job.quoted,
        "default_xero_pay_item_id": job.default_xero_pay_item_id,
        "default_xero_pay_item_name": (
            job.default_xero_pay_item.name if job.default_xero_pay_item else None
        ),
        "job_number": job.job_number,
        "name": job.name,
        "description": job.description,
        "status": job.status,
        "order_number": job.order_number,
        "delivery_date": job.delivery_date,
        "notes": job.notes,
        "pricing_methodology": job.pricing_methodology,
        "price_cap": job.price_cap,
        "speed_quality_tradeoff": job.speed_quality_tradeoff,
        "fully_invoiced": job.fully_invoiced,
        "quote_acceptance_date": job.quote_acceptance_date,
        "paid": job.paid,
        "rejected_flag": job.rejected_flag,
        "rdti_type": job.rdti_type,
        "min_people": job.min_people,
        "max_people": job.max_people,
        "is_urgent": job.is_urgent,
    }


# ── Create ───────────────────────────────────────────────────────────────


class JobCreateData(TypedDict, total=False):
    """Validated job-creation payload (v1 JobCreateSerializer fields)."""

    name: str
    company_id: UUID | str
    description: str
    order_number: str
    notes: str
    person_id: UUID | str | None
    pricing_methodology: str
    estimated_materials: Decimal
    estimated_time: Decimal
    is_urgent: bool


def create_job(data: JobCreateData, user: Staff) -> Job:  # noqa: C901, PLR0912, PLR0915 -- v1 control flow ported verbatim
    """Create a Job with its initial estimate (and quote) cost lines."""
    # Guard clauses - early return for validations
    from apps.company.models import (  # noqa: PLC0415 -- import at use, matching Job model's pattern
        Company,
        Person,
    )

    if not data.get("name"):
        raise ValueError("Job name is required")
    if not data.get("company_id"):
        raise ValueError("Company is required")

    try:
        company = Company.objects.get(id=data["company_id"])
    except Company.DoesNotExist as exc:
        raise ValueError("Company not found") from exc

    if not company.allow_jobs:
        raise ValueError(
            f"Company '{company.name}' is not permitted for jobs. "
            f"Update the company to allow jobs if this is wrong."
        )

    job = Job(name=data["name"], company=company, created_by=user)

    # Optional fields - only if provided
    if data.get("description"):
        job.description = data["description"]
    if data.get("order_number"):
        job.order_number = data["order_number"]
    if data.get("notes"):
        job.notes = data["notes"]
    if data.get("pricing_methodology"):
        job.pricing_methodology = data["pricing_methodology"]

    person_id = data.get("person_id")
    if person_id:
        try:
            job.person = Person.objects.get(id=person_id)
        except Person.DoesNotExist as exc:
            raise ValueError(f"Person with id {person_id} not found") from exc

    if "is_urgent" in data:
        job.is_urgent = data["is_urgent"]

    estimated_materials = data.get("estimated_materials")
    estimated_time = data.get("estimated_time")
    if estimated_materials is None:
        raise ValueError("estimated_materials is required")
    if estimated_time is None:
        raise ValueError("estimated_time is required")

    with transaction.atomic():
        # Job.save() resolves the default "Ordinary Time" pay item (the one
        # implementation of that concept — v1 duplicated the lookup here).
        job.save(staff=user)
        ordinary_time = job.default_xero_pay_item

        # Create job creation event (kept out of Job.save() to prevent
        # duplicates between model and service layers)
        JobEvent.objects.create(
            job=job,
            event_type="job_created",
            detail={
                "job_name": job.name,
                "company_name": job.company.name if job.company else "Shop Job",
                "person_name": job.person.name if job.person else None,
                "initial_status": job.get_status_display(),
                "pricing_methodology": job.get_pricing_methodology_display(),
            },
            staff=user,
            delta_after={"status": job.status},
        )

        # Get the estimate CostSet (already created by job.save())
        estimate_costset = job.cost_sets.get(kind="estimate")

        company_defaults = CompanyDefaults.get_solo()
        wage_rate = company_defaults.wage_rate.quantize(Decimal("0.01"))

        # Per-subtype charge-out rates were seeded by job.save()
        workshop_subtype = LabourSubtype.default_workshop()
        office_subtype = LabourSubtype.default_non_workshop()
        workshop_rate = job.labour_rates.get(labour_subtype=workshop_subtype).charge_out_rate
        office_rate = job.labour_rates.get(labour_subtype=office_subtype).charge_out_rate

        # estimated_materials is entered as retail price (what customer pays);
        # convert to cost using the standard 20% markup (retail = cost * 1.2).
        materials_markup_multiplier = Decimal("1.2")
        materials_cost = (estimated_materials / materials_markup_multiplier).quantize(
            Decimal("0.01")
        )

        CostLine.objects.create(
            cost_set=estimate_costset,
            kind="material",
            desc="Estimated materials",
            quantity=Decimal("1.000"),
            unit_cost=materials_cost,
            unit_rev=estimated_materials,
            accounting_date=timezone.localdate(),
        )
        CostLine.objects.create(
            cost_set=estimate_costset,
            kind="time",
            desc="Estimated workshop time",
            quantity=estimated_time,
            unit_cost=wage_rate,
            unit_rev=workshop_rate,
            accounting_date=timezone.localdate(),
            xero_pay_item=ordinary_time,
            labour_subtype=workshop_subtype,
        )

        # Calculate office time (1:8 ratio, rounded up to quarter hours)
        office_time_hours = Decimal(str(math.ceil(float(estimated_time) / 8 * 4) / 4))
        CostLine.objects.create(
            cost_set=estimate_costset,
            kind="time",
            desc="Estimated office time",
            quantity=office_time_hours,
            unit_cost=wage_rate,
            unit_rev=office_rate,
            accounting_date=timezone.localdate(),
            xero_pay_item=ordinary_time,
            labour_subtype=office_subtype,
        )

        # For fixed_price jobs, copy estimate lines to the quote CostSet
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
                    ext_refs=estimate_line.ext_refs.copy() if estimate_line.ext_refs else {},
                    meta=estimate_line.meta.copy() if estimate_line.meta else {},
                    xero_pay_item_id=estimate_line.xero_pay_item_id,
                    labour_subtype_id=estimate_line.labour_subtype_id,
                )

    return job


# ── Reads ────────────────────────────────────────────────────────────────


def get_job_for_edit(job_id: UUID) -> JobEditData:
    """Fetch complete Job data for editing (job + events + company defaults)."""
    try:
        job = Job.objects.select_related("company").get(id=job_id)
    except Job.DoesNotExist as exc:
        raise ValueError(f"Job with id {job_id} not found") from exc

    events = JobEvent.objects.filter(job=job).select_related("staff").order_by("-timestamp")
    return {
        "job": job_detail_data(job),
        "events": [job_event_data(event) for event in events],
        "company_defaults": _company_defaults_job_detail(),
    }


def get_job_summary(job_id: UUID) -> JobEditData:
    """Return the get_job_for_edit shape, but with cost_lines: [] and events: []."""
    try:
        job = Job.objects.select_related("company").get(id=job_id)
    except Job.DoesNotExist as exc:
        raise ValueError(f"Job with id {job_id} not found") from exc

    return {
        "job": job_detail_data(job, summary_only=True),
        "events": [],
        "company_defaults": _company_defaults_job_detail(),
    }


def get_job_basic_information(job_id: UUID) -> JobBasicInformationData:
    """Fetch description, delivery date, order number and notes for a job."""
    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist as exc:
        raise ValueError(f"Job with id {job_id} not found") from exc

    return {
        "description": job.description or "",
        "delivery_date": job.delivery_date.isoformat() if job.delivery_date else None,
        "order_number": job.order_number or "",
        "notes": job.notes or "",
    }


# ── Delta rejections: recording, listing, grouping, resolution ───────────


def _serialise_detail(detail: object) -> str | None:
    if detail in (None, ""):
        return None
    converted = _to_json_safe(detail)
    if isinstance(converted, (dict, list)):
        return json.dumps(converted)
    return str(converted)[:2000]


def _safe_uuid(value: object) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _looks_like_delta_payload(data: object) -> bool:
    if not isinstance(data, Mapping):
        return False
    required_keys = {"change_id", "fields", "before", "after", "before_checksum"}
    return required_keys.issubset(data.keys())


def record_delta_rejection(  # noqa: PLR0913 -- v1 signature ported verbatim
    job: Job | None,
    staff: Staff | None,
    *,
    reason: str,
    detail: object = "",
    envelope: Mapping[str, object] | None = None,
    change_id: str | None = None,
    checksum: str | None = None,
    request_etag: str | None = None,
    request_ip: str | None = None,
) -> None:
    """Persist information about a rejected delta for forensic analysis."""
    change_uuid = _safe_uuid(change_id)
    clean_reason = (reason or "")[:255]
    clean_detail = _serialise_detail(detail)
    clean_envelope = _to_json_safe(dict(envelope) if envelope else {})
    clean_checksum = checksum or None
    clean_request_etag = request_etag[:128] if request_etag else None

    if job and change_uuid:
        JobDeltaRejection.objects.update_or_create(
            job=job,
            change_id=change_uuid,
            defaults={
                "job": job,
                "staff": staff,
                "reason": clean_reason,
                "detail": clean_detail,
                "envelope": clean_envelope,
                "checksum": clean_checksum,
                "request_etag": clean_request_etag,
                "request_ip": request_ip,
            },
        )
    else:
        JobDeltaRejection.objects.create(
            job=job,
            staff=staff,
            change_id=change_uuid,
            reason=clean_reason,
            detail=clean_detail,
            envelope=clean_envelope,
            checksum=clean_checksum,
            request_etag=clean_request_etag,
            request_ip=request_ip,
        )


class DeltaRejectionListData(TypedDict):
    """v1 JobDeltaRejectionListResponseSerializer payload (model rows)."""

    count: int
    next: str | None
    previous: str | None
    results: list[JobDeltaRejection]


def list_job_delta_rejections(
    *,
    job_id: UUID | str | None = None,
    resolved: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> DeltaRejectionListData:
    """Return paginated delta rejection records, optionally filtered by job.

    ``resolved=None`` applies no resolved filter (show all), matching the
    System tab's individual-list semantics; ``True``/``False`` narrow to that
    state.
    """
    if limit <= 0:
        limit = 1
    limit = min(limit, 200)
    offset = max(offset, 0)

    queryset = JobDeltaRejection.objects.select_related("job", "staff").order_by("-created_at")
    if job_id:
        queryset = queryset.filter(job_id=job_id)
    if resolved is not None:
        queryset = queryset.filter(resolved=resolved)
    total = queryset.count()
    results = list(queryset[offset : offset + limit])

    return {
        "count": total,
        "next": str(offset + limit) if offset + limit < total else None,
        "previous": str(max(offset - limit, 0)) if offset > 0 else None,
        "results": results,
    }


class GroupedDeltaRejectionRow(TypedDict):
    """One grouped JobDeltaRejection row (grouped by reason)."""

    fingerprint: str
    reason: str
    occurrence_count: int
    first_seen: datetime
    last_seen: datetime
    latest_id: UUID
    resolved: bool


class GroupedDeltaRejectionListData(TypedDict):
    """Paginated grouped delta-rejection payload."""

    count: int
    next: str | None
    previous: str | None
    results: list[GroupedDeltaRejectionRow]


def list_grouped_job_delta_rejections(
    *,
    limit: int = 50,
    offset: int = 0,
    job_id: str | None = None,
    resolved: bool | None = None,
) -> GroupedDeltaRejectionListData:
    """Group delta rejections by reason for the System-tab triage view."""
    if limit <= 0:
        limit = 1
    limit = min(limit, 200)
    offset = max(offset, 0)

    queryset = JobDeltaRejection.objects.all()
    # Groups are scoped to a single resolved state, so every row in the
    # response carries that state (defaulting to unresolved). The frontend
    # uses it to choose the Resolve vs Unresolve action per group.
    group_resolved = False if resolved is None else resolved
    queryset = queryset.filter(resolved=group_resolved)
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

    results: list[GroupedDeltaRejectionRow] = [
        {
            "fingerprint": hashlib.sha256(row["reason"].encode("utf-8")).hexdigest(),
            "reason": row["reason"],
            "occurrence_count": row["occurrence_count"],
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
            "latest_id": row["latest_id"],
            "resolved": group_resolved,
        }
        for row in rows
    ]

    return {
        "count": total,
        "next": str(offset + limit) if offset + limit < total else None,
        "previous": str(max(offset - limit, 0)) if offset > 0 else None,
        "results": results,
    }


def mark_job_delta_rejection_group_resolved(reason: str, staff: Staff) -> int:
    """Resolve every rejection sharing this exact reason string."""
    return JobDeltaRejection.objects.filter(reason=reason).update(
        resolved=True,
        resolved_by=staff,
        resolved_timestamp=timezone.now(),
    )


def mark_job_delta_rejection_group_unresolved(reason: str, staff: Staff) -> int:  # noqa: ARG001 -- v1 signature ported verbatim
    """Reopen every rejection sharing this exact reason string."""
    return JobDeltaRejection.objects.filter(reason=reason).update(
        resolved=False,
        resolved_by=None,
        resolved_timestamp=None,
    )


def _mark_group_by_fingerprint(fingerprint: str, staff: Staff, *, resolved: bool) -> int:
    """Match rows by sha256(reason) and cascade.

    Callers send the fingerprint returned by the grouped listing; this
    sidesteps client-side whitespace mangling on the raw reason (same pattern
    as v1's error_grouping._mark_group_by_fingerprint).
    """
    candidates = JobDeltaRejection.objects.filter(resolved=not resolved).values("id", "reason")
    matching_ids = [
        row["id"]
        for row in candidates
        if hashlib.sha256(row["reason"].encode("utf-8")).hexdigest() == fingerprint
    ]
    if not matching_ids:
        return 0
    return JobDeltaRejection.objects.filter(id__in=matching_ids).update(
        resolved=resolved,
        resolved_by=staff if resolved else None,
        resolved_timestamp=timezone.now() if resolved else None,
    )


def mark_job_delta_rejection_group_resolved_by_fingerprint(fingerprint: str, staff: Staff) -> int:
    """Resolve a reason group identified by its SHA-256 fingerprint."""
    return _mark_group_by_fingerprint(fingerprint, staff, resolved=True)


def mark_job_delta_rejection_group_unresolved_by_fingerprint(fingerprint: str, staff: Staff) -> int:
    """Reopen a reason group identified by its SHA-256 fingerprint."""
    return _mark_group_by_fingerprint(fingerprint, staff, resolved=False)


# ── Delta validation + update ────────────────────────────────────────────

# Map payload field names to model attribute names for validation.
_FIELD_ATTRIBUTE_MAP = {"job_status": "status"}

# Delta-updatable fields (v1 JobSerializer's writable surface). ``job_files``
# is deliberately absent: nested file updates land with the files sub-slice.
_FK_DELTA_FIELDS = {
    "company_id": "company",
    "person_id": "person",
    "default_xero_pay_item_id": "default_xero_pay_item",
}
_DATE_DELTA_FIELDS = frozenset({"delivery_date"})
_DATETIME_DELTA_FIELDS = frozenset({"quote_acceptance_date"})
_DECIMAL_DELTA_FIELDS = frozenset({"price_cap"})
_INT_DELTA_FIELDS = frozenset({"min_people", "max_people"})
_BOOL_DELTA_FIELDS = frozenset({"paid", "job_is_valid", "rejected_flag", "is_urgent"})
# Nullable text columns where the DB forbids "": NULL is the only unset.
_NULLABLE_TEXT_DELTA_FIELDS = frozenset({"description", "notes", "order_number", "rdti_type"})
_REQUIRED_TEXT_DELTA_FIELDS = frozenset({"name"})
_CHOICE_DELTA_FIELDS: dict[str, frozenset[str]] = {
    "job_status": frozenset(dict(Job.JOB_STATUS_CHOICES)),
    "pricing_methodology": frozenset(dict(Job.PRICING_METHODOLOGY_CHOICES)),
    "speed_quality_tradeoff": frozenset(SpeedQualityTradeoff.values),
    "rdti_type": frozenset(RDTIType.values),
}
_DELTA_UPDATABLE_FIELDS = (
    set(_FK_DELTA_FIELDS)
    | _DATE_DELTA_FIELDS
    | _DATETIME_DELTA_FIELDS
    | _DECIMAL_DELTA_FIELDS
    | _INT_DELTA_FIELDS
    | _BOOL_DELTA_FIELDS
    | _NULLABLE_TEXT_DELTA_FIELDS
    | _REQUIRED_TEXT_DELTA_FIELDS
    | {"job_status", "pricing_methodology", "speed_quality_tradeoff"}
)


def _get_job_field_value(job: Job, field_name: str) -> object:
    """Get the current value of a delta field from the Job model."""
    attribute_name = _FIELD_ATTRIBUTE_MAP.get(field_name, field_name)
    if not hasattr(job, attribute_name):
        raise ValueError(f"Unsupported field '{field_name}' in delta payload")
    return getattr(job, attribute_name)


def _parse_delta_date(field_name: str, value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Invalid date for '{field_name}': {value!r}") from exc
    raise ValueError(f"Invalid date for '{field_name}': {value!r}")


def _parse_delta_datetime(field_name: str, value: object) -> datetime | None:
    if value is None:
        return None
    parsed: datetime
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid datetime for '{field_name}': {value!r}") from exc
    else:
        # ValueError (not TypeError): delta validation answers 400.
        raise ValueError(f"Invalid datetime for '{field_name}': {value!r}")  # noqa: TRY004
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


# price_cap is DecimalField(max_digits=10, decimal_places=2): 8 whole digits.
_PRICE_CAP_MAX_ABS = Decimal("100000000")
_PRICE_CAP_QUANTUM = Decimal("0.01")


def _parse_delta_decimal(field_name: str, value: object) -> Decimal | None:
    """Parse a decimal delta value, enforcing the model field's bounds (400 not 500)."""
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal for '{field_name}': {value!r}") from exc
    if not parsed.is_finite():
        raise ValueError(f"Invalid decimal for '{field_name}': {value!r}")
    if parsed != parsed.quantize(_PRICE_CAP_QUANTUM):
        raise ValueError(f"'{field_name}' allows at most 2 decimal places: {value!r}")
    if abs(parsed) >= _PRICE_CAP_MAX_ABS:
        raise ValueError(f"'{field_name}' exceeds the allowed magnitude: {value!r}")
    return parsed


def _apply_delta_field(job: Job, field_name: str, value: object) -> None:  # noqa: C901, PLR0912 -- one dispatch table over the writable surface
    """Validate and assign one delta field onto the (unsaved) job instance."""
    if field_name not in _DELTA_UPDATABLE_FIELDS:
        raise ValueError(f"Unsupported field '{field_name}' in delta payload")

    if (
        field_name in _CHOICE_DELTA_FIELDS
        and value is not None
        and (not isinstance(value, str) or value not in _CHOICE_DELTA_FIELDS[field_name])
    ):
        raise ValueError(f"Invalid value for '{field_name}': {value!r}")

    if field_name in _FK_DELTA_FIELDS:
        if value is not None:
            related_field = Job._meta.get_field(_FK_DELTA_FIELDS[field_name])
            related_model = related_field.related_model
            if not isinstance(related_model, type):
                raise ValueError(f"Field '{field_name}' is not a relation")
            if not related_model._default_manager.filter(pk=value).exists():
                raise ValueError(f"{_FK_DELTA_FIELDS[field_name]} with id {value} not found")
        setattr(job, field_name, value)
    elif field_name in _DATE_DELTA_FIELDS:
        setattr(job, field_name, _parse_delta_date(field_name, value))
    elif field_name in _DATETIME_DELTA_FIELDS:
        setattr(job, field_name, _parse_delta_datetime(field_name, value))
    elif field_name in _DECIMAL_DELTA_FIELDS:
        setattr(job, field_name, _parse_delta_decimal(field_name, value))
    elif field_name in _INT_DELTA_FIELDS:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"Invalid integer for '{field_name}': {value!r}")
        if value < 0:
            # v1's serializer bounds: reject before the DB CHECK turns it into a 500.
            raise ValueError(f"'{field_name}' cannot be negative: {value!r}")
        setattr(job, field_name, value)
    elif field_name in _BOOL_DELTA_FIELDS:
        if not isinstance(value, bool):
            raise ValueError(f"Invalid boolean for '{field_name}': {value!r}")
        setattr(job, field_name, value)
    elif field_name in _NULLABLE_TEXT_DELTA_FIELDS:
        if value == "":
            # NULL is the only unset (DB CHECK forbids ""); v1's serializer
            # base rejected "" for nullable text columns the same way.
            raise ValueError(f"Field '{field_name}' cannot be blank; send null to clear it")
        if value is not None and not isinstance(value, str):
            raise ValueError(f"Invalid value for '{field_name}': {value!r}")
        setattr(job, field_name, value)
    else:
        if not isinstance(value, str) or not value:
            raise ValueError(f"Invalid value for '{field_name}': {value!r}")
        setattr(job, _FIELD_ATTRIBUTE_MAP.get(field_name, field_name), value)


def _validate_delta_payload(job: Job, delta: JobDeltaPayload, soft_fail: bool) -> None:
    """Verify the envelope's before-state against the locked DB row (ADR 0004)."""
    fields = set(delta.fields)
    if not fields:
        raise ValueError("Delta payload must specify at least one field")

    missing_before = fields - set(delta.before.keys())
    missing_after = fields - set(delta.after.keys())
    if missing_before or missing_after:
        issues: list[str] = []
        if missing_before:
            issues.append(f"missing 'before' values for {sorted(missing_before)}")
        if missing_after:
            issues.append(f"missing 'after' values for {sorted(missing_after)}")
        raise ValueError("Delta payload is inconsistent: " + "; ".join(issues))

    current_values: dict[str, object] = {
        field_name: _get_job_field_value(job, field_name) for field_name in fields
    }

    server_checksum = compute_job_delta_checksum(job.id, current_values, fields)
    delta.current_values = current_values
    delta.server_checksum = server_checksum

    if server_checksum != delta.before_checksum:
        if soft_fail:
            logger.warning(
                "[DELTA_VALIDATION] CHECKSUM MISMATCH (soft-fail): "
                "job_id=%s change_id=%s server_checksum=%s client_checksum=%s "
                "fields=%s current_values=%s delta_before=%s",
                job.id,
                delta.change_id,
                server_checksum,
                delta.before_checksum,
                sorted(fields),
                current_values,
                delta.before,
            )
        else:
            logger.error(
                "[DELTA_VALIDATION] CHECKSUM MISMATCH: job_id=%s fields=%s "
                "server=%s client=%s current_values=%s delta_before=%s",
                job.id,
                sorted(fields),
                server_checksum,
                delta.before_checksum,
                current_values,
                delta.before,
            )
            raise DeltaValidationError(
                "Delta checksum mismatch: job has changed since the delta was generated",
                current_values=current_values,
                server_checksum=server_checksum,
            )

    if not soft_fail:
        # Validate field values strictly only when not in soft-fail mode
        for field_name in fields:
            current_norm = normalise_value(current_values[field_name])
            before_norm = normalise_value(delta.before[field_name])
            if current_norm != before_norm:
                logger.error(
                    "[DELTA_VALIDATION] FIELD MISMATCH for '%s': current_norm=%s before_norm=%s",
                    field_name,
                    current_norm,
                    before_norm,
                )
                raise DeltaValidationError(
                    f"Delta before state mismatch for field '{field_name}'",
                    current_values=current_values,
                    server_checksum=server_checksum,
                )

    logger.info("[DELTA_VALIDATION] Passed for job %s, fields: %s", job.id, sorted(fields))


class _SoftFailContext(TypedDict):
    """Persistence payload for a soft-failed checksum mismatch."""

    job: Job | None
    staff: Staff | None
    reason: str
    detail: dict[str, object]
    envelope: dict[str, object]
    change_id: str
    checksum: str
    request_etag: str | None
    request_ip: str | None


def _collect_soft_fail_context(  # noqa: PLR0913 -- v1 signature + forensics request_ip
    *,
    job: Job | None,
    staff: Staff | None,
    delta_payload: JobDeltaPayload,
    request_etag: str | None,
    soft_fail: bool,
    request_ip: str | None = None,
) -> _SoftFailContext | None:
    """Build persistence payload for soft-failed checksum mismatches.

    The caller invokes ``record_delta_rejection`` outside of the main
    transaction so the entry survives rollbacks.
    """
    if not soft_fail:
        return None

    server_checksum = delta_payload.server_checksum
    if server_checksum and server_checksum != delta_payload.before_checksum:
        return {
            "job": job,
            "staff": staff,
            "reason": "Delta checksum mismatch (soft-fail)",
            "detail": {
                "server_checksum": server_checksum,
                "current_values": delta_payload.current_values,
            },
            "envelope": delta_payload.to_dict(),
            "change_id": delta_payload.change_id,
            "checksum": delta_payload.before_checksum,
            "request_etag": delta_payload.etag or request_etag,
            "request_ip": request_ip,
        }
    return None


def update_job(  # noqa: C901, PLR0912, PLR0915 -- v1 control flow ported verbatim
    job_id: UUID,
    data: Mapping[str, object],
    user: Staff,
    if_match: str,
    request_ip: str | None = None,
) -> Job:
    """Update a Job from a delta envelope with OCC (ADR 0003) + checksum (ADR 0004)."""
    if not _looks_like_delta_payload(data):
        raise ValueError("Delta envelope is required for job updates")

    try:
        delta_payload = JobDeltaPayload.from_dict(data)
    except ValueError as exc:
        raise ValueError(f"Invalid delta payload: {exc}") from exc

    soft_fail = CompanyDefaults.get_solo().job_delta_soft_fail

    logger.info(
        "[JOB_UPDATE] Starting job update for job %s, change_id: %s, fields: %s",
        job_id,
        delta_payload.change_id,
        list(delta_payload.fields),
    )

    job: Job | None = None
    soft_fail_context: _SoftFailContext | None = None
    try:
        with transaction.atomic():
            # Lock the row to avoid a race between compare and update
            job = get_object_or_404(Job.objects.select_for_update(), id=job_id)

            # VALIDATE DELTA FIRST - before any other checks that might modify the job
            try:
                _validate_delta_payload(job, delta_payload, soft_fail)
            except DeltaValidationError:
                # Always persist via the outer handler; re-raise if hard-fail
                if not soft_fail:
                    raise
            except ValueError as exc:
                raise InvalidDeltaError(
                    str(exc),
                    reason="Invalid delta payload",
                    detail={"error": str(exc), "stage": "validation"},
                ) from exc

            # Capture soft-fail context for persistence outside the transaction
            soft_fail_context = _collect_soft_fail_context(
                job=job,
                staff=user,
                delta_payload=delta_payload,
                request_etag=if_match,
                soft_fail=soft_fail,
                request_ip=request_ip,
            )

            # Concurrency check using the normalized ETag - AFTER delta validation
            current_etag = generate_updated_at_etag("job", job.id, job.updated_at)
            if not if_match_satisfied(if_match, current_etag):
                logger.error(
                    "[JOB_UPDATE] ETag mismatch! Current: %s, Expected: %s",
                    current_etag,
                    if_match,
                )
                raise PreconditionFailedError("ETag mismatch: resource has changed")

            # Snapshot values needed for post-save logic (priority bump)
            original_status = job.status

            if delta_payload.job_id and str(job.id) != delta_payload.job_id:
                raise InvalidDeltaError(
                    f"Delta job_id {delta_payload.job_id} does not match target job {job.id}",
                    reason="Delta job_id mismatch",
                    detail={
                        "delta_job_id": delta_payload.job_id,
                        "target_job_id": str(job.id),
                    },
                )

            # Apply the 'after' values (v1 routed this through JobSerializer)
            for field_name, value in delta_payload.after.items():
                _apply_delta_field(job, field_name, value)

            # Enrichment context so Job.save() creates a single rich event
            # instead of service + model creating duplicates
            meta_payload: dict[str, object] = {
                "fields": list(delta_payload.fields),
                "actor_id": delta_payload.actor_id,
                "made_at": delta_payload.made_at,
                "etag": delta_payload.etag,
            }
            if delta_payload.undo_of_change_id:
                meta_payload["undo_of_change_id"] = delta_payload.undo_of_change_id

            job.save(
                staff=user,
                schema_version=1,
                change_id=_safe_uuid(delta_payload.change_id),
                delta_meta=_to_json_safe(meta_payload),
                delta_checksum=delta_payload.before_checksum or None,
            )

            # When status changes via edit, place the job at top of its new column
            if "job_status" in delta_payload.fields and job.status != original_status:
                job.priority = Job._calculate_next_priority_for_status(job.status)
                job.save(staff=user, update_fields=["priority", "updated_at"])
    # DeltaValidationError subclasses PreconditionFailedError, so it must be
    # caught first or this arm is unreachable.
    except DeltaValidationError as exc:
        record_delta_rejection(
            job=job,
            staff=user,
            reason=str(exc),
            detail={
                "server_checksum": exc.server_checksum,
                "current_values": exc.current_values,
            },
            envelope=delta_payload.to_dict(),
            change_id=delta_payload.change_id,
            checksum=delta_payload.before_checksum,
            request_etag=delta_payload.etag or if_match or None,
            request_ip=request_ip,
        )
        raise
    except PreconditionFailedError:
        if soft_fail_context:
            record_delta_rejection(**soft_fail_context)
        raise
    except InvalidDeltaError as exc:
        record_delta_rejection(
            job=job,
            staff=user,
            reason=exc.reason,
            detail=exc.detail,
            envelope=delta_payload.to_dict(),
            change_id=delta_payload.change_id,
            checksum=delta_payload.before_checksum,
            request_etag=delta_payload.etag or if_match or None,
            request_ip=request_ip,
        )
        raise
    else:
        if soft_fail_context:
            record_delta_rejection(**soft_fail_context)
        return job


def undo_job_change(  # noqa: PLR0913, PLR0917 -- v1 signature + forensics request_ip
    job_id: UUID,
    change_id: UUID,
    user: Staff,
    if_match: str,
    undo_change_id: UUID | None = None,
    request_ip: str | None = None,
) -> Job:
    """Undo a previously recorded delta by reverting to its before state."""
    job = get_object_or_404(Job, id=job_id)

    event = (
        JobEvent.objects.filter(job_id=job_id, change_id=change_id).order_by("-timestamp").first()
    )
    if not event:
        raise ValueError(f"Job event with change_id {change_id} not found")
    if event.schema_version != 1:
        raise ValueError("Undo is only supported for schema_version=1 events")
    if not event.delta_before or not event.delta_after:
        raise ValueError("Stored event does not contain delta_before/delta_after")

    meta = event.delta_meta or {}
    raw_fields = meta.get("fields") or list(event.delta_before.keys())
    if not raw_fields:
        raise ValueError("Event metadata missing target fields for undo")
    fields = [str(field_name) for field_name in raw_fields]

    current_values: dict[str, object] = {
        field_name: _get_job_field_value(job, field_name) for field_name in fields
    }

    mismatch_fields = [
        field_name
        for field_name in fields
        if normalise_value(current_values[field_name])
        != normalise_value(event.delta_after.get(field_name))
    ]

    if mismatch_fields:
        record_delta_rejection(
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
            request_ip=request_ip,
        )
        raise PreconditionFailedError(
            "Cannot undo change because the current job state no longer matches the original delta"
        )

    checksum = compute_job_delta_checksum(job.id, current_values, fields)
    undo_identifier = undo_change_id or uuid4()
    payload: dict[str, object] = {
        "change_id": str(undo_identifier),
        "job_id": str(job.id),
        "fields": fields,
        "before": current_values,
        "after": event.delta_before,
        "before_checksum": checksum,
        "actor_id": str(user.id),
        "made_at": timezone.now().isoformat(),
        "etag": updated_at_etag_value("job", job.id, job.updated_at),
        "undo_of_change_id": str(change_id),
    }

    return update_job(job_id, payload, user, if_match=if_match, request_ip=request_ip)


# ── Events, delete, accept-quote, timeline ───────────────────────────────


class JobEventCreateResult(TypedDict):
    """Result of add_job_event: the (possibly pre-existing) event row."""

    success: bool
    event: JobEvent
    duplicate_prevented: bool


@transaction.atomic
def add_job_event(
    job_id: UUID, description: str, user: Staff, if_match: str
) -> JobEventCreateResult:
    """Add a manual event to the Job with duplicate prevention."""
    # Guard clause - input validation
    if not description or not description.strip():
        raise ValueError("Event description is required")

    try:
        # Lock the job to prevent race conditions
        job = Job.objects.select_for_update().get(id=job_id)
    except Job.DoesNotExist as exc:
        raise ValueError(f"Job {job_id} not found") from exc

    current_etag = generate_updated_at_etag("job", job.id, job.updated_at)
    if not if_match_satisfied(if_match, current_etag):
        raise PreconditionFailedError("ETag mismatch: resource has changed")

    description_clean = description.strip()

    try:
        event, created = JobEvent.create_safe(
            job=job,
            staff=user,
            detail={"note_text": description_clean},
            event_type="manual_note",
        )
    except (DjangoValidationError, IntegrityError) as exc:
        persist_app_error(
            exc,
            AppErrorContext(
                job_id=str(job_id),
                user_id=str(user.id),
                additional_context={"description": description, "operation": "add_job_event"},
            ),
        )
        logger.warning(
            "Duplicate event constraint violation for job %s by user %s: %s",
            job_id,
            user.email,
            exc,
        )
        raise ValueError("Unable to create event due to duplicate constraint") from exc

    if not created:
        logger.warning(
            "Event already exists for job %s by user %s. Returning existing event: %s",
            job_id,
            user.email,
            event.id,
        )
    else:
        Job.objects.filter(pk=job.pk).touch_updated_at(at=timezone.now())

    logger.info(
        "Event %s %s for job %s by %s",
        event.id,
        "created" if created else "found",
        job_id,
        user.email,
    )
    return {"success": True, "event": event, "duplicate_prevented": not created}


class JobDeleteResult(TypedDict):
    """Result of delete_job."""

    success: bool
    message: str


def delete_job(job_id: UUID, user: Staff, if_match: str) -> JobDeleteResult:
    """Delete a Job if business rules allow and the ETag precondition matches."""
    with transaction.atomic():
        job = get_object_or_404(Job.objects.select_for_update(), id=job_id)
        current_etag = generate_updated_at_etag("job", job.id, job.updated_at)
        if not if_match_satisfied(if_match, current_etag):
            raise PreconditionFailedError("ETag mismatch: resource has changed")

        actual_cost_set = job.latest_actual
        if actual_cost_set and (
            actual_cost_set.summary.get("cost", 0) > 0 or actual_cost_set.summary.get("rev", 0) > 0
        ):
            raise ValueError("Cannot delete this job because it has real costs or revenue.")

        job_name = job.name
        job_number = job.job_number
        job.delete()

        logger.info("Job %s '%s' deleted by %s", job_number, job_name, user.email)

    return {"success": True, "message": f"Job {job_number} deleted successfully"}


class QuoteAcceptResult(TypedDict):
    """Result of accept_quote."""

    success: bool
    job_id: str
    quote_acceptance_date: str
    status: str
    message: str


def accept_quote(job_id: UUID, user: Staff, if_match: str) -> QuoteAcceptResult:
    """Accept the job's quote: set quote_acceptance_date, move to approved."""
    with transaction.atomic():
        job = get_object_or_404(Job.objects.select_for_update(), id=job_id)

        current_etag = generate_updated_at_etag("job", job.id, job.updated_at)
        if not if_match_satisfied(if_match, current_etag):
            raise PreconditionFailedError("ETag mismatch: resource has changed")

        if not job.latest_quote:
            raise ValueError("No quote found for this job")
        if job.quote_acceptance_date:
            raise ValueError("Quote has already been accepted")
        if job.status not in ["draft", "awaiting_approval"]:
            raise ValueError(
                f"Cannot accept quote when job status is '{job.status}'. "
                "Job must be in 'draft' or 'awaiting_approval' state."
            )

        job.quote_acceptance_date = timezone.now()
        job.status = "approved"
        job.save(staff=user, event_type_override="quote_accepted")

    logger.info(
        "Quote accepted for job %s by %s - status changed to approved",
        job.job_number,
        user.email,
    )
    return {
        "success": True,
        "job_id": str(job_id),
        "quote_acceptance_date": job.quote_acceptance_date.isoformat(),
        "status": job.status,
        "message": "Quote accepted successfully",
    }


class TimelineEntryData(TypedDict, total=False):
    """One unified timeline entry (JobEvent or CostLine; keys vary by type)."""

    id: UUID
    timestamp: datetime
    entry_type: str
    description: str
    staff: str | None
    event_type: str | None
    can_undo: bool
    undo_description: str | None
    schema_version: int
    change_id: str | None
    delta_before: dict[str, object] | None
    delta_after: dict[str, object] | None
    delta_meta: dict[str, object] | None
    delta_checksum: str | None
    cost_set_kind: str
    costline_kind: str
    quantity: Decimal
    unit_cost: Decimal
    unit_rev: Decimal
    total_cost: Decimal
    total_rev: Decimal
    created_at: datetime
    updated_at: datetime


def get_job_timeline(job_id: UUID) -> list[TimelineEntryData]:  # noqa: C901 -- v1 control flow ported verbatim
    """Fetch the unified timeline combining JobEvents and CostLine data."""
    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist as exc:
        raise ValueError(f"Job with id {job_id} not found") from exc

    timeline_entries: list[TimelineEntryData] = []

    for event in JobEvent.objects.filter(job=job).select_related("staff"):
        can_undo, undo_description = _undo_info(event)
        timeline_entries.append(
            {
                "id": event.id,
                "timestamp": event.timestamp,
                "entry_type": "event",
                "description": event.description,
                "staff": event.staff.get_display_full_name() if event.staff else None,
                "event_type": event.event_type,
                "can_undo": can_undo,
                "undo_description": undo_description,
                "schema_version": event.schema_version,
                "change_id": str(event.change_id) if event.change_id else None,
                "delta_before": event.delta_before,
                "delta_after": event.delta_after,
                "delta_meta": event.delta_meta,
                "delta_checksum": event.delta_checksum,
            }
        )

    cost_sets = job.cost_sets.all().prefetch_related("cost_lines")

    # Collect unique staff ids from cost lines to fetch in bulk (avoid N+1)
    staff_ids: set[UUID] = set()
    for cost_set in cost_sets:
        for cost_line in cost_set.cost_lines.all():
            if staff_id := cost_line.ext_refs.get("staff_id"):
                # FAIL EARLY: an invalid staff_id indicates data corruption
                try:
                    staff_ids.add(UUID(str(staff_id)))
                except (ValueError, TypeError) as exc:
                    raise ValueError(
                        f"Invalid staff_id in cost_line {cost_line.id}: {staff_id}"
                    ) from exc

    staff_map = Staff.objects.in_bulk(staff_ids) if staff_ids else {}

    for cost_set in cost_sets:
        for cost_line in cost_set.cost_lines.all():
            staff_name = None
            if (staff_id := cost_line.ext_refs.get("staff_id")) and (
                staff := staff_map.get(UUID(str(staff_id)))
            ):
                staff_name = staff.get_display_full_name()

            description = cost_line.desc or ""
            if cost_line.kind == "time":
                description = f"{description} ({float(cost_line.quantity):.2f} hours)"
            elif cost_line.kind == "material":
                description = f"{description} (qty: {float(cost_line.quantity):.3f})"

            common: TimelineEntryData = {
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

            timeline_entries.append(
                {**common, "timestamp": cost_line.created_at, "entry_type": "costline_created"}
            )
            # Separate entry for updates distinct from creation (1s tolerance
            # for auto-save timestamps)
            if (
                cost_line.updated_at
                and (cost_line.updated_at - cost_line.created_at).total_seconds() > 1
            ):
                timeline_entries.append(
                    {**common, "timestamp": cost_line.updated_at, "entry_type": "costline_updated"}
                )

    def _entry_timestamp(entry: TimelineEntryData) -> datetime:
        return entry["timestamp"]

    timeline_entries.sort(key=_entry_timestamp, reverse=True)
    return timeline_entries


# ── Costing: cost sets, cost lines, quote revisions, costs summary ───────
#
# Ported from v1 ``job_costing_views.py`` + ``job_costline_views.py`` (their
# logic lived in the views/serializers; v1 had no separate costing service).
# All CostLine math and summary reconciliation lives in the model layer
# (``CostLine.save``/``delete`` assign entry_seq under an advisory lock and
# refresh ``CostSet.summary``); this service only orchestrates (ADR 0039).

COST_SET_KINDS: tuple[str, ...] = ("estimate", "quote", "actual")

# v1 JobCostSetView.KIND_ORDER: the costing grid groups lines
# material → adjust → time, newest first within each group.
_COSTLINE_GRID_ORDER = Case(
    When(kind="material", then=Value(1)),
    When(kind="adjust", then=Value(2)),
    When(kind="time", then=Value(3)),
    default=Value(999),
    output_field=IntegerField(),
)


def get_latest_cost_set(job: Job, kind: str) -> CostSet | None:
    """Return the newest CostSet of ``kind`` with grid-ordered lines (v1 JobCostSetView)."""
    if kind not in COST_SET_KINDS:
        raise ValueError(f"Invalid kind. Must be one of: {', '.join(COST_SET_KINDS)}")
    return (
        CostSet.objects.filter(job=job, kind=kind)
        .prefetch_related(
            Prefetch(
                "cost_lines",
                queryset=CostLine.objects.order_by(_COSTLINE_GRID_ORDER, "-created_at", "-id"),
            )
        )
        .first()
    )


class CostLineWriteData(TypedDict, total=False):
    """Validated cost-line write payload (v1 CostLineCreateUpdateSerializer fields)."""

    kind: str
    desc: str | None
    quantity: Decimal
    unit_cost: Decimal
    unit_rev: Decimal
    accounting_date: date
    ext_refs: dict[str, object]
    meta: dict[str, object]
    xero_pay_item: UUID | None
    staff: UUID | None
    labour_subtype: UUID | None


def _apply_costline_values(line: CostLine, data: CostLineWriteData) -> None:
    """Apply the provided scalar payload fields to the line."""
    if "kind" in data:
        line.kind = data["kind"]
    if "desc" in data:
        line.desc = data["desc"]
    if "quantity" in data:
        line.quantity = data["quantity"]
    if "unit_cost" in data:
        line.unit_cost = data["unit_cost"]
    if "unit_rev" in data:
        line.unit_rev = data["unit_rev"]
    if "accounting_date" in data:
        line.accounting_date = data["accounting_date"]


def _apply_costline_refs(line: CostLine, data: CostLineWriteData) -> None:
    """Apply the provided JSON/FK payload fields to the line (FKs carry ids)."""
    if "ext_refs" in data:
        line.ext_refs = data["ext_refs"]
    if "meta" in data:
        line.meta = data["meta"]
    if "xero_pay_item" in data:
        line.xero_pay_item_id = data["xero_pay_item"]
    if "staff" in data:
        line.staff_id = data["staff"]
    if "labour_subtype" in data:
        line.labour_subtype_id = data["labour_subtype"]


def _apply_costline_fields(line: CostLine, data: CostLineWriteData) -> None:
    """Apply every provided payload field to the line."""
    _apply_costline_values(line, data)
    _apply_costline_refs(line, data)


def _timesheet_pricing_staff(meta: dict[str, object], data: CostLineWriteData) -> Staff:
    """Resolve the Staff a timesheet line is priced for: ``meta.staff_id`` (v1 contract)."""
    staff_id = meta.get("staff_id")
    if not staff_id:
        raise ValueError("Staff id must be provided when creating a new timesheet entry.")
    try:
        staff = Staff.objects.get(id=str(staff_id))
    except (Staff.DoesNotExist, DjangoValidationError, ValueError) as exc:
        raise ValueError(f"Staff not found: {staff_id}") from exc
    # v1 forced the line's staff FK to agree with meta.staff_id.
    data["staff"] = staff.id
    return staff


def _reprice_timesheet_line(
    line: CostLine, data: CostLineWriteData, meta: dict[str, object]
) -> None:
    """Reprice a ``meta.created_from_timesheet`` line through the ONE rate pipeline.

    v1 did this inside ``CostLineCreateUpdateSerializer.save()``; v2 keeps
    rate resolution in ``apps.job.services.time_entry_rates`` (ADR 0039) and
    calls it from here, so cost-line writes and the timesheet surfaces cannot
    price the same line differently. Mutates ``data`` so the caller's normal
    field application persists the derived values.
    """
    staff = _timesheet_pricing_staff(meta, data)
    # v1: `validated_data.get("labour_subtype") or instance.labour_subtype` — an
    # explicit null KEEPS the line's current subtype rather than resetting it to
    # the worker's default (which would silently reprice the line).
    subtype_id = data.get("labour_subtype") or line.labour_subtype_id
    labour_subtype = LabourSubtype.objects.get(id=subtype_id) if subtype_id is not None else None
    pricing = price_time_entry(
        job=line.cost_set.job,
        staff=staff,
        meta=meta,
        labour_subtype=labour_subtype,
    )
    data["unit_cost"] = pricing.unit_cost
    data["unit_rev"] = pricing.unit_rev
    data["xero_pay_item"] = pricing.pay_item.id
    data["labour_subtype"] = pricing.labour_subtype.id
    meta.update(pricing.meta_updates())
    data["meta"] = meta
    logger.debug(
        "Repriced timesheet cost line for staff %s: unit_cost=%s unit_rev=%s",
        staff.id,
        pricing.unit_cost,
        pricing.unit_rev,
    )


def _validate_costline_write(data: CostLineWriteData) -> None:
    quantity = data.get("quantity")
    if quantity is not None and quantity < 0:
        raise ValueError("Quantity must be non-negative")


def get_or_create_cost_set(job: Job, kind: str) -> CostSet:
    """Get the highest-rev CostSet of ``kind``, creating rev count+1 if none (v1)."""
    cost_set = job.cost_sets.filter(kind=kind).order_by("-rev").first()
    if cost_set is None:
        latest_rev = job.cost_sets.filter(kind=kind).count()
        cost_set = CostSet.objects.create(
            job=job,
            kind=kind,
            rev=latest_rev + 1,
            summary={"cost": 0, "rev": 0, "hours": 0},
        )
        logger.info("Created new %s CostSet rev %s for job %s", kind, cost_set.rev, job.id)
    return cost_set


def create_cost_line(job: Job, kind: str, data: CostLineWriteData, staff: Staff) -> CostLine:
    """Create a cost line on the job's ``kind`` cost set (v1 CostLineCreateView)."""
    if kind not in COST_SET_KINDS:
        raise ValueError(f"Invalid kind. Must be one of: {', '.join(COST_SET_KINDS)}")
    _validate_costline_write(data)

    meta = data.get("meta") or {}
    # v1 let timesheet lines omit labour_subtype: the rate pipeline defaults it
    # from the worker's Staff.default_labour_subtype.
    is_timesheet_line = bool(meta.get("created_from_timesheet"))
    if data.get("kind") == "time" and data.get("labour_subtype") is None and not is_timesheet_line:
        raise ValueError("labour_subtype is required for time lines.")

    with transaction.atomic():
        cost_set = get_or_create_cost_set(job, kind)
        # v1: lines created by workshop staff await office approval.
        line = CostLine(cost_set=cost_set, approved=staff.is_office_staff)
        if is_timesheet_line and data.get("kind") == "time":
            _reprice_timesheet_line(line, data, dict(meta))
        _apply_costline_fields(line, data)
        # CostLine.save() runs full_clean, assigns entry_seq and refreshes
        # the CostSet summary (Phase 2 machinery — not re-implemented here).
        line.save()
    return line


def update_cost_line(line: CostLine, data: CostLineWriteData) -> CostLine:
    """Update a cost line from a partial payload (v1 CostLineUpdateView).

    A quantity change on a line with ``ext_refs.stock_id`` adjusts the
    Stock row by the difference.
    """
    _validate_costline_write(data)

    kind = data.get("kind") or line.kind
    patch_meta = data.get("meta") or {}
    instance_meta = line.meta if isinstance(line.meta, dict) else {}
    # A subtype change must reprice the line even when the patch doesn't resend
    # meta (the timesheet UI patches labour_subtype alone), so pull the stored
    # meta in that case — v1 CostLineCreateUpdateSerializer.save().
    if not patch_meta and "labour_subtype" in data and instance_meta.get("created_from_timesheet"):
        patch_meta = dict(instance_meta)
        data["meta"] = patch_meta
    if kind == "time" and patch_meta.get("created_from_timesheet"):
        _reprice_timesheet_line(line, data, patch_meta)

    with transaction.atomic():
        old_quantity = line.quantity or Decimal("0")
        _apply_costline_fields(line, data)
        line.save()

        stock_id = (line.ext_refs or {}).get("stock_id")
        new_quantity = line.quantity or Decimal("0")
        diff = new_quantity - old_quantity
        if stock_id and diff:
            # Atomic decrement via F() to avoid races (v1 behaviour).
            Stock.objects.filter(pk=stock_id).update(quantity=F("quantity") - diff)
    return line


def delete_cost_line(line: CostLine) -> None:
    """Delete a cost line, returning any consumed stock (v1 CostLineDeleteView)."""
    with transaction.atomic():
        stock_id = (line.ext_refs or {}).get("stock_id")
        if stock_id and line.quantity:
            Stock.objects.filter(pk=stock_id).update(quantity=F("quantity") + line.quantity)
        # CostLine.delete() refreshes the CostSet summary (model machinery).
        line.delete()
    logger.info("Deleted cost line %s", line.id)


# ── Quote revisions ──────────────────────────────────────────────────────


class QuoteRevisionsListData(TypedDict):
    """v1 QuoteRevisionsListSerializer payload."""

    job_id: str
    job_number: int
    current_cost_set_rev: int
    total_revisions: int
    revisions: list[dict[str, object]]


class QuoteRevisionResultData(TypedDict):
    """v1 QuoteRevisionResponseSerializer payload."""

    success: bool
    message: str
    quote_revision: int
    archived_cost_lines_count: int
    job_id: str


def list_quote_revisions(job: Job) -> QuoteRevisionsListData | None:
    """List archived quote revisions from the quote CostSet summary; None if no quote."""
    current_quote = job.get_latest("quote")
    if current_quote is None:
        return None
    summary = current_quote.summary or {}
    revisions = summary.get("revisions", [])
    return {
        "job_id": str(job.id),
        "job_number": job.job_number,
        "current_cost_set_rev": current_quote.rev,
        "total_revisions": len(revisions),
        "revisions": revisions,
    }


def _archive_quote_revision(
    cost_set: CostSet, cost_lines: list[CostLine], reason: str | None
) -> int:
    """Append the current quote data to ``summary.revisions`` and zero the totals (v1).

    Returns the archived revision's number.
    """
    current_summary: dict[str, object] = cost_set.summary or {}
    if "revisions" not in current_summary:
        current_summary["revisions"] = []
    revisions = current_summary["revisions"]
    if not isinstance(revisions, list):
        raise TypeError(f"CostSet {cost_set.id} summary.revisions is not a list")

    total_cost = sum(line.total_cost for line in cost_lines)
    total_rev = sum(line.total_rev for line in cost_lines)
    total_hours = sum(line.quantity for line in cost_lines if line.kind == "time")

    quote_revision = len(revisions) + 1
    archived_revision: dict[str, object] = {
        "quote_revision": quote_revision,
        "archived_at": timezone.now().isoformat(),
        "reason": reason,
        "summary": {
            "cost": float(total_cost),
            "rev": float(total_rev),
            "hours": float(total_hours),
        },
        "cost_lines": [
            {
                "id": str(line.id),
                "kind": line.kind,
                "desc": line.desc,
                "quantity": float(line.quantity),
                "unit_cost": float(line.unit_cost),
                "unit_rev": float(line.unit_rev),
                "total_cost": float(line.total_cost),
                "total_rev": float(line.total_rev),
                "ext_refs": line.ext_refs,
                "meta": line.meta,
            }
            for line in cost_lines
        ],
    }
    revisions.append(archived_revision)

    # Zero the live totals — the new revision starts fresh.
    current_summary.update({"cost": 0.0, "rev": 0.0, "hours": 0.0})
    cost_set.summary = current_summary
    cost_set.save()
    return quote_revision


def create_quote_revision(job: Job, reason: str | None, user: Staff) -> QuoteRevisionResultData:
    """Archive the current quote lines into a revision and clear them.

    v1 JobQuoteRevisionView.post. Raises ValueError when there is no quote
    or nothing to revise (the API maps a missing quote to 404 up front).
    """
    current_quote = job.get_latest("quote")
    if current_quote is None:
        raise ValueError("No quote found for this job. Cannot create revision.")

    cost_lines = list(current_quote.cost_lines.all())
    if not cost_lines:
        raise ValueError("No cost lines found in current quote. Nothing to revise.")

    with transaction.atomic():
        quote_revision = _archive_quote_revision(current_quote, cost_lines, reason)

        # Bulk delete intentionally skips CostLine.delete()'s summary refresh:
        # the archive above just zeroed the live totals.
        current_quote.cost_lines.all().delete()

        # Reset acceptance so the new revision can be accepted.
        job.quote_acceptance_date = None
        job.save(staff=user)

        current_quote.save()

    logger.info(
        "Quote revision created for job %s: revision %s, archived %s cost lines, "
        "reset quote acceptance date",
        job.job_number,
        quote_revision,
        len(cost_lines),
    )
    return {
        "success": True,
        "message": "Quote revision created successfully. Ready for new quote.",
        "quote_revision": quote_revision,
        "archived_cost_lines_count": len(cost_lines),
        "job_id": str(job.id),
    }


# ── Costs summary ────────────────────────────────────────────────────────


class JobCostSummaryData(TypedDict):
    """v1 JobCostSummaryResponseSerializer payload."""

    estimate: CostSetSummaryData | None
    quote: CostSetSummaryData | None
    actual: CostSetSummaryData | None


def _cost_summary_entry(cost_set: CostSet | None) -> CostSetSummaryData | None:
    """One costs/summary entry (v1 JobCostSummaryRestView shape).

    v1 computed profitMargin over *cost* (markup) here while its
    CostSetSerializer computed it over *rev* — the same field name carried
    two formulas. User standardised on margin-on-revenue (2026-08-02), so
    this delegates to ``_summary_with_margin`` (ADR 0039: one
    implementation); the deviation is in the parity ledger.
    """
    if cost_set is None or not cost_set.summary:
        return None
    return _summary_with_margin(cost_set)


def get_job_costs_summary(job: Job) -> JobCostSummaryData:
    """Cost/rev/hours/profitMargin per cost-set kind (v1 JobCostSummaryRestView)."""
    return {
        "estimate": _cost_summary_entry(job.get_latest("estimate")),
        "quote": _cost_summary_entry(job.get_latest("quote")),
        "actual": _cost_summary_entry(job.get_latest("actual")),
    }


# ── Labour subtypes and job labour rates ─────────────────────────────────
#
# Ported from v1 ``labour_views.py`` + ``labour_serializer.py`` +
# ``labour_subtype_service.py`` (the one v1 costing-adjacent service module).


class LabourSubtypeData(TypedDict):
    """v1 LabourSubtypeSerializer row."""

    id: UUID
    name: str
    display_order: int
    is_active: bool
    is_workshop: bool
    default_charge_out_rate: Decimal


class LabourSubtypeManageData(TypedDict):
    """v1 LabourSubtypeManageSerializer row."""

    id: UUID
    name: str
    display_order: int
    is_active: bool
    is_workshop: bool
    counts_for_scheduling: bool
    default_charge_out_rate: Decimal


class LabourSubtypeWriteData(TypedDict, total=False):
    """Validated labour-subtype write payload (manage create/patch)."""

    name: str
    display_order: int
    is_active: bool
    is_workshop: bool
    counts_for_scheduling: bool
    default_charge_out_rate: Decimal


class JobLabourRateData(TypedDict):
    """v1 JobLabourRateSerializer row."""

    id: UUID
    labour_subtype: UUID
    labour_subtype_name: str
    is_workshop: bool
    charge_out_rate: Decimal


def labour_subtype_data(subtype: LabourSubtype) -> LabourSubtypeData:
    """Serialise one LabourSubtype (v1 LabourSubtypeSerializer shape)."""
    return {
        "id": subtype.id,
        "name": subtype.name,
        "display_order": subtype.display_order,
        "is_active": subtype.is_active,
        "is_workshop": subtype.is_workshop,
        "default_charge_out_rate": subtype.default_charge_out_rate,
    }


def labour_subtype_manage_data(subtype: LabourSubtype) -> LabourSubtypeManageData:
    """Serialise one LabourSubtype (v1 LabourSubtypeManageSerializer shape)."""
    return {
        "id": subtype.id,
        "name": subtype.name,
        "display_order": subtype.display_order,
        "is_active": subtype.is_active,
        "is_workshop": subtype.is_workshop,
        "counts_for_scheduling": subtype.counts_for_scheduling,
        "default_charge_out_rate": subtype.default_charge_out_rate,
    }


def job_labour_rate_data(rate: JobLabourRate) -> JobLabourRateData:
    """Serialise one JobLabourRate (v1 JobLabourRateSerializer shape)."""
    return {
        "id": rate.id,
        "labour_subtype": rate.labour_subtype_id,
        "labour_subtype_name": rate.labour_subtype.name,
        "is_workshop": rate.labour_subtype.is_workshop,
        "charge_out_rate": rate.charge_out_rate,
    }


def seed_subtype_onto_existing_jobs(subtype: LabourSubtype) -> int:
    """Create a JobLabourRate for ``subtype`` on every job that lacks one.

    Mirrors the seeding in ``Job.save()``: shop jobs bill no revenue so they
    get ``0.00``; every other job gets the subtype's default rate. Keeps the
    invariant that every job has a rate row for every active subtype, so
    timesheet/estimate entry against the new subtype cannot crash on a
    missing rate row. Returns the number of missing rows attempted; benign
    duplicate insert races are ignored and followed by an invariant check.
    """
    if not subtype.is_active:
        raise ValueError(f"Cannot seed inactive LabourSubtype '{subtype.name}' onto jobs.")

    with transaction.atomic():
        table_name = connection.ops.quote_name(Job._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {table_name} IN SHARE ROW EXCLUSIVE MODE")

        shop_company_id = CompanyDefaults.get_solo().shop_company_id
        existing_job_ids = set(
            JobLabourRate.objects.filter(labour_subtype=subtype).values_list("job_id", flat=True)
        )
        rows = [
            JobLabourRate(
                job_id=job_id,
                labour_subtype=subtype,
                charge_out_rate=(
                    Decimal("0.00")
                    if company_id == shop_company_id
                    else subtype.default_charge_out_rate
                ),
            )
            for job_id, company_id in Job.objects.exclude(id__in=existing_job_ids).values_list(
                "id", "company_id"
            )
        ]
        JobLabourRate.objects.bulk_create(rows, batch_size=1000, ignore_conflicts=True)
        missing_job_ids = list(
            Job.objects.exclude(labour_rates__labour_subtype=subtype).values_list("id", flat=True)[
                :10
            ]
        )
        if missing_job_ids:
            raise RuntimeError(
                "Failed to satisfy active labour-subtype rate-row invariant "
                f"for subtype '{subtype.name}'. Missing example job ids: "
                f"{missing_job_ids}"
            )
        return len(rows)


def create_labour_subtype(data: LabourSubtypeWriteData) -> LabourSubtype:
    """Create a labour subtype, backfilling rate rows when active (v1 manage POST)."""
    with transaction.atomic():
        subtype = LabourSubtype(**data)
        subtype.full_clean()
        subtype.save()
        if subtype.is_active:
            seed_subtype_onto_existing_jobs(subtype)
        # else: inactive subtype is not seeded onto jobs (matches Job.save)
    return subtype


def _check_labour_subtype_update_guards(
    subtype: LabourSubtype, data: LabourSubtypeWriteData
) -> None:
    """Enforce the v1 LabourSubtypeManageSerializer.update guards."""
    # Guard: a subtype that is a staff member's default cannot be deactivated —
    # their new timesheet lines resolve via that default and would silently use
    # a subtype no longer offered for entry.
    deactivating = subtype.is_active and data.get("is_active") is False
    if deactivating:
        dependent = Staff.objects.filter(default_labour_subtype=subtype).count()
        if dependent:
            raise ValueError(
                f"{dependent} staff default to '{subtype.name}'; "
                "reassign them before deactivating it."
            )

    # Guard: never empty the active Workshop (or non-workshop) pool.
    # default_workshop()/default_non_workshop() raise when their pool is empty,
    # which breaks job creation, Xero sync, and quote import company-wide. This
    # covers both deactivation (is_active=False) and flipping is_workshop.
    new_active = data.get("is_active", subtype.is_active)
    new_workshop = data.get("is_workshop", subtype.is_workshop)
    for was, now, is_ws, label in (
        (subtype.is_active and subtype.is_workshop, new_active and new_workshop, True, "Workshop"),
        (
            subtype.is_active and not subtype.is_workshop,
            new_active and not new_workshop,
            False,
            "non-workshop",
        ),
    ):
        if was and not now:
            others = (
                LabourSubtype.objects.filter(is_active=True, is_workshop=is_ws)
                .exclude(pk=subtype.pk)
                .exists()
            )
            if not others:
                raise ValueError(
                    f"'{subtype.name}' is the only active {label} subtype; "
                    "job creation, Xero sync and quote import depend on it."
                )


def update_labour_subtype(subtype_pk: UUID, data: LabourSubtypeWriteData) -> LabourSubtype:
    """Update a labour subtype from a partial payload, under row lock (v1 manage PATCH).

    Reactivation backfills rate rows onto every job. No delete — subtypes
    are referenced by historical cost lines (PROTECT); deactivate instead.
    """
    with transaction.atomic():
        subtype = LabourSubtype.objects.select_for_update().get(pk=subtype_pk)
        _check_labour_subtype_update_guards(subtype, data)

        was_active = subtype.is_active
        for field_name, value in data.items():
            setattr(subtype, field_name, value)
        subtype.full_clean()
        subtype.save()

        if not was_active and subtype.is_active:
            seed_subtype_onto_existing_jobs(subtype)
        # else: no activation boundary crossed; no backfill needed
    return subtype


class JobLabourRateUpdateEntryData(TypedDict):
    """One rate change in a job labour-rates update (v1 JobLabourRateUpdateSerializer)."""

    labour_subtype: UUID
    charge_out_rate: Decimal


def get_job_labour_rates(job: Job) -> list[JobLabourRateData]:
    """Return the job's per-subtype charge-out rates (v1 JobLabourRatesView.get)."""
    return [
        job_labour_rate_data(rate) for rate in job.labour_rates.select_related("labour_subtype")
    ]


def update_job_labour_rates(
    job: Job, entries: list[JobLabourRateUpdateEntryData], user: Staff
) -> list[JobLabourRateData]:
    """Apply per-subtype rate changes (v1 JobLabourRatesView.patch).

    Changed rates are recorded in one ``pricing_changed`` JobEvent whose
    ``detail.changes`` entries render via ``_render_change``.
    """
    subtypes = LabourSubtype.objects.in_bulk([e["labour_subtype"] for e in entries])
    missing = [str(e["labour_subtype"]) for e in entries if e["labour_subtype"] not in subtypes]
    if missing:
        raise ValueError(f"LabourSubtype not found: {', '.join(missing)}")

    # Check the bad case first (ADR 0015): any catalogue subtype may be sent,
    # but only subtypes seeded onto this job have a rate row. Reject unknown
    # subtypes up front so the write loop below can't fail partway through.
    rates_by_subtype = {
        r.labour_subtype_id: r for r in job.labour_rates.select_related("labour_subtype")
    }
    unknown = [
        subtypes[e["labour_subtype"]].name
        for e in entries
        if e["labour_subtype"] not in rates_by_subtype
    ]
    if unknown:
        raise ValueError(f"No rate row on this job for: {', '.join(unknown)}.")

    # Atomic so a failure mid-loop never leaves a half-applied update without
    # a matching JobEvent.
    with transaction.atomic():
        changes: list[dict[str, str]] = []
        for entry in entries:
            rate = rates_by_subtype[entry["labour_subtype"]]
            if rate.charge_out_rate == entry["charge_out_rate"]:
                continue
            # Each change must be a dict {field_name, old_value, new_value} —
            # JobEvent.build_description renders them via _render_change.
            changes.append(
                {
                    "field_name": f"{rate.labour_subtype.name} charge-out rate",
                    "old_value": f"${rate.charge_out_rate}/hour",
                    "new_value": f"${entry['charge_out_rate']}/hour",
                }
            )
            rate.charge_out_rate = entry["charge_out_rate"]
            rate.save(update_fields=["charge_out_rate"])

        if changes:
            JobEvent.objects.create(
                job=job,
                event_type="pricing_changed",
                detail={"changes": changes},
                staff=user,
            )
        # else: no-op update — nothing changed, no event to record

    return get_job_labour_rates(job)


# ── Kanban staff assignment (v1 JobStaffService) ─────────────────────────


def _touch_job_for_assignment_change(job: Job) -> None:
    """Bump updated_at so kanban clients refetch the card (untracked write)."""
    Job.objects.filter(id=job.id).touch_updated_at(at=timezone.now())


def assign_staff_to_job(job_id: UUID, staff_id: UUID) -> tuple[bool, str | None]:
    """Assign a staff member to a job; returns (success, error message)."""
    try:
        job = Job.objects.get(id=job_id)
        staff = Staff.objects.get(id=str(staff_id))
    except Job.DoesNotExist:
        return False, "Job not found"
    except Staff.DoesNotExist:
        return False, "Staff member not found"

    if not job.people.filter(id=staff.id).exists():
        job.people.add(staff)
        _touch_job_for_assignment_change(job)

    return True, None


def remove_staff_from_job(job_id: UUID, staff_id: UUID) -> tuple[bool, str | None]:
    """Remove a staff member from a job; returns (success, error message)."""
    try:
        job = Job.objects.get(id=job_id)
        staff = Staff.objects.get(id=str(staff_id))
    except Job.DoesNotExist:
        return False, "Job not found"
    except Staff.DoesNotExist:
        return False, "Staff member not found"

    if job.people.filter(id=staff.id).exists():
        job.people.remove(staff)
        _touch_job_for_assignment_change(job)

    return True, None
