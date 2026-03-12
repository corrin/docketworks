"""Helpers for linking Staff records with Xero Payroll employees."""

from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple

from django.db import transaction

from apps.accounts.models import Staff
from apps.timesheet.services.demo_payroll_data import (
    generate_ird_number,
    get_bank_account,
    setup_employee_bank,
    setup_employee_leave,
    setup_employee_tax,
)
from apps.workflow.api.xero.payroll import (
    create_payroll_employee,
    get_employees,
    get_payroll_calendars,
    update_employee_name,
)
from apps.workflow.models import CompanyDefaults, XeroPayItem

# Pattern to extract Staff UUID from job_title like "Workshop Worker [uuid-here]"
STAFF_UUID_PATTERN = re.compile(r"\[([0-9a-f-]{36})\]$", re.IGNORECASE)

logger = logging.getLogger("timesheet.payroll")


class PayrollEmployeeSyncService:
    """Service class used by management commands to sync staff with Xero Payroll."""

    # Pause between creating employees to avoid overwhelming Xero API
    PAUSE_BETWEEN_EMPLOYEES = 10  # seconds

    # Employee defaults
    DEFAULT_DATE_OF_BIRTH: date = date(1990, 1, 1)
    DEFAULT_START_DATE: date = date(2025, 4, 1)  # April 1, 2025
    DEFAULT_JOB_TITLE: str = "Workshop Worker"

    # Cached Xero lookups (populated once per sync run)
    _cached_weekly_calendar_id: Optional[str] = None
    _cached_ordinary_earnings_rate_id: Optional[str] = None

    @classmethod
    def _clear_cache(cls) -> None:
        """Clear cached Xero lookups."""
        cls._cached_weekly_calendar_id = None
        cls._cached_ordinary_earnings_rate_id = None

    @classmethod
    def sync_staff(
        cls,
        staff_queryset: Optional[Iterable[Staff]] = None,
        *,
        dry_run: bool = False,
        allow_create: bool = False,
    ) -> Dict[str, Any]:
        """
        Link Staff rows with Xero Payroll employees and optionally create missing employees.
        """
        # Clear cache at start of each sync run
        cls._clear_cache()

        if staff_queryset is None:
            # Only sync active staff with a wage rate (excludes admin-only users)
            staff_queryset = Staff.objects.filter(
                date_left__isnull=True,
                wage_rate__gt=0,
            )

        staff_members = list(staff_queryset)

        summary: Dict[str, Any] = {
            "total": len(staff_members),
            "linked": [],
            "created": [],
            "already_linked": [],
            "missing": [],
            "dry_run": dry_run,
            "allow_create": allow_create,
        }

        if not staff_members:
            return summary

        xero_employees = get_employees()
        employee_index = cls._index_xero_employees(xero_employees)

        matched_staff: List[Tuple[Staff, Dict[str, Optional[str]]]] = []
        missing_staff: List[Staff] = []

        for staff in staff_members:
            if staff.xero_user_id:
                summary["already_linked"].append(cls._format_staff(staff))
                continue

            match = cls._match_staff_to_employee(staff, employee_index)
            if match:
                matched_staff.append((staff, match))
            else:
                missing_staff.append(staff)

        creation_payloads: List[Tuple[Staff, Dict[str, Any]]] = []
        if allow_create and missing_staff:
            creation_payloads = [
                (staff, cls._build_employee_payload(staff, i))
                for i, staff in enumerate(missing_staff)
            ]

        if dry_run:
            summary["linked"] = [
                cls._summarize_link(staff, match["employee_id"], match)
                for staff, match in matched_staff
            ]
            summary["created"] = [
                cls._summarize_link(staff, None, None) for staff, _ in creation_payloads
            ]
            summary["missing"] = (
                []
                if allow_create
                else [cls._format_staff(staff) for staff in missing_staff]
            )
            return summary

        for staff, match in matched_staff:
            employee_id = match.get("employee_id")
            if not employee_id:
                raise ValueError(
                    f"Xero employee match for {staff.email} is missing employee_id"
                )
            cls._link_staff(staff, employee_id)
            summary["linked"].append(cls._summarize_link(staff, employee_id, match))

        if allow_create:
            for i, (staff, payload) in enumerate(creation_payloads):
                employee = create_payroll_employee(payload)
                employee_id = str(employee.employee_id)

                # Complete employee setup (tax/KiwiSaver, leave, bank)
                setup_employee_tax(employee_id, payload["ird_number"])
                setup_employee_leave(employee_id)
                setup_employee_bank(employee_id, payload["bank_account_number"])

                cls._link_staff(staff, employee_id)
                summary["created"].append(
                    cls._summarize_link(
                        staff,
                        employee_id,
                        {
                            "employee_id": employee_id,
                            "first_name": employee.first_name,
                            "last_name": employee.last_name,
                            "email": (employee.email or "").lower() or None,
                        },
                    )
                )
                # Pause between employees (not after the last one)
                if i < len(creation_payloads) - 1:
                    logger.info(
                        "Pausing %ds before next employee...",
                        cls.PAUSE_BETWEEN_EMPLOYEES,
                    )
                    time.sleep(cls.PAUSE_BETWEEN_EMPLOYEES)
            summary["missing"] = []
        else:
            summary["missing"] = [cls._format_staff(staff) for staff in missing_staff]

        return summary

    @classmethod
    def _link_staff(cls, staff: Staff, employee_id: str) -> None:
        logger.info(
            "Linking staff %s (%s) to Xero employee %s",
            staff.id,
            staff.email,
            employee_id,
        )
        # Update Xero employee name to match Staff
        update_employee_name(employee_id, staff.first_name, staff.last_name)

        staff.xero_user_id = employee_id
        with transaction.atomic():
            staff.save(update_fields=["xero_user_id", "updated_at"])

    @classmethod
    def _index_xero_employees(
        cls, employees: Iterable[Any]
    ) -> Dict[str, Dict[Any, Dict[str, Optional[str]]]]:
        by_staff_id: Dict[str, Dict[str, Optional[str]]] = {}
        by_email: Dict[str, Dict[str, Optional[str]]] = {}
        by_name: Dict[Tuple[str, str], Dict[str, Optional[str]]] = {}

        for employee in employees:
            serialized = cls._serialize_employee(employee)
            first_name = serialized["first_name"] or ""
            last_name = serialized["last_name"] or ""
            name_key = (first_name.lower(), last_name.lower())

            # Index by Staff UUID from job_title (most reliable for re-linking)
            if serialized["staff_id"]:
                by_staff_id.setdefault(serialized["staff_id"], serialized)

            if serialized["email"]:
                by_email.setdefault(serialized["email"], serialized)

            if name_key not in by_name:
                by_name[name_key] = serialized

        return {"by_staff_id": by_staff_id, "by_email": by_email, "by_name": by_name}

    @classmethod
    def _match_staff_to_employee(
        cls, staff: Staff, index: Dict[str, Dict[Any, Dict[str, Optional[str]]]]
    ) -> Optional[Dict[str, Optional[str]]]:
        # Priority 1: Match by Staff UUID in job_title (most reliable after DB restore)
        staff_id = str(staff.id).lower()
        if staff_id in index["by_staff_id"]:
            return index["by_staff_id"][staff_id]

        # Priority 2: Match by email
        email = (staff.email or "").strip().lower()
        if email and email in index["by_email"]:
            return index["by_email"][email]

        # Priority 3: Match by name
        name_key = (
            (staff.first_name or "").strip().lower(),
            (staff.last_name or "").strip().lower(),
        )
        return index["by_name"].get(name_key)

    @classmethod
    def _serialize_employee(cls, employee: Any) -> Dict[str, Optional[str]]:
        employee_id = getattr(employee, "employee_id", None)
        first_name = getattr(employee, "first_name", "") or ""
        last_name = getattr(employee, "last_name", "") or ""
        email = getattr(employee, "email", "") or ""
        job_title = getattr(employee, "job_title", "") or ""

        # Extract Staff UUID from job_title if present
        staff_id = None
        match = STAFF_UUID_PATTERN.search(job_title)
        if match:
            staff_id = match.group(1).lower()

        return {
            "employee_id": str(employee_id) if employee_id else None,
            "first_name": first_name.strip(),
            "last_name": last_name.strip(),
            "email": email.strip().lower() if email else None,
            "staff_id": staff_id,
        }

    @classmethod
    def _get_weekly_calendar_id(cls) -> Optional[str]:
        """Get the payroll calendar ID by name from Xero (cached per sync run)."""
        if cls._cached_weekly_calendar_id is not None:
            return cls._cached_weekly_calendar_id

        company = CompanyDefaults.get_solo()
        if not company.xero_payroll_calendar_name:
            raise ValueError(
                "CompanyDefaults.xero_payroll_calendar_name is not configured."
            )

        calendars = get_payroll_calendars()
        target_name = company.xero_payroll_calendar_name.lower()
        for cal in calendars:
            if cal.get("name", "").lower() == target_name:
                cls._cached_weekly_calendar_id = cal["id"]
                logger.info("Found calendar '%s': %s", cal["name"], cal["id"])
                return cls._cached_weekly_calendar_id

        raise ValueError(f"Calendar '{company.xero_payroll_calendar_name}' not found")

    @classmethod
    def _get_ordinary_earnings_rate_id(cls) -> str:
        """Get earnings rate ID for 'Ordinary Time' from XeroPayItem."""
        if cls._cached_ordinary_earnings_rate_id is not None:
            return cls._cached_ordinary_earnings_rate_id

        ordinary_time = XeroPayItem.get_ordinary_time()
        if not ordinary_time:
            raise ValueError(
                "XeroPayItem 'Ordinary Time' not found. "
                "Run sync_xero_pay_items() to sync pay items from Xero."
            )

        cls._cached_ordinary_earnings_rate_id = ordinary_time.xero_id
        logger.info(
            "Found earnings rate 'Ordinary Time': %s",
            cls._cached_ordinary_earnings_rate_id,
        )
        return cls._cached_ordinary_earnings_rate_id

    @classmethod
    def _build_employee_payload(
        cls, staff: Staff, employee_index: int
    ) -> Dict[str, Any]:
        first_name = cls._clean_string(staff.first_name, 35)
        last_name = cls._clean_string(staff.last_name, 35)
        email = cls._clean_string(staff.email, 255)
        if not first_name or not last_name or not email:
            raise ValueError(
                f"Staff {staff.id} is missing first name, last name, or email"
            )

        # Get company defaults for address
        company = CompanyDefaults.get_solo()
        if not company.address_line1 or not company.city or not company.post_code:
            raise ValueError(
                "CompanyDefaults is missing required address fields "
                "(address_line1, city, post_code)"
            )

        # Look up Xero IDs dynamically
        weekly_calendar_id = cls._get_weekly_calendar_id()
        ordinary_earnings_rate_id = cls._get_ordinary_earnings_rate_id()

        if not weekly_calendar_id:
            raise ValueError("Could not find Weekly payroll calendar in Xero")
        if not ordinary_earnings_rate_id:
            raise ValueError("Could not find Ordinary Time earnings rate in Xero")

        # Store Staff UUID in job_title for reliable re-linking after DB restore
        job_title_with_id = f"{cls.DEFAULT_JOB_TITLE} [{staff.id}]"

        payload: Dict[str, Any] = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "date_of_birth": cls.DEFAULT_DATE_OF_BIRTH,
            "start_date": cls.DEFAULT_START_DATE,
            "end_date": staff.date_left if staff.date_left else None,
            "phone_number": None,
            "job_title": job_title_with_id,
            "address": {
                "address_line1": company.address_line1,
                "address_line2": company.address_line2 or "",
                "city": company.city,
                "post_code": company.post_code,
                "suburb": company.suburb or "",
                "country_name": company.country,
            },
            # Payroll setup
            "payroll_calendar_id": weekly_calendar_id,
            "ordinary_earnings_rate_id": ordinary_earnings_rate_id,
            # Working hours from Staff model - all days must be defined
            "hours_per_week": cls._get_hours_per_week(staff),
            # Hourly wage rate from Staff model
            "wage_rate": float(staff.base_wage_rate) if staff.base_wage_rate else None,
            # Generated demo payroll data (see demo_payroll_data.py)
            "ird_number": generate_ird_number(employee_index + 1),
            "bank_account_number": get_bank_account(employee_index + 1),
        }

        return payload

    @staticmethod
    def _format_staff(staff: Staff) -> Dict[str, Any]:
        return {
            "staff_id": str(staff.id),
            "email": staff.email,
            "first_name": staff.first_name,
            "last_name": staff.last_name,
        }

    @staticmethod
    def _summarize_link(
        staff: Staff,
        employee_id: Optional[str],
        match: Optional[Dict[str, Optional[str]]],
    ) -> Dict[str, Any]:
        summary = PayrollEmployeeSyncService._format_staff(staff)
        summary.update(
            {
                "xero_employee_id": employee_id,
                "xero_email": match.get("email") if match else None,
                "xero_name": (
                    f"{match.get('first_name', '')} {match.get('last_name', '')}".strip()
                    if match
                    else None
                ),
            }
        )
        return summary

    @staticmethod
    def _get_hours_per_week(staff: Staff) -> Dict[str, float]:
        """Get working hours per day - fails if any day is None."""
        days = [
            ("monday", staff.hours_mon),
            ("tuesday", staff.hours_tue),
            ("wednesday", staff.hours_wed),
            ("thursday", staff.hours_thu),
            ("friday", staff.hours_fri),
            ("saturday", staff.hours_sat),
            ("sunday", staff.hours_sun),
        ]
        missing = [name for name, value in days if value is None]
        if missing:
            raise ValueError(
                f"Staff {staff.id} ({staff.email}) missing hours for: {', '.join(missing)}"
            )
        return {name: float(value) for name, value in days}

    @staticmethod
    def _clean_string(
        value: Optional[str], max_length: Optional[int] = None
    ) -> Optional[str]:
        if value is None:
            return None
        cleaned = str(value).strip()
        if not cleaned:
            return None
        if max_length is not None:
            return cleaned[:max_length]
        return cleaned
