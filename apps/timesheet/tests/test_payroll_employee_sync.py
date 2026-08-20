"""Tests for linking Staff rows to payroll employees.

The matching engine is exercised directly; the ``sync_staff`` orchestration
runs against a recording fake provider, so what is asserted is which provider
calls were made and what landed on the Staff rows — never a Xero payload.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.accounting.types import NewPayrollEmployee, PayrollEmployeeRef
from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults
from apps.timesheet.services import payroll_employee_sync as sync
from apps.timesheet.tests.conftest import make_staff

pytestmark = pytest.mark.django_db

TENANT = "tenant-under-test"
OTHER_TENANT = "some-other-organisation"


def ref(
    external_id: str,
    *,
    first_name: str = "",
    last_name: str = "",
    email: str | None = None,
    job_title: str | None = None,
) -> PayrollEmployeeRef:
    """Build a provider employee reference with only the fields a test cares about."""
    return PayrollEmployeeRef(
        external_id=external_id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        job_title=job_title,
    )


class FakeProvider:
    """Records every payroll-employee call and hands back plausible results.

    Fable: Not a sibling of the conftest FakePayrollProvider: this fakes the
    employee CRUD slice of the provider protocol (list/create/rename), which
    is disjoint from the posting surface that one fakes — no method appears
    on both, so there is nothing to consolidate.
    """

    def __init__(self, employees: list[PayrollEmployeeRef] | None = None) -> None:
        self.employees = employees or []
        self.created: list[NewPayrollEmployee] = []
        self.renamed: list[tuple[str, str, str]] = []

    def list_payroll_employees(self) -> list[PayrollEmployeeRef]:
        return self.employees

    def create_payroll_employee(self, spec: NewPayrollEmployee) -> PayrollEmployeeRef:
        self.created.append(spec)
        return ref(
            f"created-{len(self.created)}",
            first_name=spec.first_name,
            last_name=spec.last_name,
            email=spec.email,
            job_title=spec.job_title,
        )

    def update_payroll_employee_name(
        self, external_id: str, first_name: str, last_name: str
    ) -> None:
        self.renamed.append((external_id, first_name, last_name))


@pytest.fixture
def employer_address() -> None:
    """Give CompanyDefaults the address Xero demands on a created employee."""
    defaults = CompanyDefaults.get_solo()
    defaults.address_line1 = "1 Molesworth Street"
    defaults.suburb = "Pipitea"
    defaults.city = "Wellington"
    defaults.post_code = "6011"
    defaults.country = "New Zealand"
    defaults.save(update_fields=["address_line1", "suburb", "city", "post_code", "country"])


def run_sync(
    provider: FakeProvider,
    staff_members: list[Staff] | None = None,
    **kwargs: object,
) -> sync.SyncStaffResult:
    """Call sync_staff with the provider registry stubbed out."""
    with patch.object(sync, "get_provider", return_value=provider):
        return sync.sync_staff(staff_members, tenant_id=TENANT, **kwargs)  # type: ignore[arg-type]


class TestSerializeEmployee:
    def test_extracts_the_staff_uuid_from_the_job_title(self) -> None:
        staff_id = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
        record = sync.serialize_employee(
            ref("emp-1", job_title=f"Workshop Worker [{staff_id.upper()}]")
        )

        assert record.staff_id == staff_id

    def test_normalises_names_and_email(self) -> None:
        record = sync.serialize_employee(
            ref("emp-1", first_name="  Ana ", last_name=" Silva", email=" A@B.COM ")
        )

        assert record.first_name == "Ana"
        assert record.last_name == "Silva"
        assert record.email == "a@b.com"

    def test_absent_fields_become_empty_or_none(self) -> None:
        record = sync.serialize_employee(ref("emp-1"))

        assert record.first_name == ""
        assert record.email is None
        assert record.staff_id is None


@pytest.mark.usefixtures("company")
class TestMatching:
    def _staff(self) -> Staff:
        return make_staff("match-target@example.com", first_name="Ana", last_name="Silva")

    def test_uuid_in_the_job_title_beats_email_and_name(self) -> None:
        """The UUID is the only key that survives a database restore."""
        staff = self._staff()
        by_uuid = ref("emp-uuid", job_title=f"Workshop Worker [{staff.id}]")
        by_email = ref("emp-email", email=staff.office_email)
        index = sync.index_employees([by_email, by_uuid])

        match = sync.match_staff_to_employee(staff, index)

        assert match is not None
        assert match.employee_id == "emp-uuid"

    def test_email_beats_name(self) -> None:
        staff = self._staff()
        index = sync.index_employees(
            [
                ref("emp-name", first_name="Ana", last_name="Silva"),
                ref("emp-email", email=staff.office_email.upper()),
            ]
        )

        match = sync.match_staff_to_employee(staff, index)

        assert match is not None
        assert match.employee_id == "emp-email"

    def test_name_is_the_last_resort(self) -> None:
        staff = self._staff()
        index = sync.index_employees([ref("emp-name", first_name="ANA", last_name="silva")])

        match = sync.match_staff_to_employee(staff, index)

        assert match is not None
        assert match.employee_id == "emp-name"

    def test_no_match_returns_none(self) -> None:
        staff = self._staff()
        index = sync.index_employees([ref("emp-other", first_name="Bo", last_name="Kim")])

        assert sync.match_staff_to_employee(staff, index) is None

    def test_the_first_employee_wins_a_duplicated_key(self) -> None:
        staff = self._staff()
        index = sync.index_employees(
            [
                ref("emp-first", email=staff.office_email),
                ref("emp-second", email=staff.office_email),
            ]
        )

        match = sync.match_staff_to_employee(staff, index)

        assert match is not None
        assert match.employee_id == "emp-first"


@pytest.mark.usefixtures("company")
class TestSummaries:
    def test_link_summary_carries_both_sides(self) -> None:
        staff = make_staff("summary@example.com", first_name="Ana", last_name="Silva")
        record = sync.serialize_employee(
            ref("emp-1", first_name="Ana", last_name="Silva", email="ana@xero.test")
        )

        summary = sync.link_summary(staff, "emp-1", record)

        assert summary["staff_id"] == str(staff.id)
        assert summary["office_email"] == "summary@example.com"
        assert summary["xero_employee_id"] == "emp-1"
        assert summary["xero_email"] == "ana@xero.test"
        assert summary["xero_name"] == "Ana Silva"

    def test_link_summary_without_a_match(self) -> None:
        staff = make_staff("unmatched@example.com")

        summary = sync.link_summary(staff, None, None)

        assert summary["xero_employee_id"] is None
        assert summary["xero_name"] is None


@pytest.mark.usefixtures("company")
class TestStaffFacts:
    def test_job_title_carries_the_uuid_for_relinking(self) -> None:
        staff = make_staff("title@example.com")

        assert sync.xero_job_title(staff) == f"Workshop Worker [{staff.id}]"

    def test_hours_per_week_reads_the_staff_row(self) -> None:
        staff = make_staff("hours@example.com")
        staff.hours_fri = Decimal("6.00")
        staff.save(update_fields=["hours_fri", "updated_at"])

        assert sync.hours_per_week(staff) == {
            "monday": 8.0,
            "tuesday": 8.0,
            "wednesday": 8.0,
            "thursday": 8.0,
            "friday": 6.0,
            "saturday": 0.0,
            "sunday": 0.0,
        }

    def test_link_staff_records_the_employee_id_and_its_organisation(self) -> None:
        """An id with no organisation is the state a restored dump arrives in."""
        staff = make_staff("link@example.com")

        sync.link_staff(staff, "emp-42", TENANT)

        staff.refresh_from_db()
        assert staff.xero_user_id == "emp-42"
        assert staff.xero_tenant_id == TENANT

    def test_syncable_staff_excludes_leavers_and_unpaid_logins(self) -> None:
        payable = make_staff("payable@example.com")
        make_staff("unpaid@example.com", base_wage_rate=Decimal("0.00"))
        leaver = make_staff("gone@example.com")
        leaver.date_left = date(2026, 1, 1)
        leaver.save(update_fields=["date_left", "updated_at"])

        assert [staff.id for staff in sync.syncable_staff()] == [payable.id]

    def test_clean_string_trims_and_truncates(self) -> None:
        assert sync.clean_string("  Ana  ") == "Ana"
        assert sync.clean_string("   ") is None
        assert sync.clean_string(None) is None
        assert sync.clean_string("abcdef", 3) == "abc"


@pytest.mark.usefixtures("company")
class TestStaffNeedingPayrollLink:
    def test_a_restored_production_id_with_no_organisation_is_pending(self) -> None:
        """The exact shape a scrubbed dump arrives in: id set, tenant NULL."""
        restored = make_staff("restored@example.com", xero_user_id="prod-employee-1")

        assert [s.id for s in sync.staff_needing_payroll_link(TENANT)] == [restored.id]

    def test_staff_linked_to_this_organisation_are_not_pending(self) -> None:
        linked = make_staff("linked@example.com", xero_user_id="emp-1")
        Staff.objects.filter(pk=linked.pk).update(xero_tenant_id=TENANT)

        assert not sync.staff_needing_payroll_link(TENANT).exists()

    def test_staff_linked_to_another_organisation_are_pending(self) -> None:
        elsewhere = make_staff("elsewhere@example.com", xero_user_id="emp-1")
        Staff.objects.filter(pk=elsewhere.pk).update(xero_tenant_id=OTHER_TENANT)

        assert [s.id for s in sync.staff_needing_payroll_link(TENANT)] == [elsewhere.id]

    def test_staff_who_never_had_an_id_are_left_alone(self) -> None:
        """They were not linked in production; the seed has no mandate over them."""
        make_staff("never-linked@example.com", xero_user_id="")

        assert not sync.staff_needing_payroll_link(TENANT).exists()

    def test_leavers_are_included(self) -> None:
        """Historical timesheets for a departed staff member still have to post."""
        leaver = make_staff("leaver@example.com", xero_user_id="prod-employee-2")
        leaver.date_left = date(2026, 1, 1)
        leaver.save(update_fields=["date_left", "updated_at"])

        assert [s.id for s in sync.staff_needing_payroll_link(TENANT)] == [leaver.id]


@pytest.mark.usefixtures("company")
class TestSyncStaff:
    def test_a_matched_staff_member_is_renamed_then_linked(self) -> None:
        staff = make_staff(
            "matched@example.com", first_name="Ana", last_name="Silva", xero_user_id="prod-1"
        )
        provider = FakeProvider([ref("demo-1", job_title=f"Workshop Worker [{staff.id}]")])

        result = run_sync(provider, [staff])

        assert provider.renamed == [("demo-1", "Ana", "Silva")]
        assert provider.created == []
        assert [link["xero_employee_id"] for link in result.linked] == ["demo-1"]
        staff.refresh_from_db()
        assert (staff.xero_user_id, staff.xero_tenant_id) == ("demo-1", TENANT)

    @pytest.mark.usefixtures("employer_address")
    def test_an_unmatched_staff_member_is_created_and_linked(self) -> None:
        staff = make_staff(
            "new@example.com", first_name="Bo", last_name="Kim", xero_user_id="prod-2"
        )
        provider = FakeProvider()

        result = run_sync(provider, [staff], allow_create=True)

        assert len(provider.created) == 1
        assert len(result.created) == 1
        staff.refresh_from_db()
        assert (staff.xero_user_id, staff.xero_tenant_id) == ("created-1", TENANT)

    @pytest.mark.usefixtures("employer_address")
    def test_the_creation_spec_carries_what_relinking_a_restore_depends_on(self) -> None:
        staff = make_staff(
            "spec@example.com",
            first_name="Bo",
            last_name="Kim",
            base_wage_rate=Decimal("31.50"),
            xero_user_id="prod-3",
        )
        staff.date_left = date(2026, 3, 31)
        staff.hours_fri = Decimal("4.00")
        staff.save(update_fields=["date_left", "hours_fri", "updated_at"])
        provider = FakeProvider()

        run_sync(provider, [staff], allow_create=True)

        spec = provider.created[0]
        assert spec.job_title == f"Workshop Worker [{staff.id}]"
        assert spec.end_date == date(2026, 3, 31)
        assert spec.hourly_rate == Decimal("31.50")
        assert spec.hours_per_week["friday"] == 4.0
        assert spec.email == "spec@example.com"

    def test_creation_is_refused_without_allow_create(self) -> None:
        staff = make_staff("nocreate@example.com", xero_user_id="prod-4")
        provider = FakeProvider()

        result = run_sync(provider, [staff])

        assert provider.created == []
        assert [row["office_email"] for row in result.unmatched] == ["nocreate@example.com"]
        staff.refresh_from_db()
        assert staff.xero_tenant_id is None

    def test_staff_already_linked_here_are_skipped(self) -> None:
        staff = make_staff("already@example.com", xero_user_id="demo-9")
        Staff.objects.filter(pk=staff.pk).update(xero_tenant_id=TENANT)
        staff.refresh_from_db()
        provider = FakeProvider([ref("demo-9", job_title=f"Workshop Worker [{staff.id}]")])

        result = run_sync(provider, [staff], allow_create=True)

        assert provider.renamed == []
        assert provider.created == []
        assert [row["office_email"] for row in result.already_linked] == ["already@example.com"]

    def test_a_dry_run_writes_nothing(self) -> None:
        staff = make_staff("dry@example.com", xero_user_id="prod-5")
        provider = FakeProvider()

        result = run_sync(provider, [staff], dry_run=True, allow_create=True)

        assert provider.created == []
        assert provider.renamed == []
        assert len(result.created) == 1
        staff.refresh_from_db()
        assert (staff.xero_user_id, staff.xero_tenant_id) == ("prod-5", None)

    def test_an_empty_batch_never_reaches_the_provider(self) -> None:
        provider = FakeProvider()

        result = run_sync(provider, [])

        assert result == sync.SyncStaffResult()


@pytest.mark.usefixtures("company")
class TestPreflightRefusals:
    def test_every_unusable_row_is_named_and_nothing_is_written(self) -> None:
        """v1 raised on the first, after already creating employees for the rest."""
        no_wage = make_staff("nowage@example.com", base_wage_rate=Decimal("0"), xero_user_id="p1")
        no_hours = make_staff("nohours@example.com", xero_user_id="p2")
        Staff.objects.filter(pk=no_hours.pk).update(
            hours_mon=0, hours_tue=0, hours_wed=0, hours_thu=0, hours_fri=0
        )
        no_hours.refresh_from_db()
        provider = FakeProvider()

        with pytest.raises(sync.StaffNotPayrollReadyError) as excinfo:
            run_sync(provider, [no_wage, no_hours], allow_create=True)

        message = str(excinfo.value)
        assert "nowage@example.com" in message
        assert "nohours@example.com" in message
        assert provider.created == []

    def test_a_matched_row_is_not_held_to_the_creation_contract(self) -> None:
        """It links to an employee the organisation already holds; nothing is built."""
        staff = make_staff(
            "matched-nowage@example.com",
            first_name="Ana",
            last_name="Silva",
            base_wage_rate=Decimal("0"),
            xero_user_id="prod-6",
        )
        provider = FakeProvider([ref("demo-2", job_title=f"Workshop Worker [{staff.id}]")])

        result = run_sync(provider, [staff], allow_create=True)

        assert [link["xero_employee_id"] for link in result.linked] == ["demo-2"]

    def test_two_staff_matching_one_employee_is_refused_before_any_write(self) -> None:
        """Staff.xero_user_id is unique; the loser would fail partway through."""
        first = make_staff(
            "twin-a@example.com", first_name="Ana", last_name="Silva", xero_user_id="p7"
        )
        second = make_staff(
            "twin-b@example.com", first_name="Ana", last_name="Silva", xero_user_id="p8"
        )
        provider = FakeProvider([ref("demo-3", first_name="Ana", last_name="Silva")])

        with pytest.raises(sync.StaffNotPayrollReadyError, match="both match payroll employee"):
            run_sync(provider, [first, second], allow_create=True)

        assert provider.renamed == []

    @pytest.mark.usefixtures("employer_address")
    def test_a_missing_company_address_refuses_before_any_write(self) -> None:
        staff = make_staff("noaddress@example.com", xero_user_id="p9")
        defaults = CompanyDefaults.get_solo()
        defaults.city = None
        defaults.save(update_fields=["city"])
        provider = FakeProvider()

        with pytest.raises(sync.StaffNotPayrollReadyError, match=r"CompanyDefaults\.city"):
            run_sync(provider, [staff], allow_create=True)

        assert provider.created == []
