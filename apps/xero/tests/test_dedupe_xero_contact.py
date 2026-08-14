"""dedupe_xero_contact archives only provably spurious duplicates."""

from collections.abc import Iterator
from io import StringIO
from types import SimpleNamespace
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone as django_timezone

from apps.company.models import Company

COMMAND_MODULE = "apps.xero.management.commands.dedupe_xero_contact"

pytestmark = pytest.mark.django_db

LINKED_ID = "05c9804b-c7b1-4947-8f90-78361759c1a2"
SPURIOUS_ID = "f59f87a9-78eb-42bd-992b-f896446d4a14"


def _contact(
    contact_id: str, name: str = "Corrin Lakeland", status: str = "ACTIVE"
) -> SimpleNamespace:
    return SimpleNamespace(contact_id=contact_id, name=name, contact_status=status)


def _run(*args: str) -> str:
    out = StringIO()
    call_command("dedupe_xero_contact", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def linked_company() -> Company:
    return Company.objects.create(
        name="Corrin Lakeland",
        xero_contact_id=LINKED_ID,
        xero_last_modified=django_timezone.now(),
    )


@pytest.fixture
def xero_boundary() -> Iterator[mock.Mock]:
    """Mock the guards and the AccountingApi; yield the api mock."""
    with (
        mock.patch(f"{COMMAND_MODULE}.assert_xero_writes_enabled"),
        mock.patch(f"{COMMAND_MODULE}.assert_not_production_target"),
        mock.patch(f"{COMMAND_MODULE}.get_api_client"),
        mock.patch(f"{COMMAND_MODULE}.get_tenant_id", return_value="tenant-1"),
        mock.patch(f"{COMMAND_MODULE}.AccountingApi") as api_cls,
    ):
        yield api_cls.return_value


class TestRefusals:
    def test_no_linked_local_company_refuses(self, xero_boundary: mock.Mock) -> None:
        with pytest.raises(CommandError, match="0 local companies"):
            _run("--name", "Corrin Lakeland")
        xero_boundary.update_contact.assert_not_called()

    @pytest.mark.usefixtures("linked_company")
    def test_linked_contact_missing_from_active_set_refuses(self, xero_boundary: mock.Mock) -> None:
        xero_boundary.get_contacts.return_value = SimpleNamespace(contacts=[_contact(SPURIOUS_ID)])
        with pytest.raises(CommandError, match="not among the ACTIVE contacts"):
            _run("--name", "Corrin Lakeland")
        xero_boundary.update_contact.assert_not_called()

    @pytest.mark.usefixtures("linked_company")
    def test_no_spurious_duplicate_refuses(self, xero_boundary: mock.Mock) -> None:
        xero_boundary.get_contacts.return_value = SimpleNamespace(contacts=[_contact(LINKED_ID)])
        with pytest.raises(CommandError, match="No spurious ACTIVE duplicate"):
            _run("--name", "Corrin Lakeland")

    @pytest.mark.usefixtures("linked_company")
    def test_duplicate_referenced_by_another_company_refuses(
        self, xero_boundary: mock.Mock
    ) -> None:
        Company.objects.create(
            name="Corrin Lakeland Ltd",
            xero_contact_id=SPURIOUS_ID,
            xero_last_modified=django_timezone.now(),
        )
        xero_boundary.get_contacts.return_value = SimpleNamespace(
            contacts=[_contact(LINKED_ID), _contact(SPURIOUS_ID)]
        )
        with pytest.raises(CommandError, match="cross-linked"):
            _run("--name", "Corrin Lakeland")
        xero_boundary.update_contact.assert_not_called()


class TestArchiving:
    @pytest.mark.usefixtures("linked_company")
    def test_dry_run_reports_and_writes_nothing(self, xero_boundary: mock.Mock) -> None:
        xero_boundary.get_contacts.return_value = SimpleNamespace(
            contacts=[_contact(LINKED_ID), _contact(SPURIOUS_ID)]
        )
        output = _run("--name", "Corrin Lakeland")
        assert f"[DRY-RUN] would archive spurious duplicate: {SPURIOUS_ID}" in output
        xero_boundary.update_contact.assert_not_called()

    @pytest.mark.usefixtures("linked_company")
    def test_apply_archives_only_the_unreferenced_duplicate(self, xero_boundary: mock.Mock) -> None:
        # An archived same-name contact in the response must not be touched
        # either: only ACTIVE unreferenced copies are spurious.
        xero_boundary.get_contacts.return_value = SimpleNamespace(
            contacts=[
                _contact(LINKED_ID),
                _contact(SPURIOUS_ID),
                _contact("old-archived", status="ARCHIVED"),
            ]
        )
        output = _run("--name", "Corrin Lakeland", "--apply")
        assert xero_boundary.update_contact.call_count == 1
        (_tenant, contact_id, contacts_payload) = xero_boundary.update_contact.call_args.args
        assert contact_id == SPURIOUS_ID
        assert contacts_payload.contacts[0].contact_status == "ARCHIVED"
        assert f"Archived spurious duplicate: {SPURIOUS_ID}" in output
        assert LINKED_ID not in output.replace(f"Locally linked (kept): {LINKED_ID}", "")
