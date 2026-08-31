"""API tests for the costing endpoints (django test Client, house pattern).

Guards the wire contract for cost-set retrieval (rev handling, grid line
order, profitMargin, summary key filtering), cost-line CRUD (auth split,
validation, model-driven summary reconciliation, stock adjustment), quote
revisions (archive/clear/acceptance reset, revision numbering) and the costs
summary endpoint (margin-on-revenue formula per the 2026-08-02 user
decision, conditional GET).
"""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.tests.conftest import authenticate
from apps.job.models import Job, LabourSubtype
from apps.job.models.costing import CostLine, CostSet
from apps.purchasing.models import Stock

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.job.tests.urls"),
]

ACCOUNTING_DATE = date(2026, 8, 1)


def _make_line(
    cost_set: CostSet,
    *,
    kind: str = "material",
    quantity: str = "1.000",
    unit_cost: str = "100.00",
    unit_rev: str = "150.00",
    **extra: object,
) -> CostLine:
    if kind == "time" and "labour_subtype" not in extra:
        extra["labour_subtype"] = LabourSubtype.default_workshop()
    line = CostLine(
        cost_set=cost_set,
        kind=kind,
        desc=f"Test {kind} line",
        quantity=Decimal(quantity),
        unit_cost=Decimal(unit_cost),
        unit_rev=Decimal(unit_rev),
        accounting_date=ACCOUNTING_DATE,
        **extra,
    )
    line.save()
    return line


def _workshop_client(workshop_staff: Staff) -> Client:
    client = Client()
    authenticate(client, workshop_staff)
    return client


class TestCostSetRetrieve:
    def test_invalid_kind_is_400(self, client: Client, job: Job) -> None:
        response = client.get(f"/api/job/jobs/{job.id}/cost_sets/bogus/")
        assert response.status_code == 400
        assert "Invalid kind" in response.json()["detail"]

    def test_invalid_kind_beats_unknown_job(self, client: Client) -> None:
        # Kind validation precedes job lookup: 400, not 404.
        response = client.get(f"/api/job/jobs/{uuid4()}/cost_sets/bogus/")
        assert response.status_code == 400
        assert "Invalid kind" in response.json()["detail"]

    def test_unknown_job_is_404(self, client: Client) -> None:
        assert client.get(f"/api/job/jobs/{uuid4()}/cost_sets/estimate/").status_code == 404

    def test_returns_lines_in_grid_order_with_margin(self, client: Client, job: Job) -> None:
        estimate = job.cost_sets.get(kind="estimate")
        _make_line(estimate, kind="time", quantity="2.000", unit_cost="40.00", unit_rev="105.00")
        _make_line(estimate, kind="material", unit_cost="100.00", unit_rev="150.00")
        _make_line(estimate, kind="adjust", unit_cost="10.00", unit_rev="10.00")

        response = client.get(f"/api/job/jobs/{job.id}/cost_sets/estimate/")

        assert response.status_code == 200
        body = response.json()
        assert body["kind"] == "estimate"
        assert body["rev"] == estimate.rev
        # Contracted grid order: material, adjustment, then time.
        assert [line["kind"] for line in body["cost_lines"]] == ["material", "adjust", "time"]
        summary = body["summary"]
        # cost = 2*40 + 100 + 10 = 190; rev = 2*105 + 150 + 10 = 370; hours = 2
        assert summary["cost"] == 190.0
        assert summary["rev"] == 370.0
        assert summary["hours"] == 2.0
        # CostSetSerializer margin is over rev: (370-190)/370*100
        assert summary["profitMargin"] == pytest.approx((370 - 190) / 370 * 100)

    def test_returns_newest_cost_set_rev(self, client: Client, job: Job) -> None:
        CostSet.objects.create(job=job, kind="estimate", rev=2)

        response = client.get(f"/api/job/jobs/{job.id}/cost_sets/estimate/")

        assert response.status_code == 200
        assert response.json()["rev"] == 2


