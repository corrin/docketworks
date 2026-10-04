"""A company's Xero contact id is never stored without the organisation it belongs to."""

from collections.abc import Iterator
from importlib import import_module

import pytest
from django.apps import apps
from django.db import IntegrityError, connection, transaction

from apps.company.models import Company
from apps.company.tests.factories import make_company
from apps.core.models import CompanyDefaults

pytestmark = pytest.mark.django_db

GUARD = "company_xero_contact_id_has_tenant"


def test_a_contact_id_with_no_tenant_is_refused_by_the_schema() -> None:
    # Production held 3,920 such rows for months with nothing failing, and one
    # of them makes a restore seed clear the whole mirror.
    with pytest.raises(IntegrityError, match=GUARD), transaction.atomic():
        make_company("Half Linked Ltd", xero_contact_id="contact-1", xero_tenant_id=None)


def test_a_company_not_in_xero_needs_neither() -> None:
    assert make_company("Prospect Ltd").xero_contact_id is None


@pytest.fixture
def before_the_guard() -> Iterator[None]:
    """The schema as the backfill finds it: the guard is the migration after it.

    Dropped inside the test's transaction, which the test rolls back.
    """
    with connection.cursor() as cursor:
        # Postgres will not alter a table with deferred checks still queued.
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(f'ALTER TABLE company_company DROP CONSTRAINT "{GUARD}"')
    yield


def backfill() -> None:
    migration = import_module(
        "apps.company.migrations.0002_backfill_xero_tenant_on_linked_companies"
    )
    with connection.schema_editor() as schema_editor:
        migration.stamp_tenant_on_linked_companies(apps, schema_editor)


@pytest.mark.usefixtures("before_the_guard")
def test_backfill_gives_unstamped_links_the_organisation_the_stamped_ones_name() -> None:
    CompanyDefaults.objects.update(xero_tenant_id="our-tenant")
    unstamped = make_company("Old Customer Ltd", xero_contact_id="c-old", xero_tenant_id=None)
    stamped = make_company("Recent Ltd", xero_contact_id="c-new", xero_tenant_id="our-tenant")
    prospect = make_company("Prospect Ltd")
    companies_before = Company.objects.count()

    backfill()

    unstamped.refresh_from_db()
    stamped.refresh_from_db()
    prospect.refresh_from_db()
    assert unstamped.xero_tenant_id == "our-tenant"
    assert stamped.xero_tenant_id == "our-tenant"
    # Not in Xero, so in no organisation.
    assert prospect.xero_tenant_id is None
    # Populated, never deleted: these are customers with invoices.
    assert Company.objects.count() == companies_before


@pytest.mark.usefixtures("before_the_guard")
def test_backfill_on_a_restored_copy_keeps_the_source_organisation() -> None:
    # A restore bound to its own demo organisation and not yet re-seeded: the
    # contact ids are still the source's. Stamping them with the bound tenant
    # would make the seed read the mirror as already linked and skip its clear.
    CompanyDefaults.objects.update(xero_tenant_id="dev-tenant")
    Company.objects.filter(xero_contact_id__isnull=False).delete()
    make_company("Stamped in production", xero_contact_id="c-1", xero_tenant_id="prod-tenant")
    restored = make_company("Never re-synced", xero_contact_id="c-2", xero_tenant_id=None)

    backfill()

    restored.refresh_from_db()
    assert restored.xero_tenant_id == "prod-tenant"


@pytest.mark.usefixtures("before_the_guard")
def test_backfill_uses_the_configured_organisation_when_no_company_is_stamped() -> None:
    CompanyDefaults.objects.update(xero_tenant_id="our-tenant")
    Company.objects.filter(xero_contact_id__isnull=False).delete()
    unstamped = make_company("Old Customer Ltd", xero_contact_id="c-old", xero_tenant_id=None)

    backfill()

    unstamped.refresh_from_db()
    assert unstamped.xero_tenant_id == "our-tenant"


@pytest.mark.usefixtures("before_the_guard")
def test_backfill_refuses_when_nothing_says_which_organisation() -> None:
    CompanyDefaults.objects.update(xero_tenant_id=None)
    Company.objects.filter(xero_contact_id__isnull=False).delete()
    make_company("Old Customer Ltd", xero_contact_id="c-old", xero_tenant_id=None)

    with pytest.raises(RuntimeError, match="Do not bind an organisation"):
        backfill()


@pytest.mark.usefixtures("before_the_guard")
def test_backfill_refuses_when_stamped_companies_name_two_organisations() -> None:
    Company.objects.filter(xero_contact_id__isnull=False).delete()
    make_company("One Ltd", xero_contact_id="c-1", xero_tenant_id="tenant-a")
    make_company("Two Ltd", xero_contact_id="c-2", xero_tenant_id="tenant-b")
    make_company("Old Customer Ltd", xero_contact_id="c-old", xero_tenant_id=None)

    with pytest.raises(RuntimeError, match="2 different organisations"):
        backfill()


def test_backfill_asks_nothing_of_an_instance_with_no_links() -> None:
    CompanyDefaults.objects.update(xero_tenant_id=None)
    make_company("Prospect Ltd")

    backfill()
