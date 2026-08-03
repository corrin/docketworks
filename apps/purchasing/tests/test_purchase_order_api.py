"""API tests for the purchase-order surface (django test Client, house pattern).

Guards the v1 wire contract for PO list/detail/create/update, the ADR 0003
optimistic-concurrency semantics on the PATCH path (428 missing / 412 stale /
200 current, plus conditional GET), PO numbering, events, email and the PDF
stream.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company, SupplierPickupAddress
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.purchasing.tests.conftest import make_po_line, make_purchase_order

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.purchasing.tests.urls"),
]

PO_LIST_URL = "/api/purchasing/purchase-orders/"


def _detail_url(po: PurchaseOrder) -> str:
    return f"{PO_LIST_URL}{po.id}/"


def _current_etag(client: Client, po: PurchaseOrder) -> str:
    response = client.get(_detail_url(po))
    assert response.status_code == 200
    return response.headers["ETag"]


class TestPurchaseOrderNumbering:
    def test_save_generates_sequential_numbers_from_the_configured_prefix(
        self, company_defaults: CompanyDefaults
    ) -> None:
        company_defaults.po_prefix = "PO-"
        company_defaults.starting_po_number = 100
        company_defaults.save()

        first = make_purchase_order()
        second = make_purchase_order()

        assert first.po_number == "PO-0100"
        assert second.po_number == "PO-0101"

    def test_last_number_endpoint_reports_the_highest_issued(
        self, client: Client, company_defaults: CompanyDefaults
    ) -> None:
        company_defaults.po_prefix = "PO-"
        company_defaults.starting_po_number = 1
        company_defaults.save()
        make_purchase_order()
        latest = make_purchase_order()

        response = client.get(f"{PO_LIST_URL}last-number/")

        assert response.status_code == 200
        assert response.json()["last_po_number"] == latest.po_number

    @pytest.mark.usefixtures("company_defaults")
    def test_last_number_is_null_when_nothing_is_issued(self, client: Client) -> None:
        assert client.get(f"{PO_LIST_URL}last-number/").json()["last_po_number"] is None


class TestPurchaseOrderList:
    def test_lists_newest_first_with_distinct_jobs(
        self, client: Client, supplier: Company, job: Job, office_staff: Staff
    ) -> None:
        po = make_purchase_order(supplier=supplier, created_by=office_staff)
        make_po_line(po, job=job, description="First")
        make_po_line(po, job=job, description="Second")

        rows = client.get(PO_LIST_URL).json()

        assert len(rows) == 1
        assert rows[0]["po_number"] == po.po_number
        assert rows[0]["supplier"] == supplier.name
        assert rows[0]["created_by_name"] == office_staff.get_display_full_name()
        # Two lines on one job collapse to a single job entry.
        assert job.company is not None
        assert rows[0]["jobs"] == [
            {"job_number": str(job.job_number), "name": job.name, "company": job.company.name}
        ]

    def test_status_filter_accepts_a_comma_separated_list(self, client: Client) -> None:
        draft = make_purchase_order(status="draft")
        submitted = make_purchase_order(status="submitted")
        make_purchase_order(status="deleted")

        rows = client.get(f"{PO_LIST_URL}?status=draft,submitted").json()

        assert {row["po_number"] for row in rows} == {draft.po_number, submitted.po_number}

    def test_unauthenticated_requests_are_rejected(self) -> None:
        assert Client().get(PO_LIST_URL).status_code == 401


class TestPurchaseOrderDetail:
    def test_returns_lines_with_supplier_and_usage_counts(
        self, client: Client, supplier: Company, job: Job
    ) -> None:
        supplier.xero_contact_id = "11111111-1111-1111-1111-111111111111"
        supplier.save()
        po = make_purchase_order(supplier=supplier)
        used = make_po_line(po, item_code="ABC-123", job=job)
        unused = make_po_line(po, item_code="XYZ-999")
        blank = make_po_line(po, item_code=None)
        for _ in range(2):
            CostLine.objects.create(
                cost_set=job.latest_actual,
                kind="material",
                desc="Used ABC-123",
                quantity=Decimal("1.000"),
                unit_cost=Decimal("10.00"),
                unit_rev=Decimal("12.00"),
                accounting_date=timezone.localdate(),
                meta={"item_code": "ABC-123"},
            )

        body = client.get(_detail_url(po)).json()

        assert body["supplier"] == supplier.name
        assert body["supplier_has_xero_id"] is True
        lines = {line["id"]: line for line in body["lines"]}
        assert lines[str(used.id)]["times_used"] == 2
        assert lines[str(unused.id)]["times_used"] == 0
        assert lines[str(blank.id)]["times_used"] == 0
        assert lines[str(used.id)]["job_id"] == str(job.id)
        assert lines[str(used.id)]["job_number"] == job.job_number

    def test_supplierless_po_keeps_the_v1_defaults(self, client: Client) -> None:
        po = make_purchase_order()

        body = client.get(_detail_url(po)).json()

        assert body["supplier"] == ""
        assert body["supplier_id"] is None
        assert body["supplier_has_xero_id"] is False
        assert body["created_by_name"] == ""

    def test_deleted_purchase_orders_stay_viewable(self, client: Client) -> None:
        po = make_purchase_order(status="deleted")
        assert client.get(_detail_url(po)).status_code == 200

    def test_unknown_purchase_order_is_404(self, client: Client) -> None:
        assert client.get(f"{PO_LIST_URL}{uuid4()}/").status_code == 404


@pytest.mark.usefixtures("company_defaults")
class TestPurchaseOrderCreate:
    def test_creates_the_po_and_its_lines(
        self, client: Client, supplier: Company, job: Job
    ) -> None:
        response = client.post(
            PO_LIST_URL,
            data={
                "supplier_id": str(supplier.id),
                "reference": "Job 42 steel",
                "lines": [
                    {
                        "job_id": str(job.id),
                        "description": "50x50 SHS",
                        "quantity": "6",
                        "unit_cost": "31.50",
                    }
                ],
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        po = PurchaseOrder.objects.get(id=response.json()["id"])
        assert po.reference == "Job 42 steel"
        assert po.supplier_id == supplier.id
        line = po.po_lines.get()
        assert line.description == "50x50 SHS"
        assert line.unit_cost == Decimal("31.50")
        # The create response carries the ETag the client needs to mutate.
        assert response.headers["ETag"].startswith('"po:')

    def test_blank_reference_is_stored_as_unset(self, client: Client) -> None:
        # v1 wrote "" here and tripped its own reference_not_blank constraint.
        # That constraint is NOT visible in v1's models.py — it was added by a
        # raw-SQL migration and lives only in the live schema (verified against
        # v1 production: 0 blank, 167 NULL of 913 purchase orders). Do not
        # "correct" this test by reading v1's model file.
        response = client.post(PO_LIST_URL, data={"reference": ""}, content_type="application/json")

        assert response.status_code == 201
        assert PurchaseOrder.objects.get(id=response.json()["id"]).reference is None

    def test_price_tbc_clears_the_unit_cost(self, client: Client) -> None:
        response = client.post(
            PO_LIST_URL,
            data={
                "lines": [
                    {
                        "description": "TBC item",
                        "quantity": "1",
                        "unit_cost": "9.99",
                        "price_tbc": True,
                    }
                ]
            },
            content_type="application/json",
        )

        po = PurchaseOrder.objects.get(id=response.json()["id"])
        assert po.po_lines.get().unit_cost is None

    def test_dimensions_are_written_on_create(self, client: Client) -> None:
        # v1 declared dimensions on the create serializer and wrote it on the
        # update path, but create_purchase_order() omitted the field, so a
        # dimension entered on a brand-new PO was lost until the line was
        # edited. v2 uses one line-write path for both. (Ledgered.)
        response = client.post(
            PO_LIST_URL,
            data={
                "lines": [{"description": "Plate", "quantity": "1", "dimensions": "2400x1200x6"}]
            },
            content_type="application/json",
        )

        po = PurchaseOrder.objects.get(id=response.json()["id"])
        assert po.po_lines.get().dimensions == "2400x1200x6"

    def test_primary_pickup_address_is_selected_automatically(
        self, client: Client, supplier: Company
    ) -> None:
        address = SupplierPickupAddress.objects.create(
            company=supplier, name="Yard", street="1 Steel Rd", city="Auckland", is_primary=True
        )

        response = client.post(
            PO_LIST_URL, data={"supplier_id": str(supplier.id)}, content_type="application/json"
        )

        assert PurchaseOrder.objects.get(id=response.json()["id"]).pickup_address_id == address.id

    def test_unknown_supplier_is_400(self, client: Client) -> None:
        response = client.post(
            PO_LIST_URL, data={"supplier_id": str(uuid4())}, content_type="application/json"
        )
        assert response.status_code == 400
        assert "not found" in response.json()["detail"]


class TestPurchaseOrderConcurrency:
    """ADR 0003 on the PO PATCH path (v1 test_purchase_order_etags.py)."""

    def test_get_returns_a_strong_po_etag(self, client: Client) -> None:
        po = make_purchase_order()
        etag = _current_etag(client, po)
        assert etag.startswith('"po:')
        assert str(po.id) in etag

    def test_conditional_get_answers_304(self, client: Client) -> None:
        po = make_purchase_order()
        etag = _current_etag(client, po)

        response = client.get(_detail_url(po), headers={"If-None-Match": etag})

        assert response.status_code == 304

    def test_conditional_get_returns_the_body_when_the_etag_moved(self, client: Client) -> None:
        po = make_purchase_order()
        stale = _current_etag(client, po)
        PurchaseOrder.objects.filter(pk=po.pk).update(
            reference="Concurrent edit", updated_at=timezone.now()
        )

        response = client.get(_detail_url(po), headers={"If-None-Match": stale})

        assert response.status_code == 200
        assert response.json()["reference"] == "Concurrent edit"

    def test_patch_without_if_match_is_428(self, client: Client) -> None:
        po = make_purchase_order()

        response = client.patch(_detail_url(po), data={}, content_type="application/json")

        assert response.status_code == 428
        assert "If-Match" in response.json()["detail"]

    def test_patch_with_a_stale_etag_is_412_and_writes_nothing(self, client: Client) -> None:
        po = make_purchase_order(reference="Original")
        stale = _current_etag(client, po)
        PurchaseOrder.objects.filter(pk=po.pk).update(
            reference="Concurrent edit", updated_at=timezone.now()
        )

        response = client.patch(
            _detail_url(po),
            data={"reference": "My edit"},
            content_type="application/json",
            headers={"If-Match": stale},
        )

        assert response.status_code == 412
        assert "Precondition failed" in response.json()["detail"]
        po.refresh_from_db()
        assert po.reference == "Concurrent edit"

    def test_patch_with_the_current_etag_succeeds_and_returns_a_new_one(
        self, client: Client
    ) -> None:
        po = make_purchase_order(reference="Original")
        etag = _current_etag(client, po)

        response = client.patch(
            _detail_url(po),
            data={"reference": "My edit"},
            content_type="application/json",
            headers={"If-Match": etag},
        )

        assert response.status_code == 200
        po.refresh_from_db()
        assert po.reference == "My edit"
        assert response.headers["ETag"] != etag

    def test_replaying_a_consumed_etag_is_412(self, client: Client) -> None:
        """Double submission cannot apply the same mutation twice (ADR 0003)."""
        po = make_purchase_order(reference="Original")
        etag = _current_etag(client, po)
        headers = {"If-Match": etag}
        body = {"reference": "First edit"}

        first = client.patch(
            _detail_url(po), data=body, content_type="application/json", headers=headers
        )
        second = client.patch(
            _detail_url(po), data=body, content_type="application/json", headers=headers
        )

        assert first.status_code == 200
        assert second.status_code == 412

    def test_etag_is_mirrored_into_x_resource_version(self, client: Client) -> None:
        po = make_purchase_order()
        response = client.get(_detail_url(po))
        assert response.headers["X-Resource-Version"] == response.headers["ETag"]


class TestPurchaseOrderUpdate:
    def test_updates_lines_creates_new_ones_and_deletes_requested_ones(
        self, client: Client
    ) -> None:
        po = make_purchase_order()
        keep = make_po_line(po, description="Keep", quantity="1.00")
        drop = make_po_line(po, description="Drop", quantity="1.00")
        etag = _current_etag(client, po)

        response = client.patch(
            _detail_url(po),
            data={
                "lines_to_delete": [str(drop.id)],
                "lines": [
                    {"id": str(keep.id), "description": "Renamed", "quantity": "4"},
                    {"description": "Brand new", "quantity": "2", "unit_cost": "5.00"},
                ],
            },
            content_type="application/json",
            headers={"If-Match": etag},
        )

        assert response.status_code == 200
        keep.refresh_from_db()
        assert keep.description == "Renamed"
        assert keep.quantity == Decimal("4.00")
        assert not PurchaseOrderLine.objects.filter(id=drop.id).exists()
        assert po.po_lines.filter(description="Brand new").exists()

    def test_untick_price_tbc_and_enter_a_price_with_a_blank_item_code(
        self, client: Client
    ) -> None:
        """KAN-329: a live v1 production bug this port must never inherit.

        Reported from production 2026-08-03 (unfixed in v1 at that date):
        unticking "Price TBC" and entering the real
        price fails, because the form posts the whole line back with an empty
        item_code. v1's FIELD_UPDATERS coerce "" -> NULL for metal_type, alloy,
        specifics, location and dimensions but NOT for item_code, so the blank
        string reaches the item_code_not_blank CHECK constraint (present in
        v1's live schema and v2's) and the save 500s. v2 coerces every optional
        text field alike, so the edit succeeds. Unfixed in v1 as of this date.
        """
        po = make_purchase_order()
        line = make_po_line(po, quantity="10.00", unit_cost=None, price_tbc=True)
        etag = _current_etag(client, po)

        response = client.patch(
            _detail_url(po),
            data={
                "lines": [
                    {
                        "id": str(line.id),
                        "price_tbc": False,
                        "unit_cost": "42.50",
                        "item_code": "",
                    }
                ]
            },
            content_type="application/json",
            headers={"If-Match": etag},
        )

        assert response.status_code == 200
        line.refresh_from_db()
        assert line.price_tbc is False
        assert line.unit_cost == Decimal("42.50")
        assert line.item_code is None  # blank stored as unset, not ""

    def test_price_tbc_only_patch_preserves_the_stored_unit_cost(self, client: Client) -> None:
        """The "price TBC" checkbox must not wipe the cost beside it.

        v1 drove per-field updaters, each applied only when its own key was
        present, so toggling the checkbox left unit_cost alone. A coupled
        implementation nulls the cost and then hard-fails every receipt and
        allocation path for that line.
        """
        po = make_purchase_order()
        line = make_po_line(po, quantity="10.00", unit_cost="25.00")
        etag = _current_etag(client, po)

        response = client.patch(
            _detail_url(po),
            data={"lines": [{"id": str(line.id), "price_tbc": False}]},
            content_type="application/json",
            headers={"If-Match": etag},
        )

        assert response.status_code == 200
        line.refresh_from_db()
        assert line.unit_cost == Decimal("25.00")
        assert line.price_tbc is False

    def test_unit_cost_only_patch_leaves_the_price_tbc_flag_alone(self, client: Client) -> None:
        po = make_purchase_order()
        line = make_po_line(po, quantity="10.00", unit_cost="25.00")
        etag = _current_etag(client, po)

        client.patch(
            _detail_url(po),
            data={"lines": [{"id": str(line.id), "unit_cost": "31.50"}]},
            content_type="application/json",
            headers={"If-Match": etag},
        )

        line.refresh_from_db()
        assert line.unit_cost == Decimal("31.50")
        assert line.price_tbc is False

    def test_a_cost_sent_for_a_still_tbc_line_is_not_stored(self, client: Client) -> None:
        """price_tbc means "no unit cost" (the field's own help_text).

        The flag is read from the line's effective value, so a cost arriving
        while the line is still marked TBC is refused. v1's update path had no
        such rule and would store a cost on a TBC line — a row contradicting
        its own documentation — while v1's create path enforced it; v2 keeps
        the invariant on both (ADR 0039, ledgered).
        """
        po = make_purchase_order()
        line = make_po_line(po, quantity="10.00", unit_cost=None, price_tbc=True)
        etag = _current_etag(client, po)

        client.patch(
            _detail_url(po),
            data={"lines": [{"id": str(line.id), "unit_cost": "31.50"}]},
            content_type="application/json",
            headers={"If-Match": etag},
        )

        line.refresh_from_db()
        assert line.unit_cost is None
        assert line.price_tbc is True

    def test_clearing_the_flag_and_setting_a_cost_together_works(self, client: Client) -> None:
        po = make_purchase_order()
        line = make_po_line(po, quantity="10.00", unit_cost=None, price_tbc=True)
        etag = _current_etag(client, po)

        client.patch(
            _detail_url(po),
            data={"lines": [{"id": str(line.id), "price_tbc": False, "unit_cost": "31.50"}]},
            content_type="application/json",
            headers={"If-Match": etag},
        )

        line.refresh_from_db()
        assert line.price_tbc is False
        assert line.unit_cost == Decimal("31.50")

    def test_omitted_line_fields_are_left_alone(self, client: Client) -> None:
        # v1's serializer defaults reset quantity to 0 when it was not sent.
        po = make_purchase_order()
        line = make_po_line(po, description="Keep quantity", quantity="7.00")
        etag = _current_etag(client, po)

        client.patch(
            _detail_url(po),
            data={"lines": [{"id": str(line.id), "description": "Renamed"}]},
            content_type="application/json",
            headers={"If-Match": etag},
        )

        line.refresh_from_db()
        assert line.quantity == Decimal("7.00")

    def test_a_line_id_from_another_po_is_400(self, client: Client) -> None:
        po = make_purchase_order()
        other = make_purchase_order()
        foreign_line = make_po_line(other)
        etag = _current_etag(client, po)

        response = client.patch(
            _detail_url(po),
            data={"lines": [{"id": str(foreign_line.id), "description": "Hijack"}]},
            content_type="application/json",
            headers={"If-Match": etag},
        )

        assert response.status_code == 400
        assert "not found on PO" in response.json()["detail"]

    def test_an_unknown_status_is_rejected(self, client: Client) -> None:
        # v1 wrote any string into the column; choices are not DB-enforced.
        po = make_purchase_order()
        etag = _current_etag(client, po)

        response = client.patch(
            _detail_url(po),
            data={"status": "totally_bogus"},
            content_type="application/json",
            headers={"If-Match": etag},
        )

        assert response.status_code == 400
        assert "Invalid status" in response.json()["detail"]
        po.refresh_from_db()
        assert po.status == "draft"

    def test_pickup_address_can_be_cleared_with_an_explicit_null(
        self, client: Client, supplier: Company
    ) -> None:
        address = SupplierPickupAddress.objects.create(
            company=supplier, name="Yard", street="1 Steel Rd", city="Auckland"
        )
        po = make_purchase_order(supplier=supplier)
        po.pickup_address = address
        po.save()
        etag = _current_etag(client, po)

        client.patch(
            _detail_url(po),
            data={"pickup_address_id": None},
            content_type="application/json",
            headers={"If-Match": etag},
        )

        po.refresh_from_db()
        assert po.pickup_address_id is None


class TestPurchaseOrderEvents:
    def test_create_then_list_returns_the_note_with_its_author(
        self, client: Client, office_staff: Staff
    ) -> None:
        po = make_purchase_order()

        created = client.post(
            f"{_detail_url(po)}events/",
            data={"description": "Chased the supplier"},
            content_type="application/json",
        )
        listed = client.get(f"{_detail_url(po)}events/")

        assert created.status_code == 201
        assert created.json()["event"]["description"] == "Chased the supplier"
        events = listed.json()["events"]
        assert len(events) == 1
        assert events[0]["staff"] == office_staff.get_display_full_name()

    def test_events_come_back_newest_first(self, client: Client) -> None:
        po = make_purchase_order()
        for description in ("First", "Second"):
            client.post(
                f"{_detail_url(po)}events/",
                data={"description": description},
                content_type="application/json",
            )

        events = client.get(f"{_detail_url(po)}events/").json()["events"]

        assert [event["description"] for event in events] == ["Second", "First"]

    def test_events_for_an_unknown_po_are_404(self, client: Client) -> None:
        assert client.get(f"{PO_LIST_URL}{uuid4()}/events/").status_code == 404


class TestPurchaseOrderEmail:
    def test_composes_a_mailto_url_for_the_supplier(
        self, client: Client, supplier: Company, company_defaults: CompanyDefaults
    ) -> None:
        po = make_purchase_order(supplier=supplier)

        body = client.post(
            f"{_detail_url(po)}email/", data={}, content_type="application/json"
        ).json()

        assert body["success"] is True
        assert body["email_subject"] == f"Purchase Order {po.po_number}"
        assert body["mailto_url"].startswith(f"mailto:{supplier.email}?subject=")
        assert company_defaults.company_name in body["email_body"]

    @pytest.mark.usefixtures("company_defaults")
    def test_a_custom_message_is_prepended_to_the_body(
        self, client: Client, supplier: Company
    ) -> None:
        po = make_purchase_order(supplier=supplier)

        body = client.post(
            f"{_detail_url(po)}email/",
            data={"message": "Urgent please"},
            content_type="application/json",
        ).json()

        assert body["email_body"].startswith("Urgent please\n\n")

    @pytest.mark.usefixtures("company_defaults")
    def test_a_po_without_a_supplier_is_400(self, client: Client) -> None:
        po = make_purchase_order()

        response = client.post(f"{_detail_url(po)}email/", data={}, content_type="application/json")

        assert response.status_code == 400
        assert "must have a supplier" in response.json()["detail"]

    @pytest.mark.usefixtures("company_defaults")
    @pytest.mark.usefixtures("company_defaults")
    def test_an_invalid_recipient_email_is_rejected(
        self, client: Client, supplier: Company
    ) -> None:
        # v1 declared recipient_email as a DRF EmailField, so a typo was
        # rejected there even though the view only used it to retarget mailto.
        po = make_purchase_order(supplier=supplier)

        response = client.post(
            f"{_detail_url(po)}email/",
            data={"recipient_email": "not-an-email"},
            content_type="application/json",
        )

        assert response.status_code == 422

    @pytest.mark.usefixtures("company_defaults")
    def test_a_valid_recipient_email_overrides_the_supplier_address(
        self, client: Client, supplier: Company
    ) -> None:
        po = make_purchase_order(supplier=supplier)

        body = client.post(
            f"{_detail_url(po)}email/",
            data={"recipient_email": "yard@example.test"},
            content_type="application/json",
        ).json()

        assert body["mailto_url"].startswith("mailto:yard@example.test?subject=")

    def test_a_supplier_without_an_email_is_400(self, client: Client) -> None:
        silent = Company.objects.create(name="No Email Ltd", xero_last_modified=timezone.now())
        po = make_purchase_order(supplier=silent)

        response = client.post(f"{_detail_url(po)}email/", data={}, content_type="application/json")

        assert response.status_code == 400
        assert "no email address" in response.json()["detail"]