class TestCostLineCreate:
    def _payload(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": "material",
            "desc": "Sheet steel",
            "quantity": "2.000",
            "unit_cost": "50.00",
            "unit_rev": "75.00",
            "accounting_date": ACCOUNTING_DATE.isoformat(),
        }
        payload.update(overrides)
        return payload

    def test_create_on_estimate_updates_summary(self, client: Client, job: Job) -> None:
        response = client.post(
            f"/api/job/jobs/{job.id}/cost_sets/estimate/cost_lines/",
            data=self._payload(),
            content_type="application/json",
        )

        assert response.status_code == 201
        body = response.json()
        assert body["kind"] == "material"
        assert body["total_cost"] == 100.0
        assert body["total_rev"] == 150.0
        assert body["approved"] is True  # created by office staff
        # The model machinery reconciled the CostSet summary
        estimate = job.cost_sets.get(kind="estimate")
        assert estimate.summary["cost"] == 100.0
        assert estimate.summary["rev"] == 150.0

    def test_workshop_staff_cannot_create_non_actual(self, job: Job, workshop_staff: Staff) -> None:
        response = _workshop_client(workshop_staff).post(
            f"/api/job/jobs/{job.id}/cost_sets/estimate/cost_lines/",
            data=self._payload(),
            content_type="application/json",
        )
        assert response.status_code == 403
        assert "Only office staff" in response.json()["detail"]

    def test_workshop_staff_creates_unapproved_actual_line(
        self, job: Job, workshop_staff: Staff
    ) -> None:
        response = _workshop_client(workshop_staff).post(
            f"/api/job/jobs/{job.id}/cost_sets/actual/cost_lines/",
            data=self._payload(),
            content_type="application/json",
        )
        assert response.status_code == 201
        assert response.json()["approved"] is False

    def test_invalid_kind_is_400(self, client: Client, job: Job) -> None:
        response = client.post(
            f"/api/job/jobs/{job.id}/cost_sets/bogus/cost_lines/",
            data=self._payload(),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_missing_accounting_date_is_rejected(self, client: Client, job: Job) -> None:
        payload = self._payload()
        del payload["accounting_date"]
        response = client.post(
            f"/api/job/jobs/{job.id}/cost_sets/estimate/cost_lines/",
            data=payload,
            content_type="application/json",
        )
        # Schema-level validation rejects the request before the service runs.
        assert response.status_code == 422

    def test_negative_quantity_is_400(self, client: Client, job: Job) -> None:
        response = client.post(
            f"/api/job/jobs/{job.id}/cost_sets/estimate/cost_lines/",
            data=self._payload(quantity="-1.000"),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "Quantity must be non-negative" in response.json()["detail"]

    def test_time_line_requires_labour_subtype(self, client: Client, job: Job) -> None:
        response = client.post(
            f"/api/job/jobs/{job.id}/cost_sets/estimate/cost_lines/",
            data=self._payload(kind="time"),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "labour_subtype is required for time lines" in response.json()["detail"]

    def test_time_line_with_a_malformed_meta_time_is_rejected(
        self, client: Client, job: Job
    ) -> None:
        """A non-clock start_time in meta must be refused at the write.

        The my-time calendar reads these back through time.fromisoformat, so a
        stored "morning" turns a later GET into a 500 — the write is where the
        shape is enforceable.
        """
        workshop = LabourSubtype.default_workshop()
        for bad_time in ("morning", "25:00:00", "08:61:00"):
            response = client.post(
                f"/api/job/jobs/{job.id}/cost_sets/estimate/cost_lines/",
                data=self._payload(
                    kind="time",
                    labour_subtype=str(workshop.id),
                    meta={"start_time": bad_time},
                ),
                content_type="application/json",
            )
            assert response.status_code == 400, bad_time
            assert "start_time" in response.json()["detail"]

    def test_time_line_with_labour_subtype_created(self, client: Client, job: Job) -> None:
        workshop = LabourSubtype.default_workshop()
        response = client.post(
            f"/api/job/jobs/{job.id}/cost_sets/estimate/cost_lines/",
            data=self._payload(kind="time", labour_subtype=str(workshop.id)),
            content_type="application/json",
        )
        assert response.status_code == 201
        assert response.json()["labour_subtype"] == str(workshop.id)
        estimate = job.cost_sets.get(kind="estimate")
        assert estimate.summary["hours"] == 2.0

    def test_timesheet_line_is_priced_by_the_rate_pipeline(
        self, client: Client, job: Job, timesheet_worker: Staff
    ) -> None:
        """The seam is closed: a timesheet line prices itself instead of 400ing."""
        job.labour_rates.filter(labour_subtype=LabourSubtype.default_workshop()).update(
            charge_out_rate=Decimal("120.00")
        )
        response = client.post(
            f"/api/job/jobs/{job.id}/cost_sets/actual/cost_lines/",
            data=self._payload(
                kind="time",
                unit_cost="0.00",
                unit_rev="0.00",
                meta={
                    "created_from_timesheet": True,
                    "staff_id": str(timesheet_worker.id),
                    "wage_rate_multiplier": 1.5,
                },
            ),
            content_type="application/json",
        )

        assert response.status_code == 201, response.content
        body = response.json()
        # wage_rate 48.00 (40 base + 20% loading) * 1.5; charge-out 120.00 * 1.5
        assert Decimal(body["unit_cost"]) == Decimal("72.00")
        assert Decimal(body["unit_rev"]) == Decimal("180.00")
        assert body["staff"] == str(timesheet_worker.id)
        # The subtype defaulted from the worker even though the payload omitted it.
        assert body["labour_subtype"] == str(LabourSubtype.default_workshop().id)
        assert body["xero_pay_item"] is not None
        assert body["meta"]["is_billable"] is True
        assert body["meta"]["charge_out_rate"] == 120.0

    def test_timesheet_line_for_staff_without_a_wage_rate_is_400(
        self, client: Client, job: Job, unpaid_staff: Staff
    ) -> None:
        """No silent fallback: an unconfigured wage rate is a 400 naming the staff member."""
        response = client.post(
            f"/api/job/jobs/{job.id}/cost_sets/actual/cost_lines/",
            data=self._payload(
                kind="time",
                meta={
                    "created_from_timesheet": True,
                    "staff_id": str(unpaid_staff.id),
                    "wage_rate_multiplier": 1.0,
                },
            ),
            content_type="application/json",
        )

        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "Wage rate is not configured" in detail
        assert "Unpriced Person" in detail
        assert not CostLine.objects.filter(staff=unpaid_staff).exists()

    def test_timesheet_line_without_staff_id_is_400(self, client: Client, job: Job) -> None:
        response = client.post(
            f"/api/job/jobs/{job.id}/cost_sets/actual/cost_lines/",
            data=self._payload(
                kind="time",
                meta={"created_from_timesheet": True, "wage_rate_multiplier": 1.0},
            ),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "Staff id must be provided" in response.json()["detail"]

    def test_blank_desc_is_400(self, client: Client, job: Job) -> None:
        # v1's own desc_not_blank DB constraint made this a 500; v2 surfaces
        # the same rule as a 400 via full_clean (parity ledger 2026-08-02).
        response = client.post(
            f"/api/job/jobs/{job.id}/cost_sets/estimate/cost_lines/",
            data=self._payload(desc=""),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "desc_not_blank" in response.json()["detail"]


class TestCostLineUpdate:
    def test_patch_quantity_recalculates_summary(self, client: Client, job: Job) -> None:
        estimate = job.cost_sets.get(kind="estimate")
        line = _make_line(estimate, quantity="1.000", unit_cost="100.00", unit_rev="150.00")

        response = client.patch(
            f"/api/job/cost_lines/{line.id}/",
            data={"quantity": "3.000"},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["total_cost"] == 300.0
        estimate.refresh_from_db()
        assert estimate.summary["cost"] == 300.0
        assert estimate.summary["rev"] == 450.0

    def test_patch_adjusts_linked_stock_by_quantity_diff(self, client: Client, job: Job) -> None:
        stock = Stock.objects.create(
            description="Steel offcut",
            quantity=Decimal("10.00"),
            unit_cost=Decimal("5.00"),
            source="manual",
        )
        actual = job.cost_sets.get(kind="actual")
        line = _make_line(actual, quantity="1.000", ext_refs={"stock_id": str(stock.id)})

        response = client.patch(
            f"/api/job/cost_lines/{line.id}/",
            data={"quantity": "4.000"},
            content_type="application/json",
        )

        assert response.status_code == 200
        stock.refresh_from_db()
        assert stock.quantity == Decimal("7.00")  # 10 - (4 - 1)

    def test_patch_on_estimate_line_never_moves_stock(self, client: Client, job: Job) -> None:
        # Only actual lines consume inventory: an estimate references a stock
        # item hypothetically, so a quantity edit there must not draw it down.
        stock = Stock.objects.create(
            description="Steel offcut",
            quantity=Decimal("10.00"),
            unit_cost=Decimal("5.00"),
            source="manual",
        )
        estimate = job.cost_sets.get(kind="estimate")
        line = _make_line(estimate, quantity="1.000", ext_refs={"stock_id": str(stock.id)})

        response = client.patch(
            f"/api/job/cost_lines/{line.id}/",
            data={"quantity": "10.000"},
            content_type="application/json",
        )

        assert response.status_code == 200
        stock.refresh_from_db()
        assert stock.quantity == Decimal("10.00")

    def test_workshop_staff_cannot_patch_non_actual(self, job: Job, workshop_staff: Staff) -> None:
        estimate = job.cost_sets.get(kind="estimate")
        line = _make_line(estimate)
        response = _workshop_client(workshop_staff).patch(
            f"/api/job/cost_lines/{line.id}/",
            data={"quantity": "2.000"},
            content_type="application/json",
        )
        assert response.status_code == 403

    def _create_timesheet_line(
        self, client: Client, job: Job, worker: Staff, **meta: object
    ) -> str:
        """Create a priced timesheet line through the API and return its id."""
        payload: dict[str, object] = {
            "kind": "time",
            "desc": "Timesheet entry",
            "quantity": "1.000",
            "unit_cost": "0.00",
            "unit_rev": "0.00",
            "accounting_date": ACCOUNTING_DATE.isoformat(),
            "meta": {
                "created_from_timesheet": True,
                "staff_id": str(worker.id),
                "wage_rate_multiplier": 1.0,
                **meta,
            },
        }
        response = client.post(
            f"/api/job/jobs/{job.id}/cost_sets/actual/cost_lines/",
            data=payload,
            content_type="application/json",
        )
        assert response.status_code == 201, response.content
        return str(response.json()["id"])

    def test_patch_subtype_of_timesheet_line_reprices_it(
        self, client: Client, job: Job, timesheet_worker: Staff
    ) -> None:
        """Seam closure: a subtype-only PATCH reprices via the rate pipeline.

        The patch carries no meta at all, so the service must pull the stored
        meta to know the line is a timesheet entry (v1
        CostLineCreateUpdateSerializer.save).
        """
        workshop = LabourSubtype.default_workshop()
        onsite = LabourSubtype.objects.get(name="Onsite")
        job.labour_rates.filter(labour_subtype=workshop).update(charge_out_rate=Decimal("120.00"))
        job.labour_rates.filter(labour_subtype=onsite).update(charge_out_rate=Decimal("165.00"))
        line_id = self._create_timesheet_line(client, job, timesheet_worker)

        response = client.patch(
            f"/api/job/cost_lines/{line_id}/",
            data={"labour_subtype": str(onsite.id)},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["labour_subtype"] == str(onsite.id)
        # Repriced onto the Onsite charge-out rate; cost from the worker's wage.
        assert Decimal(body["unit_rev"]) == Decimal("165.00")
        assert Decimal(body["unit_cost"]) == Decimal("48.00")
        assert body["meta"]["charge_out_rate"] == 165.0

    def test_explicit_null_labour_subtype_keeps_the_lines_subtype(
        self, client: Client, job: Job, timesheet_worker: Staff
    ) -> None:
        """v1: `validated_data.get(...) or instance.labour_subtype`.

        Resetting to the worker's default instead would silently reprice the line
        off the Onsite rate and back onto Workshop.
        """
        workshop = LabourSubtype.default_workshop()
        onsite = LabourSubtype.objects.get(name="Onsite")
        job.labour_rates.filter(labour_subtype=workshop).update(charge_out_rate=Decimal("120.00"))
        job.labour_rates.filter(labour_subtype=onsite).update(charge_out_rate=Decimal("165.00"))
        line_id = self._create_timesheet_line(client, job, timesheet_worker)
        client.patch(
            f"/api/job/cost_lines/{line_id}/",
            data={"labour_subtype": str(onsite.id)},
            content_type="application/json",
        )

        response = client.patch(
            f"/api/job/cost_lines/{line_id}/",
            data={"labour_subtype": None, "desc": "Renamed"},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["labour_subtype"] == str(onsite.id)
        assert Decimal(body["unit_rev"]) == Decimal("165.00")

    def test_patch_with_timesheet_meta_reprices_the_line(
        self, client: Client, job: Job, timesheet_worker: Staff
    ) -> None:
        job.labour_rates.filter(labour_subtype=LabourSubtype.default_workshop()).update(
            charge_out_rate=Decimal("120.00")
        )
        line_id = self._create_timesheet_line(client, job, timesheet_worker)

        response = client.patch(
            f"/api/job/cost_lines/{line_id}/",
            data={
                "meta": {
                    "created_from_timesheet": True,
                    "staff_id": str(timesheet_worker.id),
                    "wage_rate_multiplier": 2.0,
                    "is_billable": False,
                }
            },
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        body = response.json()
        assert Decimal(body["unit_cost"]) == Decimal("96.00")  # 48.00 * 2
        assert Decimal(body["unit_rev"]) == Decimal("0.00")  # not billable
        assert body["meta"]["is_billable"] is False

    def test_unknown_line_is_404(self, client: Client) -> None:
        response = client.patch(
            f"/api/job/cost_lines/{uuid4()}/",
            data={"quantity": "2.000"},
            content_type="application/json",
        )
        assert response.status_code == 404


class TestCostLineDelete:
    def test_delete_returns_stock_and_recalculates_summary(self, client: Client, job: Job) -> None:
        stock = Stock.objects.create(
            description="Steel offcut",
            quantity=Decimal("10.00"),
            unit_cost=Decimal("5.00"),
            source="manual",
        )
        actual = job.cost_sets.get(kind="actual")
        line = _make_line(actual, quantity="2.000", ext_refs={"stock_id": str(stock.id)})
        actual.refresh_from_db()
        assert actual.summary["cost"] == 200.0

        response = client.delete(f"/api/job/cost_lines/{line.id}/delete/")

        assert response.status_code == 204
        assert not CostLine.objects.filter(id=line.id).exists()
        stock.refresh_from_db()
        assert stock.quantity == Decimal("12.00")  # 10 + 2 returned
        actual.refresh_from_db()
        assert actual.summary["cost"] == 0.0

    def test_delete_of_estimate_line_never_returns_stock(self, client: Client, job: Job) -> None:
        # An estimate line never consumed inventory, so deleting it must not
        # conjure stock that was never drawn.
        stock = Stock.objects.create(
            description="Steel offcut",
            quantity=Decimal("10.00"),
            unit_cost=Decimal("5.00"),
            source="manual",
        )
        estimate = job.cost_sets.get(kind="estimate")
        line = _make_line(estimate, quantity="2.000", ext_refs={"stock_id": str(stock.id)})

        response = client.delete(f"/api/job/cost_lines/{line.id}/delete/")

        assert response.status_code == 204
        stock.refresh_from_db()
        assert stock.quantity == Decimal("10.00")

    def test_workshop_staff_cannot_delete_non_actual(self, job: Job, workshop_staff: Staff) -> None:
        estimate = job.cost_sets.get(kind="estimate")
        line = _make_line(estimate)
        response = _workshop_client(workshop_staff).delete(f"/api/job/cost_lines/{line.id}/delete/")
        assert response.status_code == 403

    def test_unknown_line_is_404(self, client: Client) -> None:
        assert client.delete(f"/api/job/cost_lines/{uuid4()}/delete/").status_code == 404


class TestCopyEstimateToQuote:
    def _copy(self, client: Client, job: Job, **body: object) -> "_MonkeyPatchedWSGIResponse":
        return client.post(
            f"/api/job/jobs/{job.id}/cost_sets/quote/copy_from_estimate/",
            data=body,
            content_type="application/json",
        )

    def _seed_blank_quote(self, job: Job) -> None:
        """Recreate the $0 creation seed faithfully.

        The seeded time lines carry the real wage and charge-out rates with
        quantity 0 — nonzero unit prices, zero totals — which is exactly the
        shape that exposed a per-unit-price blank test as wrong (E2E run
        2026-08-31).
        """
        quote = job.cost_sets.get(kind="quote")
        _make_line(quote, kind="material", quantity="1.000", unit_cost="0.00", unit_rev="0.00")
        _make_line(quote, kind="time", quantity="0.000", unit_cost="48.00", unit_rev="105.00")

    def _real_estimate(self, job: Job) -> None:
        estimate = job.cost_sets.get(kind="estimate")
        _make_line(
            estimate,
            kind="material",
            quantity="1.000",
            unit_cost="100.00",
            unit_rev="150.00",
            xero_pay_item=None,
        )
        _make_line(
            estimate,
            kind="time",
            quantity="2.000",
            unit_cost="40.00",
            unit_rev="105.00",
            xero_pay_item=job.default_xero_pay_item,
        )

    def test_copy_is_office_only(self, job: Job, workshop_staff: Staff) -> None:
        response = _workshop_client(workshop_staff).post(
            f"/api/job/jobs/{job.id}/cost_sets/quote/copy_from_estimate/",
            data={},
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_unknown_job_is_404(self, client: Client) -> None:
        response = client.post(
            f"/api/job/jobs/{uuid4()}/cost_sets/quote/copy_from_estimate/",
            data={},
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_empty_estimate_is_400(self, client: Client, job: Job) -> None:
        response = self._copy(client, job)
        assert response.status_code == 400
        assert "estimate has no cost lines" in response.json()["detail"]

    def test_blank_quote_is_replaced_without_a_revision(self, client: Client, job: Job) -> None:
        self._real_estimate(job)
        self._seed_blank_quote(job)

        response = self._copy(client, job)

        assert response.status_code == 200
        body = response.json()
        assert body["copied_cost_lines_count"] == 2
        assert body["archived_quote_revision"] is None

        quote = job.cost_sets.get(kind="quote")
        lines = {line.kind: line for line in quote.cost_lines.all()}
        assert set(lines) == {"material", "time"}
        assert lines["material"].unit_cost == Decimal("100.00")
        assert lines["material"].unit_rev == Decimal("150.00")
        assert lines["time"].quantity == Decimal("2.000")
        # Subtype and pay item ride along so rate provenance survives the copy.
        estimate_time = job.cost_sets.get(kind="estimate").cost_lines.get(kind="time")
        assert lines["time"].labour_subtype_id == estimate_time.labour_subtype_id
        assert lines["time"].xero_pay_item_id == estimate_time.xero_pay_item_id
        # cost = 100 + 2*40 = 180; rev = 150 + 2*105 = 360; hours = 2
        assert quote.summary["cost"] == 180.0
        assert quote.summary["rev"] == 360.0
        assert quote.summary["hours"] == 2.0
        # A $0 seed is noise, not history: nothing archived.
        assert quote.summary.get("revisions", []) == []

    def test_real_quote_refuses_without_archive_flag(self, client: Client, job: Job) -> None:
        self._real_estimate(job)
        quote = job.cost_sets.get(kind="quote")
        _make_line(quote, kind="material", quantity="1.000", unit_cost="10.00", unit_rev="20.00")

        response = self._copy(client, job)

        assert response.status_code == 409
        quote.refresh_from_db()
        assert quote.cost_lines.count() == 1
        assert quote.cost_lines.get().unit_rev == Decimal("20.00")

    def test_zero_total_quote_with_real_lines_still_refuses(self, client: Client, job: Job) -> None:
        # Offsetting adjustments sum to $0 but are entered work; the blank
        # test is per-line, never total == 0.
        self._real_estimate(job)
        quote = job.cost_sets.get(kind="quote")
        _make_line(quote, kind="adjust", quantity="1.000", unit_cost="0.00", unit_rev="500.00")
        _make_line(quote, kind="adjust", quantity="1.000", unit_cost="0.00", unit_rev="-500.00")

        assert self._copy(client, job).status_code == 409

    def test_archive_flag_archives_then_copies(
        self, client: Client, job: Job, office_staff: Staff
    ) -> None:
        self._real_estimate(job)
        quote = job.cost_sets.get(kind="quote")
        _make_line(quote, kind="material", quantity="1.000", unit_cost="10.00", unit_rev="20.00")
        job.refresh_from_db()
        job.quote_acceptance_date = timezone.now()
        job.save(staff=office_staff)

        response = self._copy(client, job, archive_existing=True)

        assert response.status_code == 200
        body = response.json()
        assert body["copied_cost_lines_count"] == 2
        assert body["archived_quote_revision"] == 1

        quote.refresh_from_db()
        assert quote.cost_lines.count() == 2
        archived = quote.summary["revisions"]
        assert len(archived) == 1
        assert archived[0]["summary"] == {"cost": 10.0, "rev": 20.0, "hours": 0.0}
        # The live summary is the copied estimate, not the archive's zeroes.
        assert quote.summary["rev"] == 360.0

        job.refresh_from_db()
        assert job.quote_acceptance_date is None

    def test_second_press_creates_no_second_archive(self, client: Client, job: Job) -> None:
        # Double-pressing the button must not stack identical archives: once
        # the quote already matches the estimate there is nothing to archive
        # and nothing to copy, and no 409 either — the UI shows no dialog.
        self._real_estimate(job)
        quote = job.cost_sets.get(kind="quote")
        _make_line(quote, kind="material", quantity="1.000", unit_cost="10.00", unit_rev="20.00")

        first = self._copy(client, job, archive_existing=True)
        assert first.status_code == 200
        assert first.json()["archived_quote_revision"] == 1

        second = self._copy(client, job)

        assert second.status_code == 200
        body = second.json()
        assert body["copied_cost_lines_count"] == 0
        assert body["archived_quote_revision"] is None

        quote.refresh_from_db()
        assert len(quote.summary["revisions"]) == 1
        assert quote.cost_lines.count() == 2
        assert quote.summary["rev"] == 360.0


class TestQuoteRevisions:
    def test_list_is_empty_before_any_revision(self, client: Client, job: Job) -> None:
        response = client.get(f"/api/job/jobs/{job.id}/cost_sets/quote/revise/")

        assert response.status_code == 200
        body = response.json()
        assert body["job_id"] == str(job.id)
        assert body["total_revisions"] == 0
        assert body["revisions"] == []

    def test_revise_without_lines_is_400(self, client: Client, job: Job) -> None:
        response = client.post(
            f"/api/job/jobs/{job.id}/cost_sets/quote/revise/",
            data={"reason": "start again"},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "Nothing to revise" in response.json()["detail"]

    def test_revise_is_office_only(self, job: Job, workshop_staff: Staff) -> None:
        response = _workshop_client(workshop_staff).post(
            f"/api/job/jobs/{job.id}/cost_sets/quote/revise/",
            data={},
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_revise_archives_clears_and_resets_acceptance(
        self, client: Client, job: Job, office_staff: Staff
    ) -> None:
        quote = job.cost_sets.get(kind="quote")
        _make_line(quote, kind="material", quantity="1.000", unit_cost="100.00", unit_rev="150.00")
        _make_line(quote, kind="time", quantity="2.000", unit_cost="40.00", unit_rev="105.00")
        job.refresh_from_db()
        job.quote_acceptance_date = timezone.now()
        job.save(staff=office_staff)

        response = client.post(
            f"/api/job/jobs/{job.id}/cost_sets/quote/revise/",
            data={"reason": "customer changed scope"},
            content_type="application/json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["quote_revision"] == 1
        assert body["archived_cost_lines_count"] == 2

        quote.refresh_from_db()
        assert quote.cost_lines.count() == 0
        assert quote.summary["cost"] == 0.0
        assert quote.summary["rev"] == 0.0
        assert quote.summary["hours"] == 0.0
        archived = quote.summary["revisions"]
        assert len(archived) == 1
        assert archived[0]["reason"] == "customer changed scope"
        assert archived[0]["summary"] == {"cost": 180.0, "rev": 360.0, "hours": 2.0}
        assert len(archived[0]["cost_lines"]) == 2

        job.refresh_from_db()
        assert job.quote_acceptance_date is None

        # Listing reflects the archive; a second revision numbers itself 2.
        # The revision entries cross the wire typed (the revisions-history UI
        # consumes them), so the shape is contract, not incidental storage.
        listing = client.get(f"/api/job/jobs/{job.id}/cost_sets/quote/revise/").json()
        assert listing["total_revisions"] == 1
        listed = listing["revisions"][0]
        assert listed["quote_revision"] == 1
        assert listed["reason"] == "customer changed scope"
        assert listed["archived_at"]
        assert listed["summary"] == {"cost": 180.0, "rev": 360.0, "hours": 2.0}
        assert len(listed["cost_lines"]) == 2
        line_out = listed["cost_lines"][0]
        assert set(line_out) >= {"kind", "desc", "quantity", "unit_cost", "unit_rev", "total_rev"}
        _make_line(quote, kind="material")
        second = client.post(
            f"/api/job/jobs/{job.id}/cost_sets/quote/revise/",
            data={},
            content_type="application/json",
        )
        assert second.status_code == 200
        assert second.json()["quote_revision"] == 2

    def test_cost_set_reads_never_leak_archived_revisions(self, client: Client, job: Job) -> None:
        quote = job.cost_sets.get(kind="quote")
        _make_line(quote)
        assert (
            client.post(
                f"/api/job/jobs/{job.id}/cost_sets/quote/revise/",
                data={},
                content_type="application/json",
            ).status_code
            == 200
        )

        # summary.revisions is storage-only: cost-set and job-detail reads
        # serve exactly the four contracted summary keys.
        cost_set = client.get(f"/api/job/jobs/{job.id}/cost_sets/quote/").json()
        assert set(cost_set["summary"].keys()) == {"cost", "rev", "hours", "profitMargin"}
        detail = client.get(f"/api/job/jobs/{job.id}/").json()
        detail_summary = detail["data"]["job"]["latest_quote"]["summary"]
        assert set(detail_summary.keys()) == {"cost", "rev", "hours", "profitMargin"}
        # The archive itself stays reachable through the revise GET.
        listing = client.get(f"/api/job/jobs/{job.id}/cost_sets/quote/revise/").json()
        assert listing["total_revisions"] == 1

    def test_revise_without_quote_cost_set_is_404(
        self, client: Client, job: Job, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # v2's Job model guarantees a quote cost set (latest_quote is NOT NULL,
        # RESTRICT), so v1's missing-quote state is unreachable through data;
        # patch get_latest to exercise the contract's 404 branch.
        monkeypatch.setattr(Job, "get_latest", lambda *_args: None)

        assert client.get(f"/api/job/jobs/{job.id}/cost_sets/quote/revise/").status_code == 404
        response = client.post(
            f"/api/job/jobs/{job.id}/cost_sets/quote/revise/",
            data={},
            content_type="application/json",
        )
        assert response.status_code == 404
        assert "No quote found" in response.json()["detail"]


class TestCostsSummary:
    def test_margin_is_computed_over_revenue(self, client: Client, job: Job) -> None:
        estimate = job.cost_sets.get(kind="estimate")
        _make_line(estimate, quantity="1.000", unit_cost="100.00", unit_rev="150.00")

        response = client.get(f"/api/job/jobs/{job.id}/costs/summary/")

        assert response.status_code == 200
        body = response.json()
        # Margin standardised on revenue (user decision 2026-08-02):
        # Margin is ``(revenue - cost) / revenue * 100``.
        assert body["estimate"] == {
            "cost": 100.0,
            "rev": 150.0,
            "hours": 0.0,
            "profitMargin": pytest.approx((150 - 100) / 150 * 100),
        }
        # Empty cost sets still answer with zeroed summaries (created at job save)
        assert body["quote"]["cost"] == 0.0
        assert body["actual"]["profitMargin"] == 0.0

    def test_conditional_get_returns_304(self, client: Client, job: Job) -> None:
        first = client.get(f"/api/job/jobs/{job.id}/costs/summary/")
        etag = first.headers["ETag"]

        second = client.get(f"/api/job/jobs/{job.id}/costs/summary/", HTTP_IF_NONE_MATCH=etag)

        assert second.status_code == 304
        assert second.headers["ETag"] == etag

    def test_cost_line_write_invalidates_etag(self, client: Client, job: Job) -> None:
        etag = client.get(f"/api/job/jobs/{job.id}/costs/summary/").headers["ETag"]
        estimate = job.cost_sets.get(kind="estimate")
        _make_line(estimate)

        response = client.get(f"/api/job/jobs/{job.id}/costs/summary/", HTTP_IF_NONE_MATCH=etag)

        assert response.status_code == 200
        assert response.headers["ETag"] != etag

    def test_unknown_job_is_404(self, client: Client) -> None:
        assert client.get(f"/api/job/jobs/{uuid4()}/costs/summary/").status_code == 404
