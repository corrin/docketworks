"""Pydantic wire contracts for the job router.

The service layer builds matching TypedDict data, and error responses use the
standard envelope from ADR 0013.
"""

import datetime as datetime_module
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from ninja import Schema
from pydantic import Field

from apps.job.models import JobDeltaRejection

# ── Shared nested shapes ─────────────────────────────────────────────────


class CompanyDefaultsJobDetail(Schema):
    """Wire contract for CompanyDefaultsJobDetail."""

    materials_markup: float
    time_markup: float
    wage_rate: float


class CostLineOut(Schema):
    """Wire contract for CostLineOut."""

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


class CostLineApprovalResponse(Schema):
    """Success body for cost-line approval.

    Material lines consume stock and include ``remaining_quantity``; other line
    kinds omit it. One optional field models that sole variation without a
    polymorphic response union.
    """

    success: bool
    message: str
    remaining_quantity: Decimal | None = None
    line: CostLineOut


class CostSetSummaryOut(Schema):
    """The four public cost-set summary values.

    Storage-only summary keys (e.g. the archived quote ``revisions``) must
    never appear on cost-set reads because they are not part of this contract.
    """

    cost: float
    rev: float
    hours: float
    profitMargin: float | None  # noqa: N815 -- public API uses camelCase


class CostSetOut(Schema):
    """Wire contract for CostSetOut."""

    id: str
    job: UUID
    kind: str
    rev: int
    summary: CostSetSummaryOut
    created: datetime
    cost_lines: list[CostLineOut]


class JobFileOut(Schema):
    """Wire contract for JobFileOut."""

    id: UUID
    filename: str
    mime_type: str | None
    uploaded_at: datetime
    status: str
    print_on_jobsheet: bool
    size: int | None
    download_url: str
    thumbnail_url: str | None


class QuoteSpreadsheetOut(Schema):
    """Wire contract for QuoteSpreadsheetOut."""

    id: UUID
    sheet_id: str | None
    sheet_url: str | None
    tab: str | None
    job_id: str
    job_number: int
    job_name: str


class InvoiceOut(Schema):
    """Wire contract for InvoiceOut."""

    id: UUID
    xero_id: UUID
    number: str
    status: str
    # Fully qualified: the field name ``date`` would otherwise shadow the type.
    date: datetime_module.date
    due_date: datetime_module.date | None
    total_excl_tax: float
    total_incl_tax: float
    amount_due: float
    tax: float
    online_url: str | None


class QuoteOut(Schema):
    """Wire contract for QuoteOut."""

    id: UUID
    xero_id: UUID
    status: str
    date: datetime_module.date
    total_excl_tax: float
    total_incl_tax: float
    online_url: str | None


class XeroQuoteOut(Schema):
    """Wire contract for XeroQuoteOut."""

    status: str
    online_url: str | None


class XeroInvoiceOut(Schema):
    """Wire contract for XeroInvoiceOut."""

    number: str
    status: str
    online_url: str | None


class JobEventOut(Schema):
    """Wire contract for JobEventOut."""

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


class JobDetail(Schema):
    """Wire contract for JobDetail."""

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
    latest_estimate: CostSetOut | None
    latest_quote: CostSetOut | None
    latest_actual: CostSetOut | None
    job_status: str
    delivery_date: date | None
    paid: bool
    quote_acceptance_date: datetime | None
    job_is_valid: bool
    job_files: list[JobFileOut]
    pricing_methodology: str
    price_cap: Decimal | None
    speed_quality_tradeoff: str
    quote_sheet: QuoteSpreadsheetOut | None
    quoted: bool
    fully_invoiced: bool
    quote: QuoteOut | None
    invoices: list[InvoiceOut]
    xero_quote: XeroQuoteOut | None
    xero_invoices: list[XeroInvoiceOut]
    shop_job: bool
    rejected_flag: bool
    rdti_type: str | None
    default_xero_pay_item_id: UUID | None
    default_xero_pay_item_name: str | None
    min_people: int
    max_people: int
    is_urgent: bool


