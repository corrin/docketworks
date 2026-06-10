import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Tuple

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.accounts.models import Staff
from apps.job.models import CostLine, CostSet, Job, JobLabourRate, LabourSubtype
from apps.job.models.costing import get_default_cost_set_summary
from apps.job.services.time_entry_rates import (
    calculate_time_unit_rates,
    get_bill_rate_multiplier,
    normalize_multiplier,
    resolve_xero_pay_item,
)

logger = logging.getLogger(__name__)


class WorkshopTimesheetService:
    """Service encapsulating workshop staff timesheet operations."""

    def __init__(self, *, staff: Staff) -> None:
        self.staff = staff

    @staticmethod
    def resolve_entry_date(date_param: str | None):
        """Parse an optional date query parameter for workshop timesheets."""
        if not date_param:
            return timezone.localdate()

        parsed = parse_date(date_param)
        if not parsed:
            raise ValueError("date must be provided in YYYY-MM-DD format.")
        return parsed

    def list_entries(self, entry_date) -> Tuple[list[CostLine], dict]:
        """Fetch cost lines and summary for the staff member on a date."""
        queryset = (
            CostLine.objects.filter(
                cost_set__kind="actual",
                kind="time",
                staff=self.staff,
                accounting_date=entry_date,
            )
            .select_related("cost_set__job__client")
            .order_by("entry_seq")
        )

        entries = list(queryset)
        summary = self._build_summary(entries)
        return entries, summary

    def create_entry(self, data) -> CostLine:
        """Create a new CostLine for the staff member."""
        job = Job.objects.get(id=data["job_id"])

        with transaction.atomic():
            cost_set = self._get_or_create_actual_cost_set(job)
            wage_rate_multiplier = self._to_decimal(
                data.get("wage_rate_multiplier", Decimal("1.0")), default="1.0"
            )
            bill_rate_multiplier = get_bill_rate_multiplier(
                data,
                normalize_multiplier(wage_rate_multiplier),
            )
            is_billable = bill_rate_multiplier > Decimal("0.00")
            start_time = data.get("start_time")
            end_time = data.get("end_time")

            labour_subtype = self._resolve_labour_subtype(data)
            unit_cost, unit_rev, wage_rate, charge_out_rate = self._calculate_rates(
                job=job,
                labour_subtype=labour_subtype,
                wage_rate_multiplier=wage_rate_multiplier,
                bill_rate_multiplier=bill_rate_multiplier,
            )
            xero_pay_item = resolve_xero_pay_item(wage_rate_multiplier)

            meta = {
                "staff_id": str(self.staff.id),
                "date": data["accounting_date"].isoformat(),
                "is_billable": is_billable,
                "wage_rate_multiplier": float(wage_rate_multiplier),
                "bill_rate_multiplier": float(bill_rate_multiplier),
                "created_from_timesheet": True,
                "wage_rate": float(wage_rate),
                "charge_out_rate": float(charge_out_rate),
            }
            if start_time is not None:
                meta["start_time"] = self._format_time(start_time)
            if end_time is not None:
                meta["end_time"] = self._format_time(end_time)

            cost_line = CostLine.objects.create(
                cost_set=cost_set,
                kind="time",
                desc=data.get("description", None),
                quantity=data["hours"],
                unit_cost=unit_cost,
                unit_rev=unit_rev,
                accounting_date=data["accounting_date"],
                staff=self.staff,
                xero_pay_item=xero_pay_item,
                labour_subtype=labour_subtype,
                ext_refs={},
                meta=meta,
                approved=self.staff.is_office_staff,
            )

            self._update_latest_actual(job, cost_set, self.staff)

        return cost_line

    def update_entry(self, data) -> CostLine:
        """Update an existing CostLine belonging to the staff member."""
        cost_line = CostLine.objects.select_related("cost_set__job__client").get(
            id=data["entry_id"], kind="time"
        )

        if (cost_line.meta or {}).get("staff_id") != str(self.staff.id):
            raise PermissionError("You can only update your own timesheet entries.")

        with transaction.atomic():
            has_updates = False
            target_job = cost_line.cost_set.job
            target_cost_set = cost_line.cost_set
            job_changed = False

            if "description" in data:
                cost_line.desc = data["description"] or ""
                has_updates = True

            if "hours" in data:
                cost_line.quantity = data["hours"]
                has_updates = True

            if "accounting_date" in data:
                cost_line.accounting_date = data["accounting_date"]
                meta = cost_line.meta or {}
                meta["date"] = data["accounting_date"].isoformat()
                cost_line.meta = meta
                has_updates = True

            meta = cost_line.meta or {}
            recalc_rates = False

            if "job_id" in data:
                new_job_id = str(data["job_id"])
                current_job_id = str(getattr(target_job, "id", ""))
                if new_job_id != current_job_id:
                    target_job = Job.objects.get(id=data["job_id"])
                    target_cost_set = self._get_or_create_actual_cost_set(target_job)
                    cost_line.cost_set = target_cost_set
                    job_changed = True
                    has_updates = True
                    recalc_rates = True

            if "labour_subtype_id" in data:
                cost_line.labour_subtype = LabourSubtype.objects.get(
                    id=data["labour_subtype_id"]
                )
                has_updates = True
                recalc_rates = True

            if "is_billable" in data:
                if data["is_billable"]:
                    meta["bill_rate_multiplier"] = float(
                        get_bill_rate_multiplier(
                            meta,
                            self._to_decimal(
                                meta.get("wage_rate_multiplier", 1.0), default="1.0"
                            ),
                        )
                    )
                else:
                    meta["bill_rate_multiplier"] = 0.0
                meta["is_billable"] = data["is_billable"]
                recalc_rates = True

            if "bill_rate_multiplier" in data:
                bill_multiplier = self._to_decimal(
                    data["bill_rate_multiplier"], default="1.0"
                )
                meta["bill_rate_multiplier"] = float(bill_multiplier)
                meta["is_billable"] = bill_multiplier > Decimal("0.00")
                recalc_rates = True

            if "wage_rate_multiplier" in data:
                meta["wage_rate_multiplier"] = float(data["wage_rate_multiplier"])
                if "bill_rate_multiplier" not in data:
                    meta["bill_rate_multiplier"] = float(data["wage_rate_multiplier"])
                recalc_rates = True

            if "start_time" in data:
                meta["start_time"] = (
                    self._format_time(data["start_time"])
                    if data["start_time"] is not None
                    else None
                )
                has_updates = True

            if "end_time" in data:
                meta["end_time"] = (
                    self._format_time(data["end_time"])
                    if data["end_time"] is not None
                    else None
                )
                has_updates = True

            cost_line.meta = meta

            if recalc_rates:
                wage_rate_multiplier = self._to_decimal(
                    data.get("wage_rate_multiplier")
                    or meta.get("wage_rate_multiplier", 1.0),
                    default="1.0",
                )
                bill_rate_multiplier = get_bill_rate_multiplier(
                    meta,
                    normalize_multiplier(wage_rate_multiplier),
                )
                line_subtype = cost_line.labour_subtype
                if line_subtype is None:
                    raise ValueError(f"Cost line {cost_line.id} has no labour_subtype.")
                unit_cost, unit_rev, wage_rate, charge_out_rate = self._calculate_rates(
                    job=cost_line.cost_set.job,
                    labour_subtype=line_subtype,
                    wage_rate_multiplier=wage_rate_multiplier,
                    bill_rate_multiplier=bill_rate_multiplier,
                )
                cost_line.unit_cost = unit_cost
                cost_line.unit_rev = unit_rev
                cost_line.xero_pay_item = resolve_xero_pay_item(wage_rate_multiplier)
                meta["wage_rate"] = float(wage_rate)
                meta["charge_out_rate"] = float(charge_out_rate)
                meta["bill_rate_multiplier"] = float(bill_rate_multiplier)
                meta["is_billable"] = bill_rate_multiplier > Decimal("0.00")
                cost_line.meta = meta
                has_updates = True

            if not has_updates:
                raise ValueError("No changes supplied.")

            cost_line.save()
            if job_changed:
                self._update_latest_actual(target_job, target_cost_set, self.staff)

        return cost_line

    def delete_entry(self, entry_id: str) -> CostLine:
        """Delete a CostLine belonging to the staff member."""
        cost_line = CostLine.objects.get(id=entry_id, kind="time")

        if (cost_line.meta or {}).get("staff_id") != str(self.staff.id):
            raise PermissionError("You can only delete your own timesheet entries.")

        cost_line.delete()
        return cost_line

    @staticmethod
    def _build_summary(entries: Iterable[CostLine]) -> dict:
        total_hours = Decimal("0")
        billable_hours = Decimal("0")
        total_cost = Decimal("0")
        total_revenue = Decimal("0")

        for line in entries:
            quantity = WorkshopTimesheetService._to_decimal(line.quantity, default="0")
            total_hours += quantity
            if (line.meta or {}).get("is_billable", True):
                billable_hours += quantity
            total_cost += quantity * WorkshopTimesheetService._to_decimal(
                line.unit_cost, default="0"
            )
            total_revenue += quantity * WorkshopTimesheetService._to_decimal(
                line.unit_rev, default="0"
            )

        non_billable_hours = total_hours - billable_hours
        return {
            "total_hours": float(total_hours),
            "billable_hours": float(billable_hours),
            "non_billable_hours": float(non_billable_hours),
            "total_cost": float(total_cost),
            "total_revenue": float(total_revenue),
        }

    @staticmethod
    def _get_or_create_actual_cost_set(job: Job):
        cost_set, _ = CostSet.objects.get_or_create(
            job=job,
            kind="actual",
            defaults={"rev": 1, "summary": get_default_cost_set_summary()},
        )
        return cost_set

    def _resolve_labour_subtype(self, data: Mapping[str, Any]) -> LabourSubtype:
        """Explicit subtype from the request, else the staff member's default."""
        if data.get("labour_subtype_id"):
            return LabourSubtype.objects.get(id=data["labour_subtype_id"])

        default = self.staff.default_labour_subtype
        if default is None:
            raise ValueError(
                f"Staff {self.staff.id} has no default_labour_subtype and no "
                "labour_subtype_id was supplied."
            )
        return default

    def _calculate_rates(
        self,
        *,
        job: Job,
        labour_subtype: LabourSubtype,
        wage_rate_multiplier: Decimal,
        bill_rate_multiplier: Decimal,
    ) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        job_rate = JobLabourRate.objects.get(job=job, labour_subtype=labour_subtype)
        return calculate_time_unit_rates(
            wage_rate=getattr(self.staff, "wage_rate", None),
            charge_out_rate=job_rate.charge_out_rate,
            wage_rate_multiplier=wage_rate_multiplier,
            bill_rate_multiplier=bill_rate_multiplier,
        )

    @staticmethod
    def _update_latest_actual(job: Job, cost_set: CostSet, staff):
        if not job.latest_actual or cost_set.rev >= job.latest_actual.rev:
            job.latest_actual = cost_set
            job.save(staff=staff, update_fields=["latest_actual", "updated_at"])

    @staticmethod
    def _to_decimal(value, default: str):
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError):
            return Decimal(default)

    @staticmethod
    def _format_time(value):
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)
