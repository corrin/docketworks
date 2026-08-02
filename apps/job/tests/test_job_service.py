"""Service-level tests for apps.job.services.job_service (ported from v1).

Covers job creation cost lines, edit serialisation, the delta-envelope
update pipeline (checksum validation, rejection recording, ETag enforcement),
undo, and the delete guard.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from apps.accounts.models import Staff
from apps.company.models import Company, Person
from apps.company.tests.job_fixtures import make_job
from apps.core.etag import PreconditionFailedError, generate_updated_at_etag
from apps.core.models import CompanyDefaults
from apps.job.models import Job, JobDeltaRejection, JobEvent, LabourSubtype
from apps.job.models.costing import CostLine
from apps.job.services import job_service
from apps.job.services.delta_checksum import compute_job_delta_checksum
from apps.job.services.job_service import DeltaValidationError

pytestmark = pytest.mark.django_db


def _etag(job: Job) -> str:
    job.refresh_from_db()
    return generate_updated_at_etag("job", job.id, job.updated_at)


def _envelope(job: Job, field: str, after: object) -> dict[str, object]:
    """Build a valid delta envelope for one field from the current DB state."""
    before = getattr(job, "status" if field == "job_status" else field)
    return {
        "change_id": str(uuid4()),
        "job_id": str(job.id),
        "fields": [field],
        "before": {field: before},
        "after": {field: after},
        "before_checksum": compute_job_delta_checksum(job.id, {field: before}, [field]),
    }


class TestCreateJob:
    def test_fixed_price_create_copies_estimate_pay_item(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = job_service.create_job(
            {
                "name": "Fixed Price Job",
                "company_id": company.id,
                "pricing_methodology": "fixed_price",
                "estimated_materials": Decimal("120.00"),
                "estimated_time": Decimal("2.50"),
            },
            office_staff,
        )

        estimate_qs = CostLine.objects.filter(cost_set=job.latest_estimate)
        estimate_lines = list(estimate_qs.order_by("desc"))
        quote_lines = list(CostLine.objects.filter(cost_set=job.latest_quote).order_by("desc"))
        estimate_pay_items = {line.desc: line.xero_pay_item_id for line in estimate_lines}
        quote_pay_items = {line.desc: line.xero_pay_item_id for line in quote_lines}

        assert len(quote_lines) == len(estimate_lines) == 3
        assert quote_pay_items == estimate_pay_items

    def test_create_records_job_created_event(self, company: Company, office_staff: Staff) -> None:
        job = job_service.create_job(
            {
                "name": "Evented Job",
                "company_id": company.id,
                "estimated_materials": Decimal("0.00"),
                "estimated_time": Decimal("1.00"),
            },
            office_staff,
        )

        events = JobEvent.objects.filter(job=job, event_type="job_created")
        assert events.count() == 1

    def test_create_rejects_company_that_disallows_jobs(
        self, company: Company, office_staff: Staff
    ) -> None:
        company.allow_jobs = False
        company.save(update_fields=["allow_jobs"])

        with pytest.raises(ValueError, match="not permitted for jobs"):
            job_service.create_job(
                {
                    "name": "Blocked Job",
                    "company_id": company.id,
                    "estimated_materials": Decimal("1.00"),
                    "estimated_time": Decimal("1.00"),
                },
                office_staff,
            )


class TestGetJobForEdit:
    def test_serializes_event_staff_and_job_payload(
        self, job: Job, office_staff: Staff, company: Company
    ) -> None:
        person = Person.objects.create(name="Site Contact")
        job.person = person
        job.save(staff=office_staff, update_fields=["person"])
        JobEvent.objects.create(
            job=job,
            staff=office_staff,
            event_type="job_created",
            detail={"job_name": job.name},
        )

        result = job_service.get_job_for_edit(job.id)

        assert result["events"][0]["staff"] == "Office Staff"
        assert result["job"]["company_name"] == company.name
        assert result["job"]["person_name"] == "Site Contact"
        assert result["job"]["job_status"] == "draft"
        latest_actual = result["job"]["latest_actual"]
        assert latest_actual is not None
        assert latest_actual["summary"]["profitMargin"] == 0.0

    def test_missing_job_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            job_service.get_job_for_edit(uuid4())


class TestUpdateJob:
    def test_valid_delta_updates_field_and_records_event(
        self, job: Job, office_staff: Staff
    ) -> None:
        payload = _envelope(job, "description", "Cut and fold")

        updated = job_service.update_job(job.id, payload, office_staff, _etag(job))

        assert updated.description == "Cut and fold"
        event = JobEvent.objects.filter(job=job, event_type="job_updated").latest("timestamp")
        assert event.schema_version == 1
        assert str(event.change_id) == payload["change_id"]
        assert event.delta_before == {"description": None}
        assert event.delta_after == {"description": "Cut and fold"}

    def test_status_change_bumps_priority_to_top_of_new_column(
        self, job: Job, office_staff: Staff, company: Company
    ) -> None:
        other = make_job(company, office_staff, name="Occupies Column")
        other.status = "in_progress"
        other.save(staff=office_staff, update_fields=["status"])
        other.refresh_from_db()

        payload = _envelope(job, "job_status", "in_progress")
        updated = job_service.update_job(job.id, payload, office_staff, _etag(job))

        assert updated.status == "in_progress"
        assert updated.priority > other.priority

    def test_hard_checksum_mismatch_records_the_rejection(
        self, job: Job, office_staff: Staff
    ) -> None:
        """A refused delta must leave a JobDeltaRejection explaining why.

        ``DeltaValidationError`` subclasses ``PreconditionFailedError``; if the
        broader handler is ordered first the specific one is swallowed and the
        only record of why a client's edit was refused disappears.
        """
        defaults = CompanyDefaults.get_solo()
        defaults.job_delta_soft_fail = False
        defaults.save(update_fields=["job_delta_soft_fail"])

        payload = {
            "change_id": str(uuid4()),
            "fields": ["description"],
            "before": {"description": job.description},
            "after": {"description": "Edited elsewhere"},
            "before_checksum": "stale-checksum-from-an-older-read",
        }

        with pytest.raises(DeltaValidationError):
            job_service.update_job(job.id, payload, office_staff, _etag(job))

        rejection = JobDeltaRejection.objects.get()
        assert "checksum mismatch" in rejection.reason.lower()
        assert str(rejection.change_id) == payload["change_id"]

    def test_soft_fail_applies_change_but_records_mismatch(
        self, job: Job, office_staff: Staff
    ) -> None:
        defaults = CompanyDefaults.get_solo()
        defaults.job_delta_soft_fail = True
        defaults.save(update_fields=["job_delta_soft_fail"])

        payload = _envelope(job, "description", "Soft-fail edit")
        payload["before_checksum"] = "stale-checksum"

        updated = job_service.update_job(job.id, payload, office_staff, _etag(job))

        assert updated.description == "Soft-fail edit"
        rejection = JobDeltaRejection.objects.get()
        assert rejection.reason == "Delta checksum mismatch (soft-fail)"

    def test_stale_etag_raises_precondition_failed(self, job: Job, office_staff: Staff) -> None:
        payload = _envelope(job, "description", "New description")

        with pytest.raises(PreconditionFailedError):
            job_service.update_job(job.id, payload, office_staff, '"job:stale:etag"')

    def test_missing_envelope_is_rejected(self, job: Job, office_staff: Staff) -> None:
        with pytest.raises(ValueError, match="Delta envelope is required"):
            job_service.update_job(
                job.id, {"description": "Bare field update"}, office_staff, _etag(job)
            )

    def test_unsupported_field_is_rejected(self, job: Job, office_staff: Staff) -> None:
        payload = {
            "change_id": str(uuid4()),
            "fields": ["job_number"],
            "before": {"job_number": job.job_number},
            "after": {"job_number": 999},
            "before_checksum": compute_job_delta_checksum(
                job.id, {"job_number": job.job_number}, ["job_number"]
            ),
        }

        with pytest.raises(ValueError, match="Unsupported field"):
            job_service.update_job(job.id, payload, office_staff, _etag(job))

    def test_negative_people_bounds_are_rejected(self, job: Job, office_staff: Staff) -> None:
        payload = _envelope(job, "min_people", -1)

        with pytest.raises(ValueError, match="cannot be negative"):
            job_service.update_job(job.id, payload, office_staff, _etag(job))

    def test_price_cap_magnitude_and_precision_bounds(self, job: Job, office_staff: Staff) -> None:
        """price_cap is DecimalField(max_digits=10, dp=2): overflow/precision 400."""
        too_big = _envelope(job, "price_cap", "100000000.00")
        with pytest.raises(ValueError, match="exceeds the allowed magnitude"):
            job_service.update_job(job.id, too_big, office_staff, _etag(job))

        too_precise = _envelope(job, "price_cap", "10.999")
        with pytest.raises(ValueError, match="at most 2 decimal places"):
            job_service.update_job(job.id, too_precise, office_staff, _etag(job))

    def test_blank_string_for_nullable_text_is_rejected(
        self, job: Job, office_staff: Staff
    ) -> None:
        """NULL is the only unset: '' must 400 at the boundary, not 500 in the DB."""
        payload = _envelope(job, "notes", "")

        with pytest.raises(ValueError, match="cannot be blank"):
            job_service.update_job(job.id, payload, office_staff, _etag(job))


class TestUndoJobChange:
    def test_undo_reverts_the_recorded_delta(self, job: Job, office_staff: Staff) -> None:
        payload = _envelope(job, "description", "First edit")
        job_service.update_job(job.id, payload, office_staff, _etag(job))
        job.refresh_from_db()
        assert job.description == "First edit"

        change_id = job_service._safe_uuid(payload["change_id"])
        assert change_id is not None
        updated = job_service.undo_job_change(job.id, change_id, office_staff, _etag(job))

        assert updated.description is None
        undo_event = JobEvent.objects.filter(job=job).latest("timestamp")
        assert undo_event.delta_meta is not None
        assert undo_event.delta_meta["undo_of_change_id"] == payload["change_id"]

    def test_undo_refuses_when_state_moved_on(self, job: Job, office_staff: Staff) -> None:
        first = _envelope(job, "description", "First edit")
        job_service.update_job(job.id, first, office_staff, _etag(job))
        job.refresh_from_db()
        second = _envelope(job, "description", "Second edit")
        job_service.update_job(job.id, second, office_staff, _etag(job))
        job.refresh_from_db()

        change_id = job_service._safe_uuid(first["change_id"])
        assert change_id is not None
        with pytest.raises(PreconditionFailedError):
            job_service.undo_job_change(job.id, change_id, office_staff, _etag(job))

        rejection = JobDeltaRejection.objects.latest("created_at")
        assert rejection.reason == "Undo delta mismatch"


class TestDeleteJob:
    def test_delete_refuses_job_with_real_costs(self, job: Job, office_staff: Staff) -> None:
        CostLine.objects.create(
            cost_set=job.latest_actual,
            kind="material",
            desc="Real spend",
            quantity=Decimal("1.000"),
            unit_cost=Decimal("10.00"),
            unit_rev=Decimal("15.00"),
            accounting_date=job.created_at.date(),
        )

        with pytest.raises(ValueError, match="real costs or revenue"):
            job_service.delete_job(job.id, office_staff, _etag(job))

    def test_delete_succeeds_for_clean_job(self, job: Job, office_staff: Staff) -> None:
        result = job_service.delete_job(job.id, office_staff, _etag(job))

        assert result["success"] is True
        assert not Job.objects.filter(id=job.id).exists()


class TestAcceptQuote:
    def test_accept_quote_moves_job_to_approved(self, job: Job, office_staff: Staff) -> None:
        result = job_service.accept_quote(job.id, office_staff, _etag(job))

        job.refresh_from_db()
        assert result["success"] is True
        assert job.status == "approved"
        assert job.quote_acceptance_date is not None
        event = JobEvent.objects.filter(job=job).latest("timestamp")
        assert event.event_type == "quote_accepted"

    def test_accept_quote_twice_is_rejected(self, job: Job, office_staff: Staff) -> None:
        job_service.accept_quote(job.id, office_staff, _etag(job))

        with pytest.raises(ValueError, match="already been accepted"):
            job_service.accept_quote(job.id, office_staff, _etag(job))


class TestTimeline:
    def test_timeline_merges_events_and_cost_lines(self, job: Job, office_staff: Staff) -> None:
        JobEvent.objects.create(
            job=job,
            staff=office_staff,
            event_type="manual_note",
            detail={"note_text": "A note"},
        )
        CostLine.objects.create(
            cost_set=job.latest_actual,
            kind="time",
            desc="Welding",
            quantity=Decimal("2.000"),
            unit_cost=Decimal("32.00"),
            unit_rev=Decimal("0.00"),
            accounting_date=job.created_at.date(),
            staff=office_staff,
            xero_pay_item=job.default_xero_pay_item,
            labour_subtype=LabourSubtype.default_workshop(),
        )

        timeline = job_service.get_job_timeline(job.id)

        entry_types = {entry["entry_type"] for entry in timeline}
        assert "event" in entry_types
        assert "costline_created" in entry_types
        note_entry = next(e for e in timeline if e["entry_type"] == "event")
        assert note_entry["description"] == "A note"
        line_entry = next(e for e in timeline if e["entry_type"] == "costline_created")
        assert line_entry["description"] == "Welding (2.00 hours)"