class JobData(Schema):
    """Wire contract for JobData."""

    job: JobDetail
    events: list[JobEventOut]
    company_defaults: CompanyDefaultsJobDetail


class JobDetailResponse(Schema):
    """Wire contract for JobDetailResponse."""

    success: bool = True
    data: JobData


# ── Create / delete ──────────────────────────────────────────────────────


class JobCreateRequest(Schema):
    """Wire contract for JobCreateRequest."""

    name: Annotated[str, Field(min_length=1, max_length=255)]
    company_id: UUID
    description: str = ""
    order_number: str = ""
    notes: str = ""
    person_id: UUID | None = None
    pricing_methodology: str | None = None
    estimated_materials: Annotated[Decimal, Field(ge=0)]
    estimated_time: Annotated[Decimal, Field(ge=0)]
    is_urgent: bool = False


class JobCreateResponse(Schema):
    """Wire contract for JobCreateResponse."""

    success: bool = True
    job_id: str
    job_number: int
    message: str


class JobDeleteResponse(Schema):
    """Wire contract for JobDeleteResponse."""

    success: bool = True
    message: str


# ── Delta envelope / undo ────────────────────────────────────────────────


class JobDeltaEnvelope(Schema):
    """Wire contract for JobDeltaEnvelope."""

    change_id: UUID
    actor_id: UUID | None = None
    made_at: datetime | None = None
    job_id: UUID | None = None
    fields: Annotated[list[str], Field(min_length=1)]
    before: dict[str, object]
    after: dict[str, object]
    before_checksum: str
    etag: str | None = None


class JobUndoRequest(Schema):
    """Wire contract for JobUndoRequest."""

    change_id: UUID
    undo_change_id: UUID | None = None


# ── Header / basic info / status choices ─────────────────────────────────


class JobHeaderResponse(Schema):
    """Wire contract for JobHeaderResponse."""

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


class JobBasicInformationResponse(Schema):
    """Wire contract for JobBasicInformationResponse."""

    description: str
    delivery_date: str | None
    order_number: str
    notes: str


class JobStatusChoicesResponse(Schema):
    """Wire contract for JobStatusChoicesResponse."""

    statuses: dict[str, str]


# ── Events / timeline ────────────────────────────────────────────────────


class JobEventCreateRequest(Schema):
    """Wire contract for JobEventCreateRequest."""

    description: Annotated[str, Field(min_length=1, max_length=500)]


class JobEventCreateResponse(Schema):
    """Wire contract for JobEventCreateResponse."""

    success: bool
    event: JobEventOut


class JobEventsResponse(Schema):
    """Wire contract for JobEventsResponse."""

    events: list[JobEventOut]


class TimelineEntryOut(Schema):
    """Wire contract for TimelineEntryOut."""

    id: UUID
    timestamp: datetime
    entry_type: str
    description: str
    staff: str | None = None
    event_type: str | None = None
    can_undo: bool | None = None
    undo_description: str | None = None
    change_id: str | None = None
    schema_version: int | None = None
    delta_before: dict[str, object] | None = None
    delta_after: dict[str, object] | None = None
    delta_meta: dict[str, object] | None = None
    delta_checksum: str | None = None
    cost_set_kind: str | None = None
    costline_kind: str | None = None
    quantity: Decimal | None = None
    unit_cost: Decimal | None = None
    unit_rev: Decimal | None = None
    total_cost: Decimal | None = None
    total_rev: Decimal | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class JobTimelineResponse(Schema):
    """Wire contract for JobTimelineResponse."""

    timeline: list[TimelineEntryOut]


# ── Quote acceptance ─────────────────────────────────────────────────────


class JobQuoteAcceptanceResponse(Schema):
    """Wire contract for JobQuoteAcceptanceResponse."""

    success: bool
    job_id: UUID
    quote_acceptance_date: str
    message: str


# ── Delta rejections ─────────────────────────────────────────────────────


