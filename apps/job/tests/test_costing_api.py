"""API tests for the costing endpoints (django test Client, house pattern).

Guards the v1 wire contract for cost-set retrieval (rev handling, grid line
order, profitMargin), cost-line CRUD (auth split, validation, model-driven
summary reconciliation, stock adjustment), quote revisions (archive/clear/
acceptance reset, revision numbering) and the costs summary endpoint
(margin-on-cost formula, conditional GET).
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

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
        # v1 grid order: material -> adjust -> time
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
        # v1 answered 400 from an explicit guard; v2 rejects at schema level.
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

    def test_timesheet_meta_is_rejected_until_timesheet_slice(
        self, client: Client, job: Job
    ) -> None:
        workshop = LabourSubtype.default_workshop()
        response = client.post(
            f"/api/job/jobs/{job.id}/cost_sets/estimate/cost_lines/",
            data=self._payload(
                kind="time",
                labour_subtype=str(workshop.id),
                meta={"created_from_timesheet": True},
            ),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "timesheet" in response.json()["detail"]


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

    def test_workshop_staff_cannot_patch_non_actual(self, job: Job, workshop_staff: Staff) -> None:
        estimate = job.cost_sets.get(kind="estimate")
        line = _make_line(estimate)
        response = _workshop_client(workshop_staff).patch(
            f"/api/job/cost_lines/{line.id}/",
            data={"quantity": "2.000"},
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_patch_subtype_of_timesheet_line_is_rejected(self, client: Client, job: Job) -> None:
        estimate = job.cost_sets.get(kind="estimate")
        line = _make_line(estimate, kind="time", meta={"created_from_timesheet": True})
        other = LabourSubtype.default_non_workshop()

        response = client.patch(
            f"/api/job/cost_lines/{line.id}/",
            data={"labour_subtype": str(other.id)},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "timesheet" in response.json()["detail"]

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

    def test_workshop_staff_cannot_delete_non_actual(self, job: Job, workshop_staff: Staff) -> None:
        estimate = job.cost_sets.get(kind="estimate")
        line = _make_line(estimate)
        response = _workshop_client(workshop_staff).delete(f"/api/job/cost_lines/{line.id}/delete/")
        assert response.status_code == 403

    def test_unknown_line_is_404(self, client: Client) -> None:
        assert client.delete(f"/api/job/cost_lines/{uuid4()}/delete/").status_code == 404


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
        listing = client.get(f"/api/job/jobs/{job.id}/cost_sets/quote/revise/").json()
        assert listing["total_revisions"] == 1
        _make_line(quote, kind="material")
        second = client.post(
            f"/api/job/jobs/{job.id}/cost_sets/quote/revise/",
            data={},
            content_type="application/json",
        )
        assert second.status_code == 200
        assert second.json()["quote_revision"] == 2


class TestCostsSummary:
    def test_margin_is_computed_over_cost(self, client: Client, job: Job) -> None:
        estimate = job.cost_sets.get(kind="estimate")
        _make_line(estimate, quantity="1.000", unit_cost="100.00", unit_rev="150.00")

        response = client.get(f"/api/job/jobs/{job.id}/costs/summary/")

        assert response.status_code == 200
        body = response.json()
        # v1 JobCostSummaryRestView: profitMargin = (rev - cost) / cost * 100
        assert body["estimate"] == {
            "cost": 100.0,
            "rev": 150.0,
            "hours": 0.0,
            "profitMargin": 50.0,
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
