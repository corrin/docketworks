"""Unit tests for the ONE time-entry rate pipeline (apps/job/services/time_entry_rates.py).

These guard the behaviours the three v1 pipelines disagreed about and that the
whole timesheet domain now depends on: which pay item a line gets, what a leave
job does to the multipliers, where the wage rate comes from, and how the
charge-out rate is chosen.
"""

from decimal import Decimal
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.core.models import CompanyDefaults
from apps.job.models import Job, LabourSubtype
from apps.job.services.time_entry_rates import (
    ZERO_MULTIPLIER,
    calculate_time_unit_rates,
    get_bill_rate_multiplier,
    normalize_multiplier,
    price_time_entry,
    resolve_xero_pay_item,
)

pytestmark = pytest.mark.django_db


class TestMultiplierRules:
    def test_explicit_bill_multiplier_wins(self) -> None:
        meta: dict[str, object] = {"bill_rate_multiplier": 0.5, "is_billable": False}
        assert get_bill_rate_multiplier(meta, Decimal("1.5")) == Decimal("0.50")

    def test_non_billable_means_zero(self) -> None:
        assert get_bill_rate_multiplier({"is_billable": False}, Decimal("1.5")) == ZERO_MULTIPLIER

    def test_bill_multiplier_tracks_the_wage_multiplier_by_default(self) -> None:
        assert get_bill_rate_multiplier({}, Decimal("1.5")) == Decimal("1.50")

    def test_unparseable_multiplier_falls_back_to_the_default(self) -> None:
        # v1 tolerated junk in meta rather than crashing the whole grid.
        assert normalize_multiplier("not-a-number") == Decimal("1.00")

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
        assert pricing.pay_item.name == "Time and one half"

    def test_missing_wage_rate_multiplier_fails_early(
        self, job: Job, timesheet_worker: Staff
    ) -> None:
        with pytest.raises(ValidationError, match="Rate multiplier must be provided"):
            price_time_entry(job=job, staff=timesheet_worker, meta={})

    def test_staff_without_a_wage_rate_is_refused_by_name(
        self, job: Job, unpaid_staff: Staff
    ) -> None:
        """No fallback: v1 substituted CompanyDefaults.wage_rate (costing) or 0.00
        (workshop); ADR 0015 + user decision 2026-08-03 make it a hard error."""
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
        """The behaviour v1's workshop pipeline got wrong (ADR 0039 canonicalisation)."""
        leave_job = make_job(company, office_staff, name="Annual Leave")
        leave_job.default_xero_pay_item_id = _pay_item_id("Annual Leave", uses_leave_api=True)
        leave_job.save(staff=office_staff, update_fields=["default_xero_pay_item", "updated_at"])
        leave_job.labour_rates.update(charge_out_rate=Decimal("120.00"))

        pricing = price_time_entry(
            job=leave_job,
            staff=timesheet_worker,
            # The caller asked for time-and-a-half; leave overrides it.
            meta={"wage_rate_multiplier": 1.5, "is_billable": True},
        )

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
        leave_job = make_job(company, office_staff, name="Unpaid Leave")
        leave_job.default_xero_pay_item_id = _pay_item_id("Unpaid Leave", uses_leave_api=True)
        leave_job.save(staff=office_staff, update_fields=["default_xero_pay_item", "updated_at"])

        pricing = price_time_entry(
            job=leave_job, staff=timesheet_worker, meta={"wage_rate_multiplier": 1.0}
        )

        assert pricing.wage_rate_multiplier == ZERO_MULTIPLIER
        assert pricing.unit_cost == Decimal("0.00")


def _pay_item_id(name: str, *, uses_leave_api: bool) -> UUID:
    """The id of a seeded pay item (no static apps.job -> apps.xero import)."""
    from django.apps import apps as django_apps  # noqa: PLC0415

    pay_item = django_apps.get_model("xero", "XeroPayItem")._default_manager.get(
        name=name, uses_leave_api=uses_leave_api
    )
    return UUID(str(pay_item.pk))
