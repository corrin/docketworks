"""Xero's query language is one implementation over the model (ADR 0060).

Business risk covered: the sync, the duplicate check and every listing
the application makes reach the fake through ``where``, ``order``, ``page``
and the id lists; a filter parsed loosely returns rows Xero would not, and
a parameter dropped returns everything. Each construct the grammar
implements is exercised against seeded rows, and an unknown one is refused.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.xero.fake import query
from apps.xero.fake.http import FakeRequest, FakeXeroUnhandledRouteError
from apps.xero.fake.models import FakeContact, FakeInvoice
from apps.xero.fake.tests.conftest import TENANT

pytestmark = pytest.mark.django_db


def _request(**params: str) -> FakeRequest:
    return FakeRequest(
        method="GET",
        host="api.xero.com",
        path="/api.xro/2.0/Invoices",
        query=params,
        headers={"xero-tenant-id": TENANT},
        json_body=None,
        raw_body=None,
    )


@pytest.fixture
def rows(tenant: str) -> dict[str, FakeInvoice]:
    """Two contacts, three invoices: enough to tell every construct apart."""
    acme = FakeContact.from_wire(
        tenant, {"ContactID": str(uuid.uuid4()), "Name": "Acme Ltd", "ContactStatus": "ACTIVE"}
    )
    zed = FakeContact.from_wire(
        tenant,
        {"ContactID": str(uuid.uuid4()), "Name": 'Zed "Quoted" Co', "ContactStatus": "ACTIVE"},
    )
    invoices: dict[str, FakeInvoice] = {}
    for key, contact, kind, status, day, total in (
        ("old", acme, "ACCREC", "PAID", "2026-01-05", "100"),
        ("new", acme, "ACCREC", "AUTHORISED", "2026-09-01", "250.5"),
        ("bill", zed, "ACCPAY", "DRAFT", "2026-09-02", "40"),
    ):
        invoices[key] = FakeInvoice.from_wire(
            tenant,
            {
                "InvoiceID": str(uuid.uuid4()),
                "InvoiceNumber": f"INV-{key}",
                "Type": kind,
                "Status": status,
                "Date": day,
                "Total": Decimal(total),
                "Contact": {"ContactID": str(contact.id)},
            },
            updated_date_utc=datetime.fromisoformat(f"{day}T00:00:00+00:00"),
        )
    return invoices


def _numbers(request: FakeRequest) -> list[str | None]:
    return [row.number for row in query.listing(FakeInvoice, request)]


class TestWhere:
    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ('Type=="ACCREC"', ["INV-old", "INV-new"]),
            ('Type!="ACCREC"', ["INV-bill"]),
            ('Status=="PAID" OR Status=="DRAFT"', ["INV-old", "INV-bill"]),
            ('Type=="ACCREC" AND Status=="AUTHORISED"', ["INV-new"]),
            ('(Type=="ACCREC" && Status=="PAID") || Status=="DRAFT"', ["INV-old", "INV-bill"]),
            ("Date>=DateTime(2026, 9, 1)", ["INV-new", "INV-bill"]),
            ("Date<DateTime(2026,9,2)", ["INV-old", "INV-new"]),
            ("Total>100", ["INV-new"]),
            ("Total<=100", ["INV-old", "INV-bill"]),
            ('InvoiceNumber.Contains("ne")', ["INV-new"]),
            ('InvoiceNumber.StartsWith("INV-b")', ["INV-bill"]),
            ('InvoiceNumber.EndsWith("old")==true', ["INV-old"]),
            ('InvoiceNumber.Contains("old")==false', ["INV-new", "INV-bill"]),
            ('InvoiceNumber.ToLower()=="inv-new"', ["INV-new"]),
            ('Contact.Name=="Acme Ltd"', ["INV-old", "INV-new"]),
            ('Contact.Name=="Zed \\"Quoted\\" Co"', ["INV-bill"]),
        ],
    )
    def test_each_construct_selects_what_xero_would(
        self, rows: dict[str, FakeInvoice], expression: str, expected: list[str]
    ) -> None:
        del rows
        assert _numbers(_request(where=expression)) == expected

    def test_a_guid_selects_by_id_and_through_the_contact(
        self, rows: dict[str, FakeInvoice]
    ) -> None:
        by_id = _numbers(_request(where=f'InvoiceID==Guid("{rows["new"].id}")'))
        assert by_id == ["INV-new"]
        contact_id = rows["bill"].contact_id
        by_contact = _numbers(_request(where=f'Contact.ContactID==Guid("{contact_id}")'))
        assert by_contact == ["INV-bill"]

    @pytest.mark.parametrize(
        "expression",
        [
            'Colour=="red"',
            'Type="ACCREC"',
            'Type=="ACCREC" XOR Status=="PAID"',
            "Date>=DateTime(2026, 9, 1) AND",
            'Type.Squash("x")',
        ],
    )
    def test_what_the_grammar_does_not_implement_is_refused_not_dropped(
        self, rows: dict[str, FakeInvoice], expression: str
    ) -> None:
        del rows
        with pytest.raises(FakeXeroUnhandledRouteError):
            _numbers(_request(where=expression))


class TestOrderIdsAndPaging:
    def test_order_by_a_field_either_way_and_the_default_is_updated_ascending(
        self, rows: dict[str, FakeInvoice]
    ) -> None:
        del rows
        assert _numbers(_request()) == ["INV-old", "INV-new", "INV-bill"]
        assert _numbers(_request(order="Total DESC")) == ["INV-new", "INV-old", "INV-bill"]
        assert _numbers(_request(order="InvoiceNumber")) == ["INV-bill", "INV-new", "INV-old"]
        with pytest.raises(FakeXeroUnhandledRouteError):
            _numbers(_request(order="Colour ASC"))

    def test_the_id_lists_narrow_and_an_unknown_parameter_is_refused(
        self, rows: dict[str, FakeInvoice]
    ) -> None:
        ids = f"{rows['old'].id},{rows['bill'].id}"
        assert _numbers(_request(IDs=ids)) == ["INV-old", "INV-bill"]
        assert _numbers(_request(Statuses="PAID,DRAFT")) == ["INV-old", "INV-bill"]
        assert _numbers(_request(InvoiceNumbers="INV-new")) == ["INV-new"]
        assert _numbers(_request(ContactIDs=str(rows["bill"].contact_id))) == ["INV-bill"]
        with pytest.raises(FakeXeroUnhandledRouteError, match="summaryOnly"):
            _numbers(_request(summaryOnly="true"))

    def test_modified_since_reads_both_header_forms(self, rows: dict[str, FakeInvoice]) -> None:
        del rows
        iso = _request()
        iso.headers["If-Modified-Since"] = "2026-09-01T00:00:00+00:00"
        assert _numbers(iso) == ["INV-new", "INV-bill"]
        rfc = _request()
        rfc.headers["If-Modified-Since"] = "Wed, 02 Sep 2026 00:00:00 GMT"
        assert _numbers(rfc) == ["INV-bill"]

    def test_pages_carry_xero_s_block_and_the_whole_listing_answers_without_a_page(
        self, rows: dict[str, FakeInvoice]
    ) -> None:
        del rows
        everything, block = query.page(_request(), query.listing(FakeInvoice, _request()))
        assert len(everything) == 3 and block is None
        first, block = query.page(
            _request(page="1", pageSize="2"), query.listing(FakeInvoice, _request())
        )
        assert [row.number for row in first] == ["INV-old", "INV-new"]
        assert block == {"page": 1, "pageSize": 2, "pageCount": 2, "itemCount": 3}
        second, _block = query.page(
            _request(page="2", pageSize="2"), query.listing(FakeInvoice, _request())
        )
        assert [row.number for row in second] == ["INV-bill"]

    def test_a_date_time_on_a_timestamp_field_keeps_its_time(
        self, rows: dict[str, FakeInvoice]
    ) -> None:
        del rows
        at_noon = datetime(2026, 9, 1, 12, tzinfo=UTC)
        FakeInvoice.objects.filter(number="INV-new").update(updated_date_utc=at_noon)
        assert _numbers(_request(where="UpdatedDateUTC>=DateTime(2026,9,1,11,0,0)")) == [
            "INV-new",
            "INV-bill",
        ]