class JobDeltaRejectionOut(Schema):
    """Wire contract for JobDeltaRejectionOut."""

    id: UUID
    change_id: UUID | None
    job_id: UUID | None
    job_name: str | None
    reason: str
    detail: object
    checksum: str | None
    request_etag: str | None
    request_ip: str | None
    created_at: datetime
    envelope: dict[str, object]
    staff_id: UUID | None
    staff_email: str | None

    @staticmethod
    def resolve_job_name(obj: "JobDeltaRejection") -> str | None:
        """Return the rejected job's name, when the job still exists."""
        return obj.job.name if obj.job else None

    @staticmethod
    def resolve_staff_email(obj: "JobDeltaRejection") -> str | None:
        """Return the submitting staff member's email, when known."""
        return obj.staff.email if obj.staff else None

    @staticmethod
    def resolve_detail(obj: "JobDeltaRejection") -> object:
        """Parse JSON text when possible while preserving non-JSON forensic detail."""
        raw = obj.detail or ""
        if not raw:
            return None
        try:
            return json.loads(raw)
        # deliberate-swallow: a JobDeltaRejection row is the only surviving trace
        # of a delta that failed, so raising while READING one would destroy the
        # evidence the record exists to hold. Detail that is not JSON is
        # returned verbatim rather than parsed.
        except ValueError:
            return raw


class JobDeltaRejectionListResponse(Schema):
    """Wire contract for JobDeltaRejectionListResponse."""

    count: int
    next: str | None = None
    previous: str | None = None
    results: list[JobDeltaRejectionOut]


class GroupedJobDeltaRejectionOut(Schema):
    """Wire contract for GroupedJobDeltaRejectionOut."""

    fingerprint: str
    reason: str
    occurrence_count: int
    first_seen: datetime
    last_seen: datetime
    latest_id: UUID
    resolved: bool


class GroupedJobDeltaRejectionListResponse(Schema):
    """Wire contract for GroupedJobDeltaRejectionListResponse."""

    count: int
    next: str | None = None
    previous: str | None = None
    results: list[GroupedJobDeltaRejectionOut]


class GroupedJobDeltaRejectionResolveRequest(Schema):
    """Identify a rejection group to resolve.

    Identifies the group by the SHA-256 fingerprint of the reason (matches the
    ``fingerprint`` field returned in the grouped listing).
    """

    fingerprint: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class GroupedJobDeltaRejectionResolveResponse(Schema):
    """Wire contract for GroupedJobDeltaRejectionResolveResponse."""

    updated: int


# ── Costing: cost lines, quote revisions, costs summary ──────────────────


class CostLineCreateRequest(Schema):
    """Wire contract for CostLineCreateRequest."""

    kind: str
    desc: str | None = None
    quantity: Decimal = Decimal("1.000")
    unit_cost: Decimal = Decimal("0.00")
    unit_rev: Decimal = Decimal("0.00")
    accounting_date: date
    ext_refs: dict[str, object] = Field(default_factory=dict)
    meta: dict[str, object] = Field(default_factory=dict)
    xero_pay_item: UUID | None = None
    staff: UUID | None = None
    labour_subtype: UUID | None = None


class CostLineUpdateRequest(Schema):
    """Wire contract for CostLineUpdateRequest."""

    kind: str | None = None
    desc: str | None = None
    quantity: Decimal | None = None
    unit_cost: Decimal | None = None
    unit_rev: Decimal | None = None
    accounting_date: date | None = None
    ext_refs: dict[str, object] | None = None
    meta: dict[str, object] | None = None
    xero_pay_item: UUID | None = None
    staff: UUID | None = None
    labour_subtype: UUID | None = None


class QuoteRevisionRequest(Schema):
    """Wire contract for QuoteRevisionRequest."""

    reason: Annotated[str, Field(max_length=500)] | None = None


class QuoteRevisionResponse(Schema):
    """Wire contract for QuoteRevisionResponse."""

    success: bool
    message: str
    quote_revision: int
    archived_cost_lines_count: int
    job_id: str


class QuoteRevisionsListResponse(Schema):
    """Wire contract for QuoteRevisionsListResponse."""

    job_id: str
    job_number: int
    current_cost_set_rev: int
    total_revisions: int
    revisions: list[dict[str, object]]


