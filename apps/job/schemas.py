"""Pydantic schemas for the job router (wire shapes match v1 frontend/schema.yml).

Success bodies mirror v1's DRF serializers (``apps/job/serializers/``); the
service layer (``apps/job/services/job_service.py``) builds matching TypedDict
data. Error bodies use the v2 envelope (ADR 0013).
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
    """v1 CompanyDefaultsJobDetailSerializer."""

    materials_markup: float
    time_markup: float
    wage_rate: float


class CostLineOut(Schema):
    """v1 CostLineSerializer (COSTLINE_API_FIELDS + totals)."""

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
    """v1 ``CostLineApprovalResult`` — the approve endpoint's success body.

    v1 declared it as a polymorphic union of ``StockConsumeResponse`` (material
    lines, which consume stock and report the remaining quantity) and
    ``CostLineApprovalResponse`` (everything else). The two differ only in the
    optional ``remaining_quantity``, so v2 serves one schema whose optional
    field is present exactly when a stock row was drawn down.
    """

    success: bool
    message: str
    remaining_quantity: Decimal | None = None
    line: CostLineOut


class CostSetSummaryOut(Schema):
    """v1 CostSetSummarySerializer: exactly these four keys.

    Storage-only summary keys (e.g. the archived quote ``revisions``) must
    never appear on cost-set reads (adversarial review 2026-08-02).
    """

    cost: float
    rev: float
    hours: float
    profitMargin: float | None  # noqa: N815 -- v1 wire name


class CostSetOut(Schema):
    """v1 CostSetSerializer (summary carries computed profitMargin)."""

    id: str
    job: UUID
    kind: str
    rev: int
    summary: CostSetSummaryOut
    created: datetime
    cost_lines: list[CostLineOut]


class JobFileOut(Schema):
    """v1 JobFileSerializer."""

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
    """v1 QuoteSpreadsheetSerializer."""

    id: UUID
    sheet_id: str | None
    sheet_url: str | None
    tab: str | None
    job_id: str
    job_number: int
    job_name: str


class InvoiceOut(Schema):
    """v1 InvoiceSerializer."""

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
    """v1 QuoteSerializer."""

    id: UUID
    xero_id: UUID
    status: str
    date: datetime_module.date
    total_excl_tax: float
    total_incl_tax: float
    online_url: str | None


class XeroQuoteOut(Schema):
    """v1 XeroQuoteSerializer (status and URL only)."""

    status: str
    online_url: str | None


class XeroInvoiceOut(Schema):
    """v1 XeroInvoiceSerializer (number, status, URL only)."""

    number: str
    status: str
    online_url: str | None


class JobEventOut(Schema):
    """v1 JobEventSerializer (fields + computed undo support)."""

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
    """v1 JobSerializer."""

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
    """v1 JobDataSerializer (the ``data`` of getFullJob/getJobSummary)."""

    job: JobDetail
    events: list[JobEventOut]
    company_defaults: CompanyDefaultsJobDetail


class JobDetailResponse(Schema):
    """v1 JobDetailResponseSerializer / JobSummaryResponseSerializer."""

    success: bool = True
    data: JobData


# ── Create / delete ──────────────────────────────────────────────────────


class JobCreateRequest(Schema):
    """v1 JobCreateSerializer."""

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
    """v1 JobCreateResponseSerializer."""

    success: bool = True
    job_id: str
    job_number: int
    message: str


class JobDeleteResponse(Schema):
    """v1 JobDeleteResponseSerializer."""

    success: bool = True
    message: str


# ── Delta envelope / undo ────────────────────────────────────────────────


class JobDeltaEnvelope(Schema):
    """v1 JobDeltaEnvelopeSerializer (ADR 0004)."""

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
    """v1 JobUndoSerializer."""

    change_id: UUID
    undo_change_id: UUID | None = None


# ── Header / basic info / status choices ─────────────────────────────────


class JobHeaderResponse(Schema):
    """v1 JobHeaderResponseSerializer (JOB_DIRECT_FIELDS + joins)."""

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
    """v1 JobBasicInformationResponseSerializer."""

    description: str
    delivery_date: str | None
    order_number: str
    notes: str


class JobStatusChoicesResponse(Schema):
    """v1 JobStatusChoicesResponseSerializer."""

    statuses: dict[str, str]


# ── Events / timeline ────────────────────────────────────────────────────


class JobEventCreateRequest(Schema):
    """v1 JobEventCreateSerializer."""

    description: Annotated[str, Field(min_length=1, max_length=500)]


class JobEventCreateResponse(Schema):
    """v1 JobEventCreateResponseSerializer."""

    success: bool
    event: JobEventOut


class JobEventsResponse(Schema):
    """v1 JobEventsResponseSerializer."""

    events: list[JobEventOut]


class TimelineEntryOut(Schema):
    """v1 TimelineEntrySerializer (JobEvent or CostLine entry)."""

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
    """v1 JobTimelineResponseSerializer."""

    timeline: list[TimelineEntryOut]


# ── Quote acceptance ─────────────────────────────────────────────────────


class JobQuoteAcceptanceResponse(Schema):
    """v1 JobQuoteAcceptanceSerializer."""

    success: bool
    job_id: UUID
    quote_acceptance_date: str
    message: str


# ── Delta rejections ─────────────────────────────────────────────────────


class JobDeltaRejectionOut(Schema):
    """v1 JobDeltaRejectionSerializer (read-only, resolved from model rows)."""

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
        """v1 parity: detail is stored as text but served as parsed JSON when possible."""
        raw = obj.detail or ""
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return raw


class JobDeltaRejectionListResponse(Schema):
    """v1 JobDeltaRejectionListResponseSerializer."""

    count: int
    next: str | None = None
    previous: str | None = None
    results: list[JobDeltaRejectionOut]


class GroupedJobDeltaRejectionOut(Schema):
    """v1 GroupedJobDeltaRejectionSerializer."""

    fingerprint: str
    reason: str
    occurrence_count: int
    first_seen: datetime
    last_seen: datetime
    latest_id: UUID
    resolved: bool


class GroupedJobDeltaRejectionListResponse(Schema):
    """v1 GroupedJobDeltaRejectionListResponseSerializer."""

    count: int
    next: str | None = None
    previous: str | None = None
    results: list[GroupedJobDeltaRejectionOut]


class GroupedJobDeltaRejectionResolveRequest(Schema):
    """v1 GroupedJobDeltaRejectionResolveRequestSerializer.

    Identifies the group by the SHA-256 fingerprint of the reason (matches the
    ``fingerprint`` field returned in the grouped listing).
    """

    fingerprint: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class GroupedJobDeltaRejectionResolveResponse(Schema):
    """v1 GroupedJobDeltaRejectionResolveResponseSerializer."""

    updated: int


# ── Costing: cost lines, quote revisions, costs summary ──────────────────


class CostLineCreateRequest(Schema):
    """v1 CostLineCreateUpdateSerializer (create: accounting_date required)."""

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
    """v1 CostLineCreateUpdateSerializer (partial update: every field optional)."""

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
    """v1 QuoteRevisionSerializer."""

    reason: Annotated[str, Field(max_length=500)] | None = None


class QuoteRevisionResponse(Schema):
    """v1 QuoteRevisionResponseSerializer."""

    success: bool
    message: str
    quote_revision: int
    archived_cost_lines_count: int
    job_id: str


class QuoteRevisionsListResponse(Schema):
    """v1 QuoteRevisionsListSerializer."""

    job_id: str
    job_number: int
    current_cost_set_rev: int
    total_revisions: int
    revisions: list[dict[str, object]]


class JobCostSummaryResponse(Schema):
    """v1 JobCostSummaryResponseSerializer.

    Entries reuse ``CostSetSummaryOut``: the profitMargin formula was
    standardised on margin-on-revenue by user decision 2026-08-02 (v1's
    costs/summary reported markup-on-cost under the same field name).
    """

    estimate: CostSetSummaryOut | None
    quote: CostSetSummaryOut | None
    actual: CostSetSummaryOut | None


# ── Labour subtypes and job labour rates ─────────────────────────────────


class LabourSubtypeOut(Schema):
    """v1 LabourSubtypeSerializer (active-subtype dropdown row)."""

    id: UUID
    name: str
    display_order: int
    is_active: bool
    is_workshop: bool
    default_charge_out_rate: Decimal


class LabourSubtypeManageOut(Schema):
    """v1 LabourSubtypeManageSerializer (management UI row)."""

    id: UUID
    name: str
    display_order: int
    is_active: bool
    is_workshop: bool
    counts_for_scheduling: bool
    default_charge_out_rate: Decimal


class LabourSubtypeManageCreateRequest(Schema):
    """v1 LabourSubtypeManageSerializer write fields (create)."""

    name: Annotated[str, Field(min_length=1, max_length=100)]
    display_order: Annotated[int, Field(ge=0)] = 0
    is_active: bool = True
    is_workshop: bool = False
    counts_for_scheduling: bool = False
    default_charge_out_rate: Annotated[Decimal, Field(ge=0)]


class LabourSubtypeManageUpdateRequest(Schema):
    """v1 LabourSubtypeManageSerializer write fields (partial update)."""

    name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    display_order: Annotated[int, Field(ge=0)] | None = None
    is_active: bool | None = None
    is_workshop: bool | None = None
    counts_for_scheduling: bool | None = None
    default_charge_out_rate: Annotated[Decimal, Field(ge=0)] | None = None


class JobLabourRateOut(Schema):
    """v1 JobLabourRateSerializer."""

    id: UUID
    labour_subtype: UUID
    labour_subtype_name: str
    is_workshop: bool
    charge_out_rate: Decimal


class JobLabourRateUpdateEntry(Schema):
    """v1 JobLabourRateUpdateSerializer (one rate change)."""

    labour_subtype: UUID
    charge_out_rate: Annotated[Decimal, Field(ge=0)]


class JobLabourRatesUpdateRequest(Schema):
    """v1 JobLabourRatesUpdateRequestSerializer."""

    rates: Annotated[list[JobLabourRateUpdateEntry], Field(min_length=1)]


# ── Kanban ───────────────────────────────────────────────────────────────


class KanbanJobPersonOut(Schema):
    """v1 KanbanJobPersonSerializer (assigned staff on a card)."""

    id: UUID
    display_name: str
    # Plain str, not a URL type: icon URLs are site-root-relative (/media/...)
    # so the browser resolves them against its own origin (v1 comment).
    icon_url: str | None


class KanbanJobOut(Schema):
    """v1 KanbanJobSerializer (fetch-all / fetch-by-status / advanced search)."""

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
    """v1 KanbanColumnJobSerializer (adds badge info for the column view)."""

    badge_label: str
    badge_color: str


class FetchAllJobsResponse(Schema):
    """v1 FetchAllJobsResponseSerializer."""

    success: bool = True
    active_jobs: list[KanbanJobOut] = Field(default_factory=list)
    archived_jobs: list[KanbanJobOut] = Field(default_factory=list)
    total_archived: int = 0


class FetchJobsResponse(Schema):
    """v1 FetchJobsResponseSerializer."""

    success: bool = True
    jobs: list[KanbanJobOut] = Field(default_factory=list)
    total: int = 0
    filtered_count: int = 0


class FetchJobsByColumnResponse(Schema):
    """v1 FetchJobsByColumnResponseSerializer."""

    success: bool = True
    jobs: list[KanbanColumnJobOut] = Field(default_factory=list)
    total: int = 0
    filtered_count: int = 0
    has_more: bool | None = None
    error: str | None = None


class FetchStatusValuesResponse(Schema):
    """v1 FetchStatusValuesResponseSerializer."""

    success: bool = True
    statuses: dict[str, str] = Field(default_factory=dict)
    tooltips: dict[str, str] = Field(default_factory=dict)


class AdvancedSearchResponse(Schema):
    """v1 AdvancedSearchResponseSerializer."""

    success: bool = True
    jobs: list[KanbanJobOut] = Field(default_factory=list)
    total: int = 0


class KanbanChangesResponse(Schema):
    """v1 KanbanChangesResponseSerializer (incremental reconciliation)."""

    success: bool
    jobs: list[KanbanColumnJobOut]
    removed_job_ids: list[UUID]
    full_refresh_required: bool


class KanbanSuccessResponse(Schema):
    """v1 KanbanSuccessResponseSerializer."""

    success: bool = True
    message: str


class JobStatusUpdateRequest(Schema):
    """v1 JobStatusUpdateSerializer."""

    status: str


class JobReorderRequest(Schema):
    """v1 JobReorderSerializer (cross-field rules enforced in the endpoint)."""

    anchor_job_id: UUID | None = None
    placement: str | None = None
    status: str | None = None


class AssignJobRequest(Schema):
    """v1 AssignJobSerializer (job_id comes from the URL)."""

    staff_id: UUID


class AssignJobResponse(Schema):
    """v1 AssignJobResponseSerializer."""

    success: bool
    message: str | None = None
    error: str | None = None


# ── Job files ────────────────────────────────────────────────────────────


class JobFileUploadSuccessResponse(Schema):
    """v1 JobFileUploadSuccessResponseSerializer."""

    status: str = "success"
    uploaded: list[JobFileOut]
    message: str


class JobFileUploadPartialResponse(Schema):
    """v1 JobFileUploadPartialResponseSerializer."""

    status: str
    uploaded: list[JobFileOut]
    errors: list[str]


class JobFileUpdateRequest(Schema):
    """v1 updateJobFile body (both fields optional; only provided ones apply)."""

    print_on_jobsheet: bool | None = None
    filename: str | None = None


class JobFileUpdateSuccessResponse(Schema):
    """v1 JobFileUpdateSuccessResponseSerializer (+ filename, as the v1 body)."""

    status: str = "success"
    message: str
    print_on_jobsheet: bool
    filename: str
