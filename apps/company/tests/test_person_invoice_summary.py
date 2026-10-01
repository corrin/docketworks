"""Person invoice-summary annotation tests (KAN-372).

A person's spend is the sum of sales invoices on jobs whose contact is that
person, whichever company each job was for: the owner's example is a contact
who works for two customers and whose dealings must read as one figure.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.company.models import CompanyPersonLink, ContactMethod, Person
from apps.company.services.person_service import PersonDirectoryService
from apps.company.tests.factories import make_company
from apps.company.tests.job_fixtures import make_invoice, make_job
from apps.timesheet.tests.conftest import make_staff

pytestmark = pytest.mark.django_db


def test_with_invoice_summary_sums_invoices_on_the_persons_jobs_across_companies() -> None:
    """Two customers, one contact: the figure is the contact's, not either company's."""
    staff = make_staff("summary-staff@example.com")
    cushman = make_company("Cushman")
    allied = make_company("Allied")
    rusty = Person.objects.create(name="Rusty")
    cushman_job = make_job(cushman, staff, name="Cushman job", person=rusty)
    allied_job = make_job(allied, staff, name="Allied job", person=rusty)
    make_invoice(
        cushman, job=cushman_job, invoice_date=date(2024, 1, 10), total_excl_tax=Decimal("100.00")
    )
    make_invoice(
        cushman, job=cushman_job, invoice_date=date(2024, 3, 5), total_excl_tax=Decimal("20.00")
    )
    make_invoice(
        allied, job=allied_job, invoice_date=date(2024, 2, 20), total_excl_tax=Decimal("5.50")
    )

    annotated = Person.objects.with_invoice_summary().get(id=rusty.id)

    assert annotated.last_invoice_date == date(2024, 3, 5)
    assert annotated.total_spend == Decimal("125.50")


def test_with_invoice_summary_excludes_jobs_with_no_contact() -> None:
    """An invoice on a job with no contact counts for nobody; a new person is zero."""
    staff = make_staff("nocontact-staff@example.com")
    company = make_company("Orphan Co")
    person = Person.objects.create(name="Uninvoiced")
    CompanyPersonLink.objects.create(company=company, person=person)
    job = make_job(company, staff, name="No contact job")
    make_invoice(company, job=job, total_excl_tax=Decimal("999.00"))

    annotated = Person.objects.with_invoice_summary().get(id=person.id)

    assert annotated.last_invoice_date is None
    assert annotated.total_spend == Decimal("0.00")


def test_with_invoice_summary_is_not_multiplied_by_search_joins() -> None:
    """The directory search joins links and phones; the figure must not multiply through them."""
    staff = make_staff("joins-staff@example.com")
    first = make_company("Joined Alpha")
    second = make_company("Joined Beta")
    person = Person.objects.create(name="Many Links")
    CompanyPersonLink.objects.create(company=first, person=person)
    CompanyPersonLink.objects.create(company=second, person=person)
    ContactMethod.objects.create(
        person=person,
        method_type=ContactMethod.MethodType.PHONE,
        value="021 111 1111",
        is_primary=True,
    )
    ContactMethod.objects.create(
        person=person, method_type=ContactMethod.MethodType.PHONE, value="021 222 2222"
    )
    job = make_job(first, staff, name="Single invoice job", person=person)
    make_invoice(first, job=job, invoice_date=date(2024, 6, 1), total_excl_tax=Decimal("40.00"))

    found = list(PersonDirectoryService.search("Joined"))

    assert [row.id for row in found] == [person.id]
    assert found[0].total_spend == Decimal("40.00")
    assert found[0].last_invoice_date == date(2024, 6, 1)


def test_invoice_summary_properties_require_annotation() -> None:
    """Unannotated access fails loudly instead of issuing a hidden query."""
    person = Person.objects.create(name="Unannotated")

    with pytest.raises(RuntimeError, match="with_invoice_summary"):
        _ = person.last_invoice_date

    with pytest.raises(RuntimeError, match="with_invoice_summary"):
        _ = person.total_spend