class JobCostSummaryResponse(Schema):
    """Estimate, quote, and actual cost summaries for a job.

    Entries reuse ``CostSetSummaryOut`` so ``profitMargin`` consistently means
    margin on revenue rather than markup on cost.
    """

    estimate: CostSetSummaryOut | None
    quote: CostSetSummaryOut | None
    actual: CostSetSummaryOut | None


# ── Labour subtypes and job labour rates ─────────────────────────────────


class LabourSubtypeOut(Schema):
    """Wire contract for LabourSubtypeOut."""

    id: UUID
    name: str
    display_order: int
    is_active: bool
    is_workshop: bool
    default_charge_out_rate: Decimal


class LabourSubtypeManageOut(Schema):
    """Wire contract for LabourSubtypeManageOut."""

    id: UUID
    name: str
    display_order: int
    is_active: bool
    is_workshop: bool
    counts_for_scheduling: bool
    default_charge_out_rate: Decimal


class LabourSubtypeManageCreateRequest(Schema):
    """Wire contract for LabourSubtypeManageCreateRequest."""

    name: Annotated[str, Field(min_length=1, max_length=100)]
    display_order: Annotated[int, Field(ge=0)] = 0
    is_active: bool = True
    is_workshop: bool = False
    counts_for_scheduling: bool = False
    default_charge_out_rate: Annotated[Decimal, Field(ge=0)]


class LabourSubtypeManageUpdateRequest(Schema):
    """Wire contract for LabourSubtypeManageUpdateRequest."""

    name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    display_order: Annotated[int, Field(ge=0)] | None = None
    is_active: bool | None = None
    is_workshop: bool | None = None
    counts_for_scheduling: bool | None = None
    default_charge_out_rate: Annotated[Decimal, Field(ge=0)] | None = None


class JobLabourRateOut(Schema):
    """Wire contract for JobLabourRateOut."""

    id: UUID
    labour_subtype: UUID
    labour_subtype_name: str
    is_workshop: bool
    charge_out_rate: Decimal


class JobLabourRateUpdateEntry(Schema):
    """Wire contract for JobLabourRateUpdateEntry."""

    labour_subtype: UUID
    charge_out_rate: Annotated[Decimal, Field(ge=0)]


class JobLabourRatesUpdateRequest(Schema):
    """Wire contract for JobLabourRatesUpdateRequest."""

    rates: Annotated[list[JobLabourRateUpdateEntry], Field(min_length=1)]


# ── Kanban ───────────────────────────────────────────────────────────────


class KanbanJobPersonOut(Schema):
    """Wire contract for KanbanJobPersonOut."""

    id: UUID
    display_name: str
    # Plain str, not a URL type: site-root-relative /media/ paths must resolve
    # against the browser's own origin.
    icon_url: str | None


class KanbanJobOut(Schema):
    """Wire contract for KanbanJobOut."""

    id: UUID
    name: str
    description: str | None
    job_number: int
    company_name: str
    person_name: str
    people: list[KanbanJobPersonOut]
    status: str  # Display name
    status_key: str  # Actual status key
    rejected_flag: bool
    paid: bool
    fully_invoiced: bool
    speed_quality_tradeoff: str
    created_by_id: UUID | None
    created_at: str | None  # Formatted as string by the service
    updated_at: str | None
    delivery_date: str | None
    priority: float
    shop_job: bool
    is_urgent: bool
    over_budget: bool
    quote_revenue: float
    time_and_materials_revenue: float
    min_people: int
    max_people: int


class KanbanColumnJobOut(KanbanJobOut):
    """Wire contract for KanbanColumnJobOut."""

    badge_label: str
    badge_color: str


class FetchAllJobsResponse(Schema):
    """Wire contract for FetchAllJobsResponse."""

    success: bool = True
    active_jobs: list[KanbanJobOut] = Field(default_factory=list)
    archived_jobs: list[KanbanJobOut] = Field(default_factory=list)
    total_archived: int = 0


