"""Unit tests for the ONE time-entry rate pipeline (apps/job/services/time_entry_rates.py).

These guard the rate decisions the whole timesheet domain depends on: which pay
item a line gets, what a leave
job does to the multipliers, where the wage rate comes from, and how the
charge-out rate is chosen.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import Staff, StaffPayrollTerm
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.core.models import CompanyDefaults
from apps.job.models import Job, LabourSubtype
from apps.job.services.time_entry_rates import (
    DEFAULT_MULTIPLIER,
    ZERO_MULTIPLIER,
    calculate_time_unit_rates,
    get_bill_rate_multiplier,
    price_time_entry,
    rate_from_meta,
    resolve_xero_pay_item,
)
from apps.timesheet.models import LeaveType

pytestmark = pytest.mark.django_db


class TestMultiplierRules:
    def test_explicit_bill_multiplier_wins(self) -> None:
        meta: dict[str, object] = {"bill_rate_multiplier": 0.5, "is_billable": False}
        assert get_bill_rate_multiplier(meta, Decimal("1.5")) == Decimal("0.50")

    def test_non_billable_means_zero(self) -> None:
        assert get_bill_rate_multiplier({"is_billable": False}, Decimal("1.5")) == ZERO_MULTIPLIER

    def test_bill_multiplier_tracks_the_wage_multiplier_by_default(self) -> None:
        assert get_bill_rate_multiplier({}, Decimal("1.5")) == Decimal("1.50")

    def test_unset_multiplier_is_absent_not_a_value(self) -> None:
        assert rate_from_meta({}, "bill_rate_multiplier") is None
        assert rate_from_meta({"bill_rate_multiplier": None}, "bill_rate_multiplier") is None

    def test_stored_multiplier_is_read_as_the_number_it_reads_as(self) -> None:
        assert rate_from_meta({"m": "1.5"}, "m") == Decimal("1.5")
        assert rate_from_meta({"m": 0.1}, "m") == Decimal("0.1")  # not the binary 0.1

    def test_unparseable_multiplier_raises_rather_than_defaulting(self) -> None:
        """It used to return 1.00, pricing the line at full rate on bad data.

        That made a corrupt multiplier indistinguishable from an unset one, and
        the two mean opposite things: unset is "use the default", corrupt is
        "this row is wrong". Fix the row (ADR 0015).
        """
        for stored in ("not-a-number", "", [1.5], {"v": 1}):
            with pytest.raises(ValidationError, match="must be a number"):
                rate_from_meta({"bill_rate_multiplier": stored}, "bill_rate_multiplier")

    def test_non_finite_multiplier_raises(self) -> None:
        """Parsing as a Decimal is not proof of a usable number.

        Decimal accepts "NaN" and "Infinity". Infinity then raises
        InvalidOperation inside quantize() as an uncaught 500; NaN is worse,
        returning quietly and poisoning every multiplication after it, so the
        line prices at NaN. The same defect as _positive_int's non-finite
        floats, which this PR fixes one app over.
        """
        for stored in ("NaN", "Infinity", "-Infinity", float("nan"), float("inf")):
            with pytest.raises(ValidationError, match="must be a finite number"):
                rate_from_meta({"bill_rate_multiplier": stored}, "bill_rate_multiplier")

    def test_rates_are_quantized_to_cents(self) -> None:
        rates = calculate_time_unit_rates(
            wage_rate=Decimal("33.333"),
            charge_out_rate=Decimal("105.555"),
            wage_rate_multiplier=Decimal("1.5"),
            bill_rate_multiplier=Decimal("1.0"),
        )
        assert rates.unit_cost == Decimal("50.00")  # 33.33 * 1.5
        assert rates.unit_rev == Decimal("105.56")

    def test_missing_pay_item_for_multiplier_fails_early(self, job: Job) -> None:
        assert job is not None  # the fixture seeds the standard catalogue
        with pytest.raises(ValidationError, match="No Xero pay item found"):
            resolve_xero_pay_item(Decimal("3.75"))


class TestPriceTimeEntry:
    def test_prices_from_staff_wage_and_job_charge_out_rate(
        self, job: Job, timesheet_worker: Staff
    ) -> None:
        workshop = LabourSubtype.default_workshop()
        job.labour_rates.filter(labour_subtype=workshop).update(charge_out_rate=Decimal("120.00"))

        pricing = price_time_entry(
            job=job,
            staff=timesheet_worker,
            meta={"wage_rate_multiplier": 1.5},
        )

        assert pricing.unit_cost == Decimal("72.00")  # 48.00 * 1.5
        assert pricing.unit_rev == Decimal("180.00")  # 120.00 * 1.5
        assert pricing.is_billable is True
        assert pricing.labour_subtype == workshop
        assert pricing.pay_item is not None
        assert pricing.pay_item.name == "Time and one half"

    def test_missing_wage_rate_multiplier_fails_early(
        self, job: Job, timesheet_worker: Staff
    ) -> None:
        with pytest.raises(ValidationError, match="Rate multiplier must be provided"):
            price_time_entry(job=job, staff=timesheet_worker, meta={})

    def test_staff_without_a_wage_rate_is_refused_by_name(
        self, job: Job, unpaid_staff: Staff
    ) -> None:
        """Missing wage rates are a hard error, not a silent default or zero cost."""
        defaults = CompanyDefaults.get_solo()
        defaults.wage_rate = Decimal("30.00")
        defaults.save(update_fields=["wage_rate"])
        assert unpaid_staff.wage_rate == Decimal("0")

        with pytest.raises(ValidationError) as excinfo:
            price_time_entry(job=job, staff=unpaid_staff, meta={"wage_rate_multiplier": 1.0})

        message = "; ".join(excinfo.value.messages)
        assert "Wage rate is not configured" in message
        assert "Unpriced Person" in message
        assert str(unpaid_staff.id) in message

    def test_an_explicit_wage_rate_override_satisfies_the_guard(
        self, job: Job, unpaid_staff: Staff
    ) -> None:
        pricing = price_time_entry(
            job=job,
            staff=unpaid_staff,
            meta={"wage_rate_multiplier": 1.0},
            wage_rate_override=Decimal("55.00"),
        )

        assert pricing.unit_cost == Decimal("55.00")

    def test_salaried_staff_are_costed_from_effective_xero_terms(
        self, job: Job, unpaid_staff: Staff
    ) -> None:
        unpaid_staff.pay_basis = "salary"
        unpaid_staff.save(update_fields=["pay_basis", "updated_at"])
        CompanyDefaults.objects.update(labour_cost_loading=Decimal("20.00"))
        term = StaffPayrollTerm.objects.create(
            staff=unpaid_staff,
            effective_from=date(2026, 1, 1),
            pay_basis="salary",
            annual_salary=Decimal("104000.00"),
            working_weeks=[
                {
                    "monday": 8,
                    "tuesday": 8,
                    "wednesday": 8,
                    "thursday": 8,
                    "friday": 8,
                    "saturday": 0,
                    "sunday": 0,
                }
            ],
        )

        pricing = price_time_entry(
            job=job,
            staff=unpaid_staff,
            meta={"date": "2026-08-18", "wage_rate_multiplier": 1.5},
        )

        assert pricing.wage_rate == Decimal("60.00")  # $104k / 52 / 40, plus 20% loading
        assert pricing.unit_cost == Decimal("60.00")
        assert pricing.wage_rate_multiplier == Decimal("1.00")
        assert pricing.bill_rate_multiplier == Decimal("1.50")
        assert pricing.salary_term_id == str(term.id)

    def test_subtype_defaults_from_the_worker(self, job: Job, timesheet_worker: Staff) -> None:
        pricing = price_time_entry(
            job=job, staff=timesheet_worker, meta={"wage_rate_multiplier": 1.0}
        )
        assert pricing.labour_subtype == timesheet_worker.default_labour_subtype

    def test_explicit_subtype_selects_that_jobs_rate(
        self, job: Job, timesheet_worker: Staff
    ) -> None:
        onsite = LabourSubtype.objects.get(name="Onsite")
        job.labour_rates.filter(labour_subtype=onsite).update(charge_out_rate=Decimal("165.00"))

        pricing = price_time_entry(
            job=job,
            staff=timesheet_worker,
            meta={"wage_rate_multiplier": 1.0},
            labour_subtype=onsite,
        )

        assert pricing.unit_rev == Decimal("165.00")

    def test_leave_job_uses_its_leave_pay_item_and_never_bills(
        self, company: Company, office_staff: Staff, timesheet_worker: Staff
    ) -> None:
        """Leave pricing remains job-aware through the canonical pipeline (ADR 0039)."""
        leave_job = _configured_leave_job(company, office_staff, "Annual Leave", "annual_leave")
        leave_job.labour_rates.update(charge_out_rate=Decimal("120.00"))

        pricing = price_time_entry(
            job=leave_job,
            staff=timesheet_worker,
            # The caller asked for time-and-a-half; leave overrides it.
            meta={"wage_rate_multiplier": 1.5, "is_billable": True},
        )

        assert pricing.pay_item is not None
        assert pricing.pay_item.name == "Annual Leave"
        assert pricing.wage_rate_multiplier == Decimal("1.00")
        assert pricing.bill_rate_multiplier == ZERO_MULTIPLIER
        assert pricing.is_billable is False
        assert pricing.unit_rev == Decimal("0.00")
        assert pricing.unit_cost == Decimal("48.00")

    def test_leave_pay_item_without_a_xero_id_is_refused(
        self, company: Company, office_staff: Staff, timesheet_worker: Staff
    ) -> None:
        """Backup-loaded pay items carry no xero_id until the tenant is connected."""
        from django.apps import apps as django_apps  # noqa: PLC0415

        pay_item_model = django_apps.get_model("xero", "XeroPayItem")
        pay_item_model._default_manager.filter(name="Sick Leave", uses_leave_api=True).update(
            xero_id=None
        )
        leave_job = make_job(company, office_staff, name="Sick Leave")
        leave_job.default_xero_pay_item_id = _pay_item_id("Sick Leave", uses_leave_api=True)
        leave_job.save(staff=office_staff, update_fields=["default_xero_pay_item", "updated_at"])

        with pytest.raises(ValidationError, match="no xero_id"):
            price_time_entry(
                job=leave_job, staff=timesheet_worker, meta={"wage_rate_multiplier": 1.0}
            )

    def test_unpaid_leave_job_costs_nothing(
        self, company: Company, office_staff: Staff, timesheet_worker: Staff
    ) -> None:
        leave_job = _configured_leave_job(company, office_staff, "Unpaid Leave", "unpaid_leave")

        pricing = price_time_entry(
            job=leave_job, staff=timesheet_worker, meta={"wage_rate_multiplier": 1.0}
        )

        assert pricing.wage_rate_multiplier == ZERO_MULTIPLIER
        assert pricing.unit_cost == Decimal("0.00")

    def test_paid_leave_is_costed_at_full_rate(
        self, company: Company, office_staff: Staff, timesheet_worker: Staff
    ) -> None:
        """Whether leave is paid comes from its category, not from its Xero name."""
        leave_job = _configured_leave_job(company, office_staff, "Sick Leave", "sick_leave")

        pricing = price_time_entry(
            job=leave_job, staff=timesheet_worker, meta={"wage_rate_multiplier": 1.0}
        )

        assert pricing.wage_rate_multiplier == DEFAULT_MULTIPLIER

    def test_renaming_the_xero_leave_item_does_not_make_unpaid_leave_paid(
        self, company: Company, office_staff: Staff, timesheet_worker: Staff
    ) -> None:
        """The regression: pay was decided by ``"unpaid" in pay_item.name.lower()``.

        The leave-settings screen lets an admin rename these, and renaming this
        one away from the word "unpaid" used to cost a full day's pay per day
        booked, with nothing reporting it.
        """
        from django.apps import apps as django_apps  # noqa: PLC0415

        leave_job = _configured_leave_job(company, office_staff, "Unpaid Leave", "unpaid_leave")
        pay_item_model = django_apps.get_model("xero", "XeroPayItem")
        pay_item_model._default_manager.filter(pk=leave_job.default_xero_pay_item_id).update(
            name="Leave Without Pay"
        )

        pricing = price_time_entry(
            job=leave_job, staff=timesheet_worker, meta={"wage_rate_multiplier": 1.0}
        )

        assert pricing.wage_rate_multiplier == ZERO_MULTIPLIER

    def test_a_leave_item_no_category_claims_is_refused(
        self, company: Company, office_staff: Staff, timesheet_worker: Staff
    ) -> None:
        """The organisation holds 18 leave types and Docketworks maps four.

        Two of the unmapped ones are unpaid, so assuming "paid" for an unmapped
        item would rebuild the overpayment for the next category configured.
        """
        from django.apps import apps as django_apps  # noqa: PLC0415

        unmapped = django_apps.get_model("xero", "XeroPayItem")._default_manager.create(
            name="Parental Leave - Primary Carer", uses_leave_api=True, xero_id=uuid4()
        )
        leave_job = make_job(company, office_staff, name="Parental Leave")
        leave_job.default_xero_pay_item_id = unmapped.pk
        leave_job.save(staff=office_staff, update_fields=["default_xero_pay_item", "updated_at"])

        with pytest.raises(ValidationError, match="not mapped to a Docketworks leave category"):
            price_time_entry(
                job=leave_job, staff=timesheet_worker, meta={"wage_rate_multiplier": 1.0}
            )


def _configured_leave_job(
    company: Company, actor: Staff, pay_item_name: str, leave_code: str
) -> Job:
    """A leave job bound to its Xero pay item AND claimed by its LeaveType.

    Opus: Both halves, because that is what an onboarded instance has:
    ``configure_default_leave_types`` binds the category to the job whose
    default pay item posts it. The seed migration leaves ``LeaveType.job`` NULL
    when the special jobs do not exist yet, which is the state a test database
    is in — so a test that skipped this would be asserting against a
    configuration no real installation runs.
    """
    leave_job = make_job(company, actor, name=pay_item_name)
    leave_job.default_xero_pay_item_id = _pay_item_id(pay_item_name, uses_leave_api=True)
    leave_job.save(staff=actor, update_fields=["default_xero_pay_item", "updated_at"])
    LeaveType.objects.filter(code=leave_code).update(job=leave_job)
    return leave_job


def _pay_item_id(name: str, *, uses_leave_api: bool) -> UUID:
    """The id of a seeded pay item (no static apps.job -> apps.xero import)."""
    from django.apps import apps as django_apps  # noqa: PLC0415

    pay_item = django_apps.get_model("xero", "XeroPayItem")._default_manager.get(
        name=name, uses_leave_api=uses_leave_api
    )
    return UUID(str(pay_item.pk))
