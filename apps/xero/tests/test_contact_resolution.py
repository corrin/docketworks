"""Embedded-contact-first company resolution in the document transforms.

Business case: every invoice/quote/PO page already carries its contact, and a
follow-up ``get_contacts`` per document is what drained the day quota in
production. Resolution must use the embedded payload and only fall back to a
GET when Xero sent a bare contact reference.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.utils import timezone as django_timezone

from apps.accounting.models import Quote
from apps.company.models import Company
from apps.purchasing.models import PurchaseOrder
from apps.xero.transforms import (
    _extract_required_fields_xero,
    resolve_company_from_xero_contact,
    transform_purchase_order,
    transform_quote,
)

from .xero_fixtures import make_xero_contact


@pytest.fixture
def company() -> Company:
    return Company.objects.create(
        name="Existing Company",
        xero_contact_id="contact-123",
        xero_last_modified=django_timezone.now(),
    )


def _rich_contact(
    contact_id: str = "contact-123", name: str = "Existing Company"
) -> SimpleNamespace:
    """An embedded contact carrying more than its id — no GET warranted."""
    return SimpleNamespace(contact_id=contact_id, name=name)


@pytest.mark.django_db
class TestResolveCompanyFromXeroContact:
    def test_rich_embedded_contact_resolves_without_follow_up_get(self, company: Company) -> None:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "apps.xero.transforms.get_or_fetch_company",
                _fail_if_called,
            )
            resolved = resolve_company_from_xero_contact(_rich_contact(), "INV-001")

        assert resolved.id == company.id

    def test_rich_embedded_contact_syncs_unknown_company_directly(self) -> None:
        # The embedded payload is enough to create the company — burning a GET
        # here is exactly the quota leak this seam exists to close.
        contact = make_xero_contact("contact-embed-9", "Embedded New Co")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("apps.xero.transforms.get_or_fetch_company", _fail_if_called)
            resolved = resolve_company_from_xero_contact(contact, "INV-002")

        assert resolved.xero_contact_id == "contact-embed-9"
        assert resolved.name == "Embedded New Co"

    def test_bare_contact_id_falls_back_to_get(self, company: Company) -> None:
        calls: list[tuple[str, str | None]] = []

        def _fake_get(contact_id: str, reference: str | None = None) -> Company:
            calls.append((contact_id, reference))
            return company

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("apps.xero.transforms.get_or_fetch_company", _fake_get)
            resolved = resolve_company_from_xero_contact(
                SimpleNamespace(contact_id="contact-123"), "INV-001"
            )

        assert resolved.id == company.id
        assert calls == [("contact-123", "INV-001")]

    def test_missing_contact_raises(self) -> None:
        with pytest.raises(ValueError, match="INV-001"):
            resolve_company_from_xero_contact(None, "INV-001")

    def test_contact_without_id_raises(self) -> None:
        with pytest.raises(ValueError, match="INV-001"):
            resolve_company_from_xero_contact(SimpleNamespace(name="No Id Co"), "INV-001")


@pytest.mark.django_db
class TestTransformsUseEmbeddedContact:
    """Each document transform must resolve its company from the embedded
    contact without a follow-up GET.
    """

    def test_invoice_field_extraction_resolves_embedded_contact(self, company: Company) -> None:
        invoice = SimpleNamespace(
            contact=_rich_contact(),
            invoice_number="INV-001",
            date="2026-05-05",
            sub_total=100,
            total_tax=15,
            total=115,
            amount_due=115,
            updated_date_utc=datetime(2026, 5, 5, tzinfo=UTC),
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("apps.xero.transforms.get_or_fetch_company", _fail_if_called)
            fields = _extract_required_fields_xero("invoice", invoice, "inv-xero-id")

        resolved = fields["company"]
        assert isinstance(resolved, Company)
        assert resolved.id == company.id

    def test_quote_transform_resolves_embedded_contact(self, company: Company) -> None:
        xero_id = str(uuid4())
        # Underscore attributes feed process_xero_data's raw_json; the plain
        # ones are the SDK accessors the transform reads directly.
        xero_quote = SimpleNamespace(
            contact=_rich_contact(),
            quote_number="Q-001",
            _status=SimpleNamespace(_value_="DRAFT"),
            _date="2026-05-05",
            _sub_total=100,
            _total=115,
            _updated_date_utc="2026-05-05T00:00:00+00:00",
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("apps.xero.transforms.get_or_fetch_company", _fail_if_called)
            quote, status = transform_quote(xero_quote, xero_id)

        assert status == "created"
        assert Quote.objects.get(xero_id=xero_id).company_id == company.id
        assert quote.number == "Q-001"

    def test_purchase_order_transform_resolves_embedded_contact(self, company: Company) -> None:
        xero_id = str(uuid4())
        xero_po = SimpleNamespace(
            contact=_rich_contact(),
            purchase_order_number="PO-9001",
            date="2026-05-05",
            status="DRAFT",
            updated_date_utc=datetime(2026, 5, 5, tzinfo=UTC),
            delivery_date=None,
            line_items=[],
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("apps.xero.transforms.get_or_fetch_company", _fail_if_called)
            po, status = transform_purchase_order(xero_po, xero_id)

        assert status == "created"
        assert PurchaseOrder.objects.get(po_number="PO-9001").supplier_id == company.id
        assert po.status == "draft"


def _fail_if_called(*args: object, **kwargs: object) -> Company:
    raise AssertionError(
        f"get_or_fetch_company was called ({args!r} {kwargs!r}) — the embedded "
        "contact should have been enough"
    )