class FetchJobsResponse(Schema):
    """Wire contract for FetchJobsResponse."""

    success: bool = True
    jobs: list[KanbanJobOut] = Field(default_factory=list)
    total: int = 0
    filtered_count: int = 0


class FetchJobsByColumnResponse(Schema):
    """Wire contract for FetchJobsByColumnResponse."""

    success: bool = True
    jobs: list[KanbanColumnJobOut] = Field(default_factory=list)
    total: int = 0
    filtered_count: int = 0
    has_more: bool | None = None
    error: str | None = None


class FetchStatusValuesResponse(Schema):
    """Wire contract for FetchStatusValuesResponse."""

    success: bool = True
    statuses: dict[str, str] = Field(default_factory=dict)
    tooltips: dict[str, str] = Field(default_factory=dict)


class AdvancedSearchResponse(Schema):
    """Wire contract for AdvancedSearchResponse."""

    success: bool = True
    jobs: list[KanbanJobOut] = Field(default_factory=list)
    total: int = 0


class KanbanChangesResponse(Schema):
    """Wire contract for KanbanChangesResponse."""

    success: bool
    jobs: list[KanbanColumnJobOut]
    removed_job_ids: list[UUID]
    full_refresh_required: bool


class KanbanSuccessResponse(Schema):
    """Wire contract for KanbanSuccessResponse."""

    success: bool = True
    message: str


class JobStatusUpdateRequest(Schema):
    """Wire contract for JobStatusUpdateRequest."""

    status: str


class JobReorderRequest(Schema):
    """Wire contract for JobReorderRequest."""

    anchor_job_id: UUID | None = None
    placement: str | None = None
    status: str | None = None


class AssignJobRequest(Schema):
    """Wire contract for AssignJobRequest."""

    staff_id: UUID


class AssignJobResponse(Schema):
    """Wire contract for AssignJobResponse."""

    success: bool
    message: str | None = None
    error: str | None = None


# ── Job files ────────────────────────────────────────────────────────────


class JobFileUploadSuccessResponse(Schema):
    """Wire contract for JobFileUploadSuccessResponse."""

    status: str = "success"
    uploaded: list[JobFileOut]
    message: str


class JobFileUploadPartialResponse(Schema):
    """Wire contract for JobFileUploadPartialResponse."""

    status: str
    uploaded: list[JobFileOut]
    errors: list[str]


class JobFileUpdateRequest(Schema):
    """Wire contract for JobFileUpdateRequest."""

    print_on_jobsheet: bool | None = None
    filename: str | None = None


class JobFileUpdateSuccessResponse(Schema):
    """Wire contract for JobFileUpdateSuccessResponse."""

    status: str = "success"
    message: str
    print_on_jobsheet: bool
    filename: str


class MonthEndJobHistoryOut(Schema):
    """Wire contract for MonthEndJobHistoryOut."""

    date: date
    total_hours: float
    total_dollars: float


class MonthEndJobOut(Schema):
    """Wire contract for MonthEndJobOut."""

    job_id: UUID
    job_number: int
    job_name: str
    company_name: str
    history: list[MonthEndJobHistoryOut]
    total_hours: float
    total_dollars: float


class MonthEndStockHistoryOut(Schema):
    """Wire contract for MonthEndStockHistoryOut."""

    date: date
    material_line_count: int
    material_cost: float


class MonthEndStockJobOut(Schema):
    """Wire contract for MonthEndStockJobOut."""

    job_id: UUID
    job_number: int
    job_name: str
    history: list[MonthEndStockHistoryOut]


class MonthEndGetResponse(Schema):
    """Wire contract for MonthEndGetResponse."""

    jobs: list[MonthEndJobOut]
    stock_job: MonthEndStockJobOut


class MonthEndPostRequest(Schema):
    """Wire contract for MonthEndPostRequest."""

    job_ids: list[UUID]


class MonthEndPostResponse(Schema):
    """Wire contract for MonthEndPostResponse.

    ``errors`` are plain strings; see month_end_service.process_jobs for the
    tuple-shaped errors are deliberately rejected.
    """

    processed: list[UUID]
    errors: list[str]
