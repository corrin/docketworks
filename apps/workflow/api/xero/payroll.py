"""Xero Payroll NZ API Integration."""

import logging
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from xero_python.payrollnz import PayrollNzApi
from xero_python.payrollnz.models import (
    Address,
    BankAccount,
    Employee,
    EmployeeLeaveSetup,
    EmployeeTax,
    EmployeeWorkingPatternWithWorkingWeeksRequest,
    Employment,
    PaymentMethod,
    PayRun,
    SalaryAndWage,
    TaxCode,
    Timesheet,
    TimesheetLine,
    WorkingWeek,
)

from apps.workflow.api.xero.xero import api_client, get_tenant_id
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models import CompanyDefaults, XeroPayItem
from apps.workflow.services.error_persistence import (
    persist_and_raise,
    persist_app_error,
)

logger = logging.getLogger("xero.payroll")

# Sleep after every API call to avoid hitting rate limits
# Xero has per-minute, per-hour, and per-day limits - be patient
SLEEP_TIME = 3

# Monkeypatch for Xero Python NZ Payroll API (dev-only, does not affect PROD)
# Problem: when fetching employees, we get an error because the SDK expects all employees to have date of birth,
# but the default contractors of Demo Company don't have date of birth, and the REST API doesn't allow PUTTING dateOfBirth for contractors.
# Result: we can't GET employees and we can't PUT contractors to fix that.
# The monkeypatch below aims to fix that by allowing Employee objects to have None as date of birth.


def _safe_date_of_birth(self, value):
    self._date_of_birth = value


Employee.date_of_birth = Employee.date_of_birth.setter(_safe_date_of_birth)


# Monkeypatch SalaryAndWage to accept null annual_salary (SDK bug for hourly employees)
def _safe_annual_salary(self, value):
    self._annual_salary = value


def _safe_status(self, value):
    self._status = value


SalaryAndWage.annual_salary = SalaryAndWage.annual_salary.setter(_safe_annual_salary)
SalaryAndWage.status = SalaryAndWage.status.setter(_safe_status)


# Same issue for Employment.engagement_type - SDK requires it but Demo Company rejects it
def _safe_engagement_type(self, value):
    self._engagement_type = value


Employment.engagement_type = Employment.engagement_type.setter(_safe_engagement_type)


# Monkeypatch TimesheetLine - Xero API returns nulls for date/earnings_rate_id/number_of_units
# after delete_timesheet. SDK requires these to be non-null but Xero returns null in response.
# Verified: Bug occurs with valid timesheets too (tested 2025-12-28).
# SDK version: xero-python 9.3.0 (latest as of 2025-12-28)
def _safe_timesheet_line_date(self, value):
    self._date = value


def _safe_timesheet_line_earnings_rate_id(self, value):
    self._earnings_rate_id = value


def _safe_timesheet_line_number_of_units(self, value):
    self._number_of_units = value


TimesheetLine.date = TimesheetLine.date.setter(_safe_timesheet_line_date)
TimesheetLine.earnings_rate_id = TimesheetLine.earnings_rate_id.setter(
    _safe_timesheet_line_earnings_rate_id
)
TimesheetLine.number_of_units = TimesheetLine.number_of_units.setter(
    _safe_timesheet_line_number_of_units
)


def get_employees() -> List[Employee]:
    """
    Get list of Xero Payroll employees.

    Returns:
        List of Employee objects from Xero

    Raises:
        Exception: If API call fails
    """
    if not get_tenant_id():
        raise Exception("No Xero tenant ID configured")

    tenant_id = get_tenant_id()
    payroll_api = PayrollNzApi(api_client)

    try:
        logger.info("Fetching Xero Payroll employees")
        response = payroll_api.get_employees(xero_tenant_id=tenant_id)
        employees = response.employees if response.employees else []
        logger.info(f"Retrieved {len(employees)} employees from Xero Payroll")
        return employees
    except Exception as exc:
        logger.error(f"Failed to get Xero Payroll employees: {exc}", exc_info=True)
        persist_and_raise(exc)


def create_payroll_employee(employee_data: Dict[str, Any]) -> Employee:
    """
    Create a payroll employee in Xero with full employment setup.

    Creates the employee record, then sets up:
    - Employment (links to payroll calendar)
    - Working pattern (weekly hours)
    - Salary and wage (hourly rate)

    Args:
        employee_data: Dict containing:
            - first_name, last_name, email (required)
            - date_of_birth, start_date, job_title
            - end_date (optional, for terminated employees)
            - address (dict with address_line1, city, post_code)
            - payroll_calendar_id (required for employment)
            - ordinary_earnings_rate_id (required for salary)
            - hours_per_week (dict with monday-sunday hours)
            - wage_rate (hourly rate)

    Returns:
        Newly created Employee object.
    """
    if not get_tenant_id():
        raise Exception("No Xero tenant ID configured")

    required_fields = (
        "first_name",
        "last_name",
        "date_of_birth",
        "address",
        "payroll_calendar_id",
        "ordinary_earnings_rate_id",
        "wage_rate",
        "ird_number",
        "bank_account_number",
    )
    for field in required_fields:
        if not employee_data.get(field):
            raise ValueError(f"{field} is required to create a Xero payroll employee")

    address_data = employee_data["address"]
    address_required_fields = ("address_line1", "city", "post_code")
    for field in address_required_fields:
        if not address_data.get(field):
            raise ValueError(
                f"{field} is required inside the address payload for payroll employees"
            )

    tenant_id = get_tenant_id()
    payroll_api = PayrollNzApi(api_client)

    try:
        logger.info(
            "Creating Xero Payroll employee for %s %s",
            employee_data.get("first_name"),
            employee_data.get("last_name"),
        )

        address = Address(
            address_line1=address_data["address_line1"],
            address_line2=address_data.get("address_line2"),
            city=address_data["city"],
            suburb=address_data.get("suburb"),
            country_name=address_data.get("country_name"),
            post_code=address_data["post_code"],
        )

        employee = Employee(
            first_name=employee_data["first_name"],
            last_name=employee_data["last_name"],
            date_of_birth=employee_data["date_of_birth"],
            address=address,
            email=employee_data.get("email"),
            phone_number=employee_data.get("phone_number"),
            start_date=employee_data.get("start_date"),
            end_date=employee_data.get("end_date"),
            engagement_type=employee_data.get("engagement_type"),
            gender=employee_data.get("gender"),
            job_title=employee_data.get("job_title"),
        )

        response = payroll_api.create_employee(
            xero_tenant_id=tenant_id,
            employee=employee,
        )
        time.sleep(SLEEP_TIME)

        if not response or not response.employee:
            raise Exception("Failed to create payroll employee in Xero")

        created_employee = response.employee
        employee_id = str(created_employee.employee_id)
        logger.info(
            "Created Xero Payroll employee %s (%s %s)",
            employee_id,
            created_employee.first_name,
            created_employee.last_name,
        )

        # Set up employment (links employee to payroll calendar)
        _create_employment(
            payroll_api,
            tenant_id,
            employee_id,
            employee_data["payroll_calendar_id"],
            employee_data.get("start_date"),
        )

        # Set up salary and wage (hourly rate) - MUST be before working pattern
        hours_per_week = employee_data.get("hours_per_week")
        _create_salary_and_wage(
            payroll_api,
            tenant_id,
            employee_id,
            employee_data["ordinary_earnings_rate_id"],
            employee_data["wage_rate"],
            hours_per_week,
            employee_data.get("start_date"),
        )

        # Set up working pattern (weekly hours) - requires salary to exist first
        if hours_per_week:
            _create_working_pattern(
                payroll_api,
                tenant_id,
                employee_id,
                hours_per_week,
                employee_data.get("start_date"),
            )

        # Set up tax (IRD number, tax code, KiwiSaver) - required for pay runs
        _create_employee_tax(
            payroll_api,
            tenant_id,
            employee_id,
            employee_data["ird_number"],
            TaxCode.M,  # Main employment
        )

        # Set up bank account - required for pay runs
        _create_employee_payment_method(
            payroll_api,
            tenant_id,
            employee_id,
            employee_data["bank_account_number"],
        )

        # Set up leave entitlements - required for pay runs
        _create_employee_leave_setup(
            payroll_api,
            tenant_id,
            employee_id,
        )

        return created_employee
    except Exception as exc:
        logger.error(
            "Failed to create Xero Payroll employee %s %s: %s",
            employee_data.get("first_name"),
            employee_data.get("last_name"),
            exc,
            exc_info=True,
        )
        persist_and_raise(
            exc,
            additional_context={
                "operation": "create_payroll_employee",
                "email": employee_data.get("email"),
            },
        )


def update_employee_name(employee_id: str, first_name: str, last_name: str) -> None:
    """
    Update an existing Xero Payroll employee's name.

    Fetches the existing employee data and only updates the name fields.

    Args:
        employee_id: Xero employee ID (UUID string)
        first_name: New first name
        last_name: New last name
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        raise Exception("No Xero tenant ID configured")

    payroll_api = PayrollNzApi(api_client)

    # Fetch existing employee to preserve their data
    response = payroll_api.get_employee(
        xero_tenant_id=tenant_id,
        employee_id=employee_id,
    )
    if not response or not response.employee:
        raise Exception(f"Employee {employee_id} not found in Xero")

    existing = response.employee

    # Fix garbage data from Xero demo company (gender serialized as string 'None')
    if existing.gender == "None":
        existing.gender = None

    # Update only the name fields
    existing.first_name = first_name
    existing.last_name = last_name

    payroll_api.update_employee(
        xero_tenant_id=tenant_id,
        employee_id=employee_id,
        employee=existing,
    )
    time.sleep(SLEEP_TIME)
    logger.info(
        "Updated Xero employee %s name to %s %s",
        employee_id,
        first_name,
        last_name,
    )


def _create_employment(
    payroll_api: PayrollNzApi,
    tenant_id: str,
    employee_id: str,
    payroll_calendar_id: str,
    start_date: Optional[date],
) -> None:
    """Create employment record linking employee to payroll calendar."""
    # engagement_type omitted - Demo Company rejects it, prod may need it later
    employment = Employment(
        payroll_calendar_id=payroll_calendar_id,
        start_date=start_date,
    )
    payroll_api.create_employment(
        xero_tenant_id=tenant_id,
        employee_id=employee_id,
        employment=employment,
    )
    time.sleep(SLEEP_TIME)
    logger.info("Created employment for employee %s", employee_id)


def _create_working_pattern(
    payroll_api: PayrollNzApi,
    tenant_id: str,
    employee_id: str,
    hours_per_week: Dict[str, float],
    effective_from: Optional[date],
) -> None:
    """Create working pattern with weekly hours."""
    # All days must be present - validated by PayrollEmployeeSyncService
    working_week = WorkingWeek(
        monday=hours_per_week["monday"],
        tuesday=hours_per_week["tuesday"],
        wednesday=hours_per_week["wednesday"],
        thursday=hours_per_week["thursday"],
        friday=hours_per_week["friday"],
        saturday=hours_per_week["saturday"],
        sunday=hours_per_week["sunday"],
    )
    pattern_request = EmployeeWorkingPatternWithWorkingWeeksRequest(
        effective_from=effective_from,
        working_weeks=[working_week],
    )
    payroll_api.create_employee_working_pattern(
        xero_tenant_id=tenant_id,
        employee_id=employee_id,
        employee_working_pattern_with_working_weeks_request=pattern_request,
    )
    time.sleep(SLEEP_TIME)
    total_hours = sum(hours_per_week.values())
    logger.info(
        "Created working pattern for employee %s (%.1f hrs/week)",
        employee_id,
        total_hours,
    )


def _create_salary_and_wage(
    payroll_api: PayrollNzApi,
    tenant_id: str,
    employee_id: str,
    earnings_rate_id: str,
    hourly_rate: float,
    hours_per_week: Optional[Dict[str, float]],
    effective_from: Optional[date],
) -> None:
    """Create salary and wage record with hourly rate."""
    total_hours = sum(hours_per_week.values()) if hours_per_week else 40.0
    # Calculate working days (days with non-zero hours)
    if hours_per_week:
        working_days = sum(1 for h in hours_per_week.values() if h > 0)
    else:
        working_days = 5  # Default Mon-Fri
    hours_per_day = total_hours / working_days if working_days > 0 else 8.0

    # SDK requires annual_salary and status even for hourly employees (client-side validation bugs)
    # These are not meaningful for hourly but SDK enforces them
    salary_and_wage = SalaryAndWage(
        earnings_rate_id=earnings_rate_id,
        number_of_units_per_week=total_hours,
        number_of_units_per_day=hours_per_day,
        days_per_week=working_days,  # Required by API
        rate_per_unit=hourly_rate,
        annual_salary=0,  # Required by SDK, not meaningful for hourly
        status="Active",  # Required by SDK
        effective_from=effective_from,
        payment_type="Hourly",
    )
    payroll_api.create_employee_salary_and_wage(
        xero_tenant_id=tenant_id,
        employee_id=employee_id,
        salary_and_wage=salary_and_wage,
    )
    time.sleep(SLEEP_TIME)
    logger.info(
        "Created salary for employee %s ($%.2f/hr, %.1f hrs/week)",
        employee_id,
        hourly_rate,
        total_hours,
    )


def _create_employee_tax(
    payroll_api: PayrollNzApi,
    tenant_id: str,
    employee_id: str,
    ird_number: str,
    tax_code: TaxCode = TaxCode.M,
) -> None:
    """Set up employee tax details including KiwiSaver and ESCT rate.

    ESCT rate 17.5% is for income $16,801-$57,600 (reasonable default).
    KiwiSaver: 3% employee, 3% employer (standard rates).
    """
    # Clean IRD: remove dashes and ensure 9 digits
    ird_clean = ird_number.replace("-", "").zfill(9)
    employee_tax = EmployeeTax(
        ird_number=ird_clean,
        tax_code=tax_code,
        esct_rate_percentage=17.5,
        is_eligible_for_kiwi_saver=True,
        kiwi_saver_contributions="MakeContributions",
        kiwi_saver_employee_contribution_rate_percentage=3.0,
        kiwi_saver_employer_contribution_rate_percentage=3.0,
        kiwi_saver_employer_salary_sacrifice_contribution_rate_percentage=0.0,
    )
    payroll_api.update_employee_tax(
        xero_tenant_id=tenant_id,
        employee_id=employee_id,
        employee_tax=employee_tax,
    )
    time.sleep(SLEEP_TIME)
    logger.info(
        "Set tax for employee %s (IRD=%s, code=%s, KiwiSaver=3%%/3%%)",
        employee_id,
        ird_number,
        tax_code.value if hasattr(tax_code, "value") else tax_code,
    )


def _create_employee_payment_method(
    payroll_api: PayrollNzApi,
    tenant_id: str,
    employee_id: str,
    bank_account_number: str,
) -> None:
    """Set up employee bank account for payment.

    NZ bank account format: BB-bbbb-AAAAAAA-SSS
    - BB: bank code (2 digits)
    - bbbb: branch code (4 digits)
    - AAAAAAA: account number (7 digits)
    - SSS: suffix (2-3 digits)

    Xero API requires:
    - sort_code: 6 digits (bank + branch, no dashes)
    - account_number: 15-16 digits (full account, no dashes)
    """
    parts = bank_account_number.split("-")
    if len(parts) != 4:
        raise ValueError(
            f"Invalid NZ bank account format: {bank_account_number}. "
            "Expected BB-bbbb-AAAAAAA-SSS"
        )
    # Xero wants: sort_code = 6 digits, account_number = full 16 digits (no dashes)
    sort_code = f"{parts[0]}{parts[1]}"
    account_number = f"{parts[0]}{parts[1]}{parts[2]}{parts[3]}"

    bank_account = BankAccount(
        account_name="Wages",
        account_number=account_number,
        sort_code=sort_code,
        calculation_type="Balance",
    )
    payment_method = PaymentMethod(
        payment_method="Electronically",
        bank_accounts=[bank_account],
    )
    payroll_api.create_employee_payment_method(
        xero_tenant_id=tenant_id,
        employee_id=employee_id,
        payment_method=payment_method,
    )
    time.sleep(SLEEP_TIME)
    logger.info(
        "Set payment method for employee %s (bank=%s)",
        employee_id,
        bank_account_number,
    )


def _create_employee_leave_setup(
    payroll_api: PayrollNzApi,
    tenant_id: str,
    employee_id: str,
) -> None:
    """Set up employee leave entitlements (annual and sick leave).

    NZ standard entitlements:
    - Annual leave: 160 hours per year (4 weeks)
    - Sick leave: 80 hours per year (10 days)
    """
    leave_setup = EmployeeLeaveSetup(
        include_holiday_pay=False,
        holiday_pay_opening_balance=0.0,
        annual_leave_opening_balance=160.0,
        sick_leave_to_accrue_annually=80.0,
        sick_leave_maximum_to_accrue=80.0,
        sick_leave_opening_balance=80.0,
    )
    payroll_api.create_employee_leave_setup(
        xero_tenant_id=tenant_id,
        employee_id=employee_id,
        employee_leave_setup=leave_setup,
    )
    time.sleep(SLEEP_TIME)
    logger.info(
        "Set leave for employee %s (Annual=160h, Sick=80h)",
        employee_id,
    )


def get_employee_salary_and_wages(employee_id: str) -> List[SalaryAndWage]:
    """
    Get salary and wage records for a Xero Payroll employee.

    Returns:
        List of SalaryAndWage objects (typically one active record per employee)

    Raises:
        Exception: If API call fails
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        raise Exception("No Xero tenant ID configured")

    payroll_api = PayrollNzApi(api_client)

    try:
        logger.info("Fetching salary/wage for employee %s", employee_id)
        response = payroll_api.get_employee_salary_and_wages(
            xero_tenant_id=tenant_id,
            employee_id=employee_id,
        )
        time.sleep(SLEEP_TIME)
        records = response.salary_and_wages if response.salary_and_wages else []
        logger.info(
            "Retrieved %d salary/wage records for employee %s",
            len(records),
            employee_id,
        )
        return records
    except Exception as exc:
        logger.error(
            "Failed to get salary/wage for employee %s: %s",
            employee_id,
            exc,
            exc_info=True,
        )
        persist_and_raise(exc)


def get_employee_working_patterns(employee_id: str) -> List[Dict[str, float]]:
    """
    Get working pattern (weekly hours per day) for a Xero Payroll employee.

    Returns:
        List of dicts with keys: monday, tuesday, ..., sunday (float hours).
        Typically one active pattern per employee.

    Raises:
        Exception: If API call fails
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        raise Exception("No Xero tenant ID configured")

    payroll_api = PayrollNzApi(api_client)

    try:
        logger.info("Fetching working patterns for employee %s", employee_id)
        response = payroll_api.get_employee_working_patterns(
            xero_tenant_id=tenant_id,
            employee_id=employee_id,
        )
        time.sleep(SLEEP_TIME)

        patterns = []
        if response and response.working_patterns:
            for pattern in response.working_patterns:
                if not pattern.working_weeks:
                    continue
                # Use the first (typically only) working week
                week = pattern.working_weeks[0]
                patterns.append(
                    {
                        "monday": float(week.monday or 0),
                        "tuesday": float(week.tuesday or 0),
                        "wednesday": float(week.wednesday or 0),
                        "thursday": float(week.thursday or 0),
                        "friday": float(week.friday or 0),
                        "saturday": float(week.saturday or 0),
                        "sunday": float(week.sunday or 0),
                    }
                )

        logger.info(
            "Retrieved %d working patterns for employee %s",
            len(patterns),
            employee_id,
        )
        return patterns
    except Exception as exc:
        logger.error(
            "Failed to get working patterns for employee %s: %s",
            employee_id,
            exc,
            exc_info=True,
        )
        persist_and_raise(exc)


def get_payroll_calendars() -> List[Dict[str, Any]]:
    """
    Get list of Xero Payroll calendars.

    Returns:
        List of payroll calendar dictionaries

    Raises:
        Exception: If API call fails
    """
    if not get_tenant_id():
        raise Exception("No Xero tenant ID configured")

    tenant_id = get_tenant_id()
    payroll_api = PayrollNzApi(api_client)

    try:
        logger.info("Fetching Xero Payroll calendars")
        response = payroll_api.get_pay_run_calendars(xero_tenant_id=tenant_id)

        calendars = []
        if response and response.pay_run_calendars:
            for cal in response.pay_run_calendars:
                calendars.append(
                    {
                        "id": cal.payroll_calendar_id,
                        "name": cal.name,
                        "calendar_type": cal.calendar_type,
                        "period_start_date": cal.period_start_date,
                        "period_end_date": cal.period_end_date,
                        "payment_date": cal.payment_date,
                    }
                )

        logger.info(f"Retrieved {len(calendars)} payroll calendars from Xero")
        return calendars
    except Exception as exc:
        logger.error(f"Failed to get Xero Payroll calendars: {exc}", exc_info=True)
        persist_and_raise(exc)


def get_pay_runs() -> List[Dict[str, Any]]:
    """
    Get list of Xero Payroll pay runs.

    Returns:
        List of pay run dictionaries with details

    Raises:
        Exception: If API call fails
    """
    if not get_tenant_id():
        raise Exception("No Xero tenant ID configured")

    tenant_id = get_tenant_id()
    payroll_api = PayrollNzApi(api_client)

    try:
        logger.info("Fetching Xero Payroll pay runs")
        response = payroll_api.get_pay_runs(xero_tenant_id=tenant_id)

        pay_runs = []
        if response and response.pay_runs:
            for pr in response.pay_runs:
                pay_runs.append(
                    {
                        "pay_run_id": str(pr.pay_run_id) if pr.pay_run_id else None,
                        "payroll_calendar_id": (
                            str(pr.payroll_calendar_id)
                            if pr.payroll_calendar_id
                            else None
                        ),
                        "period_start_date": pr.period_start_date,
                        "period_end_date": pr.period_end_date,
                        "payment_date": pr.payment_date,
                        "pay_run_status": pr.pay_run_status,
                        "pay_run_type": pr.pay_run_type,
                    }
                )

        logger.info(f"Retrieved {len(pay_runs)} pay runs from Xero Payroll")
        return pay_runs
    except Exception as exc:
        logger.error(f"Failed to get Xero Payroll pay runs: {exc}", exc_info=True)
        persist_and_raise(exc)


def get_pay_run(pay_run_id: str):
    """
    Get a single pay run from Xero by ID.

    Args:
        pay_run_id: UUID of the pay run in Xero.

    Returns:
        PayRun object from Xero API, or None if not found.

    Raises:
        Exception: If API call fails.
    """
    if not get_tenant_id():
        raise Exception("No Xero tenant ID configured")

    tenant_id = get_tenant_id()
    payroll_api = PayrollNzApi(api_client)

    try:
        logger.info(f"Fetching Xero pay run {pay_run_id}")
        response = payroll_api.get_pay_run(
            xero_tenant_id=tenant_id, pay_run_id=pay_run_id
        )

        if response and response.pay_run:
            return response.pay_run
        return None
    except Exception as exc:
        logger.error(f"Failed to get Xero pay run {pay_run_id}: {exc}", exc_info=True)
        persist_and_raise(exc)


def get_pay_run_for_week(week_start_date: date) -> Optional[Dict[str, Any]]:
    """
    Get a single pay run that matches the provided week.

    Args:
        week_start_date: Monday of the week to search for

    Returns:
        Pay run dictionary if found, otherwise None

    Raises:
    ValueError: If week_start_date is not a Monday
        Exception: If fetching pay runs fails
    """
    if week_start_date.weekday() != 0:
        raise ValueError("week_start_date must be a Monday")

    pay_runs = get_pay_runs()
    week_end_date = week_start_date + timedelta(days=6)

    for pay_run in pay_runs:
        start_date = _coerce_xero_date(pay_run.get("period_start_date"))
        end_date = _coerce_xero_date(pay_run.get("period_end_date"))

        logger.info(
            "Evaluating pay run %s: start=%s end=%s status=%s",
            pay_run.get("pay_run_id"),
            start_date,
            end_date,
            pay_run.get("pay_run_status"),
        )

        if start_date == week_start_date and end_date == week_end_date:
            return pay_run

    logger.info(
        "No pay run matched week %s-%s (checked %s runs)",
        week_start_date,
        week_end_date,
        len(pay_runs),
    )
    return None


def get_leave_types() -> List[Dict[str, Any]]:
    """
    Get list of Xero Payroll leave types.

    Returns:
        List of leave types with their IDs and names

    Raises:
        Exception: If API call fails
    """
    if not get_tenant_id():
        raise Exception("No Xero tenant ID configured")

    tenant_id = get_tenant_id()
    payroll_api = PayrollNzApi(api_client)

    try:
        logger.info("Fetching Xero Payroll leave types")
        response = payroll_api.get_leave_types(xero_tenant_id=tenant_id)

        leave_types = []
        if response and response.leave_types:
            for lt in response.leave_types:
                leave_types.append(
                    {
                        "id": lt.leave_type_id,
                        "name": lt.name,
                    }
                )

        logger.info(f"Retrieved {len(leave_types)} leave types from Xero Payroll")
        return leave_types
    except Exception as exc:
        logger.error(f"Failed to get Xero Payroll leave types: {exc}", exc_info=True)
        persist_and_raise(exc)


def get_earnings_rates() -> List[Dict[str, Any]]:
    """
    Get list of Xero Payroll earnings rates.

    Returns:
        List of earnings rates with their IDs, names, and types

    Raises:
        Exception: If API call fails
    """
    if not get_tenant_id():
        raise Exception("No Xero tenant ID configured")

    tenant_id = get_tenant_id()
    payroll_api = PayrollNzApi(api_client)

    try:
        logger.info("Fetching Xero Payroll earnings rates")
        response = payroll_api.get_earnings_rates(xero_tenant_id=tenant_id)

        earnings_rates = []
        if response and response.earnings_rates:
            for rate in response.earnings_rates:
                # Get multiplier from Xero
                # rate_type can be: RatePerUnit, MultipleOfOrdinaryEarningsRate, FixedAmount
                multiplier = None
                if rate.rate_type == "MultipleOfOrdinaryEarningsRate":
                    multiplier = rate.multiple_of_ordinary_earnings_rate
                elif rate.rate_type == "RatePerUnit":
                    # Ordinary time is rate per unit with implicit 1.0x multiplier
                    multiplier = 1.0

                earnings_rates.append(
                    {
                        "id": rate.earnings_rate_id,
                        "name": rate.name,
                        "earnings_type": rate.earnings_type,
                        "rate_type": rate.rate_type,
                        "type_of_units": rate.type_of_units,
                        "multiplier": multiplier,
                    }
                )

        logger.info(f"Retrieved {len(earnings_rates)} earnings rates from Xero Payroll")
        return earnings_rates
    except Exception as exc:
        logger.error(f"Failed to get Xero Payroll earnings rates: {exc}", exc_info=True)
        persist_and_raise(exc)


# Cache for earnings rate lookups (populated once per session)
_earnings_rate_cache: Dict[str, str] = {}


def ensure_earnings_rate_cache() -> None:
    """
    Pre-populate the earnings rate cache from Xero API.

    Call this at the start of operations to ensure all rate lookups
    are validated upfront before any modifying API calls.
    """
    if not _earnings_rate_cache:
        logger.info("Pre-fetching earnings rates from Xero")
        rates = get_earnings_rates()
        for rate in rates:
            _earnings_rate_cache[rate["name"]] = rate["id"]
        logger.info(f"Cached {len(_earnings_rate_cache)} earnings rates")


def get_earnings_rate_id_by_name(name: str) -> str:
    """
    Look up a Xero earnings rate ID by its name.

    Uses cached results. Call ensure_earnings_rate_cache() first
    for fail-early validation.

    Args:
        name: The earnings rate name (e.g., "Ordinary Time")

    Returns:
        The earnings rate ID (UUID string)

    Raises:
        ValueError: If the named earnings rate is not found in Xero
    """
    # Populate cache if not already done (lazy fallback)
    ensure_earnings_rate_cache()

    if name not in _earnings_rate_cache:
        available = ", ".join(sorted(_earnings_rate_cache.keys()))
        raise ValueError(
            f"Earnings rate '{name}' not found in Xero. "
            f"Available rates: {available}"
        )

    return _earnings_rate_cache[name]


# Cache for leave type lookups (populated once per session)
_leave_type_cache: Dict[str, str] = {}


def ensure_leave_type_cache() -> None:
    """
    Pre-populate the leave type cache from Xero API.

    Call this at the start of operations to ensure all leave type lookups
    are validated upfront before any modifying API calls.
    """
    if not _leave_type_cache:
        logger.info("Pre-fetching leave types from Xero")
        leave_types = get_leave_types()
        for lt in leave_types:
            _leave_type_cache[lt["name"]] = lt["id"]
        logger.info(f"Cached {len(_leave_type_cache)} leave types")


def get_leave_type_id_by_name(name: str) -> str:
    """
    Look up a Xero leave type ID by its name.

    Uses cached results. Call ensure_leave_type_cache() first
    for fail-early validation.

    Args:
        name: The leave type name (e.g., "Annual Leave")

    Returns:
        The leave type ID (UUID string)

    Raises:
        ValueError: If the named leave type is not found in Xero
    """
    ensure_leave_type_cache()

    if name not in _leave_type_cache:
        available = ", ".join(sorted(_leave_type_cache.keys()))
        raise ValueError(
            f"Leave type '{name}' not found in Xero. " f"Available types: {available}"
        )

    return _leave_type_cache[name]


def _coerce_xero_date(value: Any) -> Optional[date]:
    """Normalize Xero date or datetime payloads (strings, datetimes, dates) into date objects."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        cleaned = value.replace("Z", "")
        try:
            return datetime.fromisoformat(cleaned).date()
        except ValueError:
            try:
                return date.fromisoformat(cleaned.split("T")[0])
            except ValueError:
                return None
    return value


def create_pay_run(
    week_start_date: date,
    payment_date: date = None,
) -> Dict[str, str]:
    """
    Create a new pay run in Xero Payroll for the specified week.

    Args:
        week_start_date: Monday of the week
        payment_date: Optional payment date (defaults to Wednesday after period end)

    Returns:
        Dict with 'pay_run_id' and 'payroll_calendar_id'

    Raises:
        ValueError: If week_start_date is not a Monday, or configuration is missing
        Exception: If Xero API call fails
    """
    if week_start_date.weekday() != 0:
        raise ValueError("week_start_date must be a Monday")

    tenant_id = get_tenant_id()
    if not tenant_id:
        raise ValueError("No Xero tenant ID configured")

    # Get calendar from CompanyDefaults
    company = CompanyDefaults.get_solo()
    target_calendar_name = company.xero_payroll_calendar_name
    if not target_calendar_name:
        raise ValueError("xero_payroll_calendar_name not configured in CompanyDefaults")

    # Find matching calendar in Xero
    calendars = get_payroll_calendars()
    matching_calendar = next(
        (c for c in calendars if c["name"] == target_calendar_name), None
    )
    if not matching_calendar:
        available = [c["name"] for c in calendars]
        raise ValueError(
            f"Calendar '{target_calendar_name}' not found in Xero. "
            f"Available: {available}"
        )

    payroll_calendar_id = matching_calendar["id"]
    logger.info(f"Using calendar '{target_calendar_name}': {payroll_calendar_id}")

    # Calculate period end (Sunday)
    week_end_date = week_start_date + timedelta(days=6)

    # Default payment date: Wednesday after period end (3 days)
    if not payment_date:
        payment_date = week_end_date + timedelta(days=3)

    logger.info(
        f"Creating pay run for period {week_start_date} to {week_end_date}, "
        f"payment date {payment_date}"
    )

    payroll_api = PayrollNzApi(api_client)

    try:
        pay_run = PayRun(
            payroll_calendar_id=payroll_calendar_id,
            period_start_date=week_start_date,
            period_end_date=week_end_date,
            payment_date=payment_date,
            pay_run_status="Draft",
            pay_run_type="Scheduled",
        )

        response = payroll_api.create_pay_run(
            xero_tenant_id=tenant_id,
            pay_run=pay_run,
        )

        if not response or not response.pay_run:
            raise Exception("Failed to create pay run")

        pay_run_id = str(response.pay_run.pay_run_id)
        logger.info(f"Successfully created pay run: {pay_run_id}")

        return {
            "pay_run_id": pay_run_id,
            "payroll_calendar_id": payroll_calendar_id,
        }

    except Exception as exc:
        logger.error(
            f"Failed to create pay run for week {week_start_date}: {exc}", exc_info=True
        )
        persist_and_raise(
            exc,
            additional_context={
                "operation": "create_pay_run",
                "week": str(week_start_date),
            },
        )


def get_payroll_calendar_id() -> str:
    """
    Get the configured payroll calendar ID from CompanyDefaults.

    The calendar ID is cached in CompanyDefaults.xero_payroll_calendar_id,
    which is populated by the xero --setup management command.

    Returns:
        Payroll calendar ID (UUID string)

    Raises:
        ValueError: If calendar ID not configured (run xero --setup first)
    """
    company = CompanyDefaults.get_solo()
    if not company.xero_payroll_calendar_id:
        raise ValueError(
            "xero_payroll_calendar_id not configured in CompanyDefaults. "
            "Run: python manage.py xero --setup"
        )
    return str(company.xero_payroll_calendar_id)


def get_all_timesheets_for_week(week_start_date: date) -> Dict[str, Any]:
    """
    Fetch all existing timesheets for a week from Xero, keyed by employee_id.

    This allows batch operations to check for existing timesheets with a single
    API call instead of one per employee.

    Args:
        week_start_date: Monday of the week

    Returns:
        Dict mapping employee_id (str) to existing Timesheet object
    """
    week_end_date = week_start_date + timedelta(days=6)
    payroll_api = PayrollNzApi(api_client)
    tenant_id = get_tenant_id()

    logger.info(
        f"Fetching all timesheets for week {week_start_date} to {week_end_date}"
    )

    response = payroll_api.get_timesheets(
        xero_tenant_id=tenant_id,
        start_date=week_start_date,
        end_date=week_end_date,
    )

    result: Dict[str, Any] = {}
    if response and response.timesheets:
        for ts in response.timesheets:
            if ts.start_date.date() == week_start_date:
                result[str(ts.employee_id)] = ts

    logger.info(f"Found {len(result)} existing timesheets for week")
    return result


def _timesheet_lines_match(
    existing_lines: List[Any], new_lines: List[Dict[str, Any]]
) -> bool:
    """
    Compare existing Xero timesheet lines with new lines to detect changes.

    Args:
        existing_lines: TimesheetLine objects from Xero
        new_lines: Dict representations of new lines to post

    Returns:
        True if the lines are equivalent (no update needed)
    """
    if len(existing_lines) != len(new_lines):
        return False

    # Build sets of (date, earnings_rate_id, rounded_units) for comparison
    # Round to 2 decimal places to avoid floating point comparison issues
    existing_set = {
        (line.date, str(line.earnings_rate_id), round(float(line.number_of_units), 2))
        for line in existing_lines
    }
    new_set = {
        (line["date"], line["earnings_rate_id"], round(line["number_of_units"], 2))
        for line in new_lines
    }
    return existing_set == new_set


def post_timesheet(
    employee_id: UUID,
    week_start_date: date,
    timesheet_lines: List[Dict[str, Any]],
    existing_timesheet: Optional[Any] = None,
) -> Timesheet:
    """
    Post a weekly timesheet to Xero Payroll following Xero's workflow:
    1. Find the payroll calendar for this week
    2. Check if timesheet exists for employee + week
    3. If exists, delete all existing lines to avoid duplicates
    4. If not exists, create fresh timesheet
    5. Add lines individually

    Args:
        employee_id: Xero employee ID (UUID)
        week_start_date: Monday of the week (date)
        timesheet_lines: List of timesheet line entries
            Each dict should contain:
            - date (date): Date for this entry
            - earnings_rate_id (str): Xero earnings rate ID
            - number_of_units (float): Hours
        existing_timesheet: Pre-fetched existing timesheet for this employee/week
            (optional - if provided, skips the per-employee API call)

    Returns:
        Timesheet object (existing or newly created)

    Raises:
        Exception: If API call fails or validation fails
    """
    # Validation
    if not get_tenant_id():
        raise Exception("No Xero tenant ID configured")

    if not employee_id:
        raise Exception("employee_id is required")

    if not week_start_date:
        raise Exception("week_start_date is required")

    if week_start_date.weekday() != 0:  # Monday = 0
        raise Exception("week_start_date must be a Monday")

    tenant_id = get_tenant_id()
    payroll_api = PayrollNzApi(api_client)

    try:
        logger.info(
            f"Processing timesheet for employee {employee_id}, week starting {week_start_date}"
        )

        # Get the payroll calendar ID from company configuration
        payroll_calendar_id = get_payroll_calendar_id()

        # Calculate week end date (Sunday)
        week_end_date = week_start_date + timedelta(days=6)

        # Step 1: Check if timesheet already exists
        # Use pre-fetched existing_timesheet if provided (batch mode)
        # Otherwise fetch per-employee (single mode - for backwards compatibility)
        if existing_timesheet is None:
            logger.info(f"Checking for existing timesheet for week {week_start_date}")
            filter_str = f"employeeId=={employee_id}"
            timesheets_response = payroll_api.get_timesheets(
                xero_tenant_id=tenant_id,
                filter=filter_str,
                start_date=week_start_date,
                end_date=week_end_date,
            )

            if timesheets_response and timesheets_response.timesheets:
                # Find timesheet matching our week
                for ts in timesheets_response.timesheets:
                    if (
                        ts.start_date.date() == week_start_date
                        and ts.end_date.date() == week_end_date
                    ):
                        existing_timesheet = ts
                        logger.info(f"Found existing timesheet: {ts.timesheet_id}")
                        break
        elif existing_timesheet:
            logger.info(
                f"Using pre-fetched existing timesheet: {existing_timesheet.timesheet_id}"
            )

        # Check if existing timesheet already matches what we want to post
        if existing_timesheet and existing_timesheet.timesheet_lines:
            if _timesheet_lines_match(
                existing_timesheet.timesheet_lines, timesheet_lines
            ):
                logger.info(
                    f"Timesheet {existing_timesheet.timesheet_id} unchanged, skipping update"
                )
                return existing_timesheet

        # Step 2: If timesheet exists, delete it entirely (faster than deleting lines one-by-one)
        if existing_timesheet:
            timesheet_id = existing_timesheet.timesheet_id

            # If timesheet is Approved, revert to Draft first so we can delete it
            if existing_timesheet.status == "Approved":
                logger.info(f"Reverting approved timesheet {timesheet_id} to Draft")
                payroll_api.revert_timesheet(
                    xero_tenant_id=tenant_id,
                    timesheet_id=str(timesheet_id),
                )
                logger.info(f"Successfully reverted timesheet {timesheet_id} to Draft")
                time.sleep(SLEEP_TIME)
            elif existing_timesheet.status != "Draft":
                # Status is something other than Draft or Approved (e.g., Paid)
                raise Exception(
                    f"Timesheet {timesheet_id} is in '{existing_timesheet.status}' status "
                    "and cannot be modified. This timesheet has already been paid."
                )

            logger.info(f"Deleting existing timesheet {timesheet_id}")
            payroll_api.delete_timesheet(
                xero_tenant_id=tenant_id,
                timesheet_id=str(timesheet_id),
            )
            logger.info(f"Successfully deleted timesheet {timesheet_id}")
            time.sleep(SLEEP_TIME)

        # Step 3: Create timesheet with all lines in a single API call
        lines = [
            TimesheetLine(
                date=line_data["date"],
                earnings_rate_id=line_data["earnings_rate_id"],
                number_of_units=line_data["number_of_units"],
            )
            for line_data in timesheet_lines
        ]

        logger.info(f"Creating timesheet with {len(lines)} lines")
        new_timesheet = Timesheet(
            employee_id=str(employee_id),
            payroll_calendar_id=payroll_calendar_id,
            start_date=week_start_date,
            end_date=week_end_date,
            timesheet_lines=lines,
        )

        create_response = payroll_api.create_timesheet(
            xero_tenant_id=tenant_id,
            timesheet=new_timesheet,
        )
        time.sleep(SLEEP_TIME)

        if not create_response or not create_response.timesheet:
            raise Exception("Failed to create timesheet")

        created_timesheet = create_response.timesheet
        timesheet_id = created_timesheet.timesheet_id

        logger.info(
            f"Successfully created timesheet {timesheet_id} with {len(lines)} lines"
        )

        # Step 4: Approve the timesheet immediately
        logger.info(f"Approving timesheet {timesheet_id}")
        payroll_api.approve_timesheet(
            xero_tenant_id=tenant_id,
            timesheet_id=str(timesheet_id),
        )
        logger.info(f"Successfully approved timesheet {timesheet_id}")
        time.sleep(SLEEP_TIME)

        return created_timesheet

    except Exception as exc:
        logger.error(
            f"Failed to post timesheet for employee {employee_id}: {exc}",
            exc_info=True,
        )
        persist_and_raise(
            exc,
            additional_context={
                "operation": "post_timesheet",
                "employee_id": str(employee_id),
                "week_start_date": week_start_date.isoformat(),
            },
        )


def create_employee_leave(
    employee_id: UUID,
    leave_type_id: str,
    start_date: date,
    end_date: date,
    hours_per_day: float,
    description: str = "",
) -> str:
    """
    Create an employee leave record in Xero Payroll.

    Args:
        employee_id: Xero employee ID (UUID)
        leave_type_id: Xero leave type ID (str UUID)
        start_date: First day of leave
        end_date: Last day of leave (inclusive)
        hours_per_day: Hours per day for this leave
        description: Optional description of the leave

    Returns:
        Leave ID (UUID string) from Xero

    Raises:
        Exception: If API call fails or validation fails
    """
    if not get_tenant_id():
        raise Exception("No Xero tenant ID configured")

    if not employee_id:
        raise Exception("employee_id is required")

    if not leave_type_id:
        raise Exception("leave_type_id is required")

    if not start_date or not end_date:
        raise Exception("start_date and end_date are required")

    if end_date < start_date:
        raise Exception("end_date cannot be before start_date")

    tenant_id = get_tenant_id()
    payroll_api = PayrollNzApi(api_client)

    try:
        logger.info(
            f"Creating leave for employee {employee_id}: "
            f"{start_date} to {end_date} ({hours_per_day}h/day)"
        )

        # Build leave periods for each day
        from xero_python.payrollnz.models import EmployeeLeave, LeavePeriod

        periods = []
        current_date = start_date
        while current_date <= end_date:
            # Skip weekends (Xero will handle this based on employee's schedule)
            periods.append(
                LeavePeriod(
                    period_start_date=current_date,
                    period_end_date=current_date,
                    number_of_units=hours_per_day,
                    period_status="Approved",  # Auto-approve for our use case
                )
            )
            current_date += timedelta(days=1)

        employee_leave = EmployeeLeave(
            leave_type_id=leave_type_id,
            description=description or f"Leave from {start_date} to {end_date}",
            start_date=start_date,
            end_date=end_date,
            periods=periods,
        )

        response = payroll_api.create_employee_leave(
            xero_tenant_id=tenant_id,
            employee_id=str(employee_id),
            employee_leave=employee_leave,
        )

        if not response or not response.leave:
            raise Exception("Failed to create employee leave")

        leave_id = response.leave.leave_id
        logger.info(f"Successfully created leave record: {leave_id}")

        return str(leave_id)

    except Exception as exc:
        logger.error(
            f"Failed to create leave for employee {employee_id}: {exc}",
            exc_info=True,
        )
        persist_and_raise(
            exc,
            additional_context={
                "operation": "create_employee_leave",
                "employee_id": str(employee_id),
                "leave_type_id": leave_type_id,
            },
        )


# =============================================================================
# Sync-focused API functions
# These return raw Xero objects for use by the sync system
# =============================================================================


def get_pay_runs_for_sync(**kwargs):
    """
    Fetch pay runs from Xero Payroll API for sync purposes.

    Returns raw PayRun objects (not converted to dicts) so they can be
    serialized to raw_json by the sync system.

    Returns:
        Object with .pay_runs attribute containing list of PayRun objects
    """
    tenant_id = kwargs.get("xero_tenant_id") or get_tenant_id()
    if not tenant_id:
        raise ValueError("No Xero tenant ID configured for payroll sync")

    payroll_api = PayrollNzApi(api_client)

    logger.info("Fetching Xero pay runs for sync")
    response = payroll_api.get_pay_runs(xero_tenant_id=tenant_id)

    if response and response.pay_runs:
        logger.info(f"Retrieved {len(response.pay_runs)} pay runs for sync")
        return response
    return type("obj", (object,), {"pay_runs": []})()


def get_pay_slips_for_sync(pay_run_id: str, **kwargs):
    """
    Fetch pay slips for a specific pay run from Xero Payroll API.

    Returns raw PaySlip objects (not converted to dicts) so they can be
    serialized to raw_json by the sync system.

    Args:
        pay_run_id: The Xero pay run ID to fetch slips for

    Returns:
        Object with .pay_slips attribute containing list of PaySlip objects
    """
    tenant_id = kwargs.get("xero_tenant_id") or get_tenant_id()
    if not tenant_id:
        raise ValueError("No Xero tenant ID configured for payroll sync")

    payroll_api = PayrollNzApi(api_client)

    logger.debug(f"Fetching pay slips for pay run {pay_run_id}")
    response = payroll_api.get_pay_slips(
        xero_tenant_id=tenant_id, pay_run_id=pay_run_id
    )

    if response and response.pay_slips:
        logger.debug(f"Retrieved {len(response.pay_slips)} pay slips")
        return response
    return type("obj", (object,), {"pay_slips": []})()


def get_all_pay_slips_for_sync(**kwargs):
    """
    Fetch ALL pay slips across ALL pay runs from Xero Payroll API.

    This iterates through all pay runs and fetches their pay slips.
    Note: This makes N+1 API calls (1 for pay runs, N for each pay run's slips).

    Returns:
        Object with .pay_slips attribute containing list of all PaySlip objects
    """
    tenant_id = kwargs.get("xero_tenant_id") or get_tenant_id()
    if not tenant_id:
        raise ValueError("No Xero tenant ID configured for payroll sync")

    payroll_api = PayrollNzApi(api_client)

    # First get all pay runs
    logger.info("Fetching all pay runs to gather pay slips")
    pay_runs_response = payroll_api.get_pay_runs(xero_tenant_id=tenant_id)

    if not pay_runs_response or not pay_runs_response.pay_runs:
        logger.info("No pay runs found")
        return type("obj", (object,), {"pay_slips": []})()

    all_pay_slips = []
    for pay_run in pay_runs_response.pay_runs:
        pay_run_id = str(pay_run.pay_run_id)
        logger.debug(f"Fetching pay slips for pay run {pay_run_id}")

        slips_response = payroll_api.get_pay_slips(
            xero_tenant_id=tenant_id, pay_run_id=pay_run_id
        )
        if slips_response and slips_response.pay_slips:
            # Add pay_run reference to each slip for context
            for slip in slips_response.pay_slips:
                slip._pay_run = pay_run  # Attach parent for transform
            all_pay_slips.extend(slips_response.pay_slips)

    logger.info(f"Retrieved {len(all_pay_slips)} total pay slips for sync")
    return type("obj", (object,), {"pay_slips": all_pay_slips})()


def validate_pay_items_for_week(
    staff_ids: List[UUID],
    week_start_date: date,
) -> None:
    """
    Validate ALL required XeroPayItems exist for ALL staff entries BEFORE posting.

    This is fail-early validation: we check everything upfront so we don't make
    partial API calls and leave data in an inconsistent state.

    Args:
        staff_ids: List of staff UUIDs to validate
        week_start_date: Monday of the week

    Raises:
        ValueError: If any required pay items are missing
    """
    from apps.job.models.costing import CostLine

    week_end_date = week_start_date + timedelta(days=6)

    # Collect ALL time entries for ALL staff in this week
    all_entries = CostLine.objects.filter(
        kind="time",
        accounting_date__gte=week_start_date,
        accounting_date__lte=week_end_date,
    ).select_related("cost_set__job", "cost_set__job__default_xero_pay_item")

    # Filter to only the staff we're posting
    staff_id_strs = {str(sid) for sid in staff_ids}
    entries = [e for e in all_entries if e.meta.get("staff_id") in staff_id_strs]

    if not entries:
        return  # No entries to validate

    # Validate all entries have xero_pay_item with valid xero_id
    missing_pay_items = []

    for entry in entries:
        pay_item = entry.xero_pay_item

        if pay_item is None:
            missing_pay_items.append(f"CostLine {entry.id} has no xero_pay_item")
        elif not pay_item.xero_id:
            missing_pay_items.append(
                f"CostLine {entry.id} has XeroPayItem '{pay_item.name}' with no xero_id"
            )

    if missing_pay_items:
        raise ValueError(
            "Missing XeroPayItems - run sync_xero_pay_items() first:\n"
            + "\n".join(f"  - {msg}" for msg in missing_pay_items)
        )

    logger.info(
        f"Validated pay items for {len(entries)} entries across {len(staff_ids)} staff"
    )


def post_staff_week_to_xero(
    staff_id: UUID,
    week_start_date: date,
    existing_timesheet: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Post a week's timesheet to Xero Payroll for a specific staff member.

    Args:
        staff_id: UUID of the staff member
        week_start_date: Monday of the week to post (must be a Monday)
        existing_timesheet: Pre-fetched existing timesheet from Xero (optional)
            If provided, skips the per-employee API call to check for existing

    Returns:
        Dict containing:
            - success (bool): Whether the post was successful
            - xero_timesheet_id (str): Xero timesheet ID if successful
            - entries_posted (int): Number of entries posted
            - work_hours (Decimal): Total work hours
            - other_leave_hours (Decimal): Total other leave hours (timesheets API)
            - leave_hours (Decimal): Total leave hours (leave API - annual/sick/unpaid)
            - errors (List[str]): Any errors encountered

    Raises:
        ValueError: If inputs are invalid
        AlreadyLoggedException: If Xero API call fails
    """
    from apps.accounts.models import Staff
    from apps.job.models.costing import CostLine

    # Validate inputs
    if week_start_date.weekday() != 0:
        raise ValueError("week_start_date must be a Monday")

    try:
        staff = Staff.objects.get(id=staff_id)
    except Staff.DoesNotExist as exc:
        raise ValueError("Staff member not found") from exc

    if not staff.xero_user_id:
        raise ValueError(
            f"Staff member {staff.email} does not have a xero_user_id configured"
        )

    # PHASE 1: Validate XeroPayItem data is synced
    ordinary_time = XeroPayItem.get_ordinary_time()
    if not ordinary_time:
        raise ValueError(
            "XeroPayItem 'Ordinary Time' (multiplier=1.0) not found. "
            "Run sync_xero_pay_items() to sync pay items from Xero."
        )
    logger.info("XeroPayItem data validated")

    try:
        # Calculate week end date (Sunday)
        week_end_date = week_start_date + timedelta(days=6)

        logger.info(
            f"Collecting timesheet entries for {staff.email} "
            f"from {week_start_date} to {week_end_date}"
        )

        # Collect time entries for the week
        time_entries = CostLine.objects.filter(
            kind="time",
            accounting_date__gte=week_start_date,
            accounting_date__lte=week_end_date,
        ).select_related("cost_set__job")

        # Filter to entries for this staff
        staff_entries = [
            entry
            for entry in time_entries
            if entry.meta.get("staff_id") == str(staff_id)
        ]

        if not staff_entries:
            # Post empty timesheet to override Xero's Pay Template default (40 hrs)
            # Xero rejects 0-unit lines but accepts empty timesheets
            logger.info(
                f"No timesheet entries for {staff.email} in week {week_start_date} "
                f"- posting empty timesheet"
            )
            xero_timesheet = post_timesheet(
                employee_id=staff.xero_user_id,
                week_start_date=week_start_date,
                timesheet_lines=[],
                existing_timesheet=existing_timesheet,
            )
            return {
                "success": True,
                "xero_timesheet_id": str(xero_timesheet.timesheet_id),
                "entries_posted": 0,
                "work_hours": Decimal("0"),
                "other_leave_hours": Decimal("0"),
                "leave_hours": Decimal("0"),
                "errors": [],
            }

        # Categorize entries into two buckets
        leave_api_entries, timesheet_entries = _categorize_entries(staff_entries)

        # Further split timesheet entries into work vs other leave (for reporting)
        work_entries = []
        other_leave_entries = []
        for entry in timesheet_entries:
            pay_item = entry.xero_pay_item
            # Work entries have multipliers (1.0, 1.5, 2.0), leave entries don't
            if pay_item and pay_item.multiplier is not None:
                work_entries.append(entry)
            else:
                other_leave_entries.append(entry)

        xero_employee_id = UUID(staff.xero_user_id)
        xero_timesheet_id = None
        leave_ids = []

        # Post timesheet entries (work + other leave)
        if timesheet_entries:
            timesheet_lines = _map_work_entries(timesheet_entries)
            logger.info(f"Posting {len(timesheet_lines)} timesheet entries to Xero")

            timesheet = post_timesheet(
                employee_id=xero_employee_id,
                week_start_date=week_start_date,
                timesheet_lines=timesheet_lines,
                existing_timesheet=existing_timesheet,
            )
            xero_timesheet_id = str(timesheet.timesheet_id)
            logger.info(f"Successfully posted timesheet {xero_timesheet_id}")

        # Post leave entries using Leave API (annual/sick only)
        if leave_api_entries:
            leave_ids = _post_leave_entries(xero_employee_id, leave_api_entries)
            logger.info(f"Successfully posted {len(leave_ids)} leave records")

        # Calculate hours by all four categories
        work_hours = sum(Decimal(str(entry.quantity)) for entry in work_entries)
        other_leave_hours = sum(
            Decimal(str(entry.quantity)) for entry in other_leave_entries
        )
        leave_hours = sum(Decimal(str(entry.quantity)) for entry in leave_api_entries)

        return {
            "success": True,
            "xero_timesheet_id": xero_timesheet_id,
            "xero_leave_ids": leave_ids,
            "entries_posted": len(staff_entries),
            "work_hours": work_hours,
            "other_leave_hours": other_leave_hours,
            "leave_hours": leave_hours,
            "errors": [],
        }

    except AlreadyLoggedException:
        raise
    except Exception as exc:
        logger.error(
            f"Failed to post timesheet for staff {staff_id}: {exc}", exc_info=True
        )
        app_error = persist_app_error(
            exc,
            additional_context={
                "staff_id": str(staff_id),
                "week_start_date": week_start_date.isoformat(),
            },
        )
        raise AlreadyLoggedException(exc, app_error.id)


def _categorize_entries(entries: List) -> tuple:
    """
    Categorize cost line entries for Xero posting.

    Uses entry.xero_pay_item to determine how each entry should be posted.

    Args:
        entries: List of CostLine entries to categorize

    Returns:
        Tuple of (leave_api_entries, timesheet_entries)
        - leave_api_entries: Entries using Leave API (annual, sick, unpaid leave)
        - timesheet_entries: Entries using Timesheets API (work + other leave)
    """
    leave_api_entries = []  # Leave API entries
    timesheet_entries = []  # Timesheets API entries

    for entry in entries:
        pay_item = entry.xero_pay_item

        if pay_item is None:
            raise ValueError(f"CostLine {entry.id} has no xero_pay_item")

        if pay_item.uses_leave_api:
            # Uses Leave API (e.g., annual, sick, unpaid)
            leave_api_entries.append(entry)
        else:
            # Uses Timesheets API (work or other leave)
            timesheet_entries.append(entry)

    return leave_api_entries, timesheet_entries


def _map_work_entries(entries: List) -> List[Dict[str, Any]]:
    """
    Map CostLine entries to Xero Payroll timesheet lines format.

    Aggregates entries by date and pay item - if multiple entries exist
    for the same date and xero_pay_item, they are rolled up into a single
    timesheet line with summed hours.

    Args:
        entries: List of CostLine entries (uses Timesheets API)

    Returns:
        List of timesheet line dictionaries for Xero API
    """
    # Group entries by (date, xero_pay_item.xero_id) and sum quantities
    aggregated: Dict[tuple, float] = defaultdict(float)

    for entry in entries:
        pay_item = entry.xero_pay_item

        if pay_item is None:
            raise ValueError(f"CostLine {entry.id} has no xero_pay_item")

        key = (entry.accounting_date, pay_item.xero_id)
        aggregated[key] += float(entry.quantity)

    # Build timesheet lines from aggregated data
    timesheet_lines = []
    for (entry_date, earnings_rate_id), quantity in aggregated.items():
        timesheet_lines.append(
            {
                "date": entry_date,
                "earnings_rate_id": earnings_rate_id,
                "number_of_units": quantity,
            }
        )

    return timesheet_lines


def _post_leave_entries(
    employee_id: UUID,
    entries: List,
) -> List[str]:
    """
    Post leave CostLine entries to Xero using the Leave API.

    Groups consecutive days of the same leave type together.
    Uses entry.xero_pay_item to get Xero leave type IDs.

    Args:
        employee_id: Xero employee ID
        entries: List of leave CostLine entries

    Returns:
        List of leave IDs created in Xero
    """
    # Group entries by XeroPayItem and sort by date
    grouped = defaultdict(list)
    for entry in entries:
        pay_item = entry.xero_pay_item

        if pay_item is None:
            raise ValueError(f"CostLine {entry.id} has no xero_pay_item set")

        grouped[pay_item].append(entry)

    # Sort each group by date
    for pay_item in grouped:
        grouped[pay_item].sort(key=lambda e: e.accounting_date)

    leave_ids = []

    # Process each leave type
    for pay_item, type_entries in grouped.items():
        # Use xero_id directly from XeroPayItem
        leave_type_id = pay_item.xero_id

        # Group consecutive days together
        if not type_entries:
            continue

        current_start = type_entries[0].accounting_date
        current_end = type_entries[0].accounting_date
        current_hours = float(type_entries[0].quantity)

        for i in range(1, len(type_entries)):
            entry = type_entries[i]
            expected_next = current_end + timedelta(days=1)

            # Check if consecutive and same hours per day
            if (
                entry.accounting_date == expected_next
                and abs(float(entry.quantity) - current_hours) < 0.01
            ):
                # Extend current range
                current_end = entry.accounting_date
            else:
                # Create leave for current range
                leave_id = create_employee_leave(
                    employee_id=employee_id,
                    leave_type_id=leave_type_id,
                    start_date=current_start,
                    end_date=current_end,
                    hours_per_day=current_hours,
                    description=pay_item.name,
                )
                leave_ids.append(leave_id)

                # Start new range
                current_start = entry.accounting_date
                current_end = entry.accounting_date
                current_hours = float(entry.quantity)

        # Create leave for final range
        leave_id = create_employee_leave(
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date=current_start,
            end_date=current_end,
            hours_per_day=current_hours,
            description=pay_item.name,
        )
        leave_ids.append(leave_id)

    return leave_ids


def sync_xero_pay_items() -> Dict[str, Any]:
    """
    Sync XeroPayItem from Xero Leave Types and Earnings Rates.

    This creates/updates XeroPayItem records from Xero's:
    - Leave Types (uses_leave_api=True)
    - Earnings Rates (uses_leave_api=False)

    Returns:
        Dict with sync results: created, updated counts

    Raises:
        ValueError: If no Xero tenant ID configured
        Exception: If Xero API calls fail
    """
    from django.utils import timezone

    from apps.workflow.models import XeroPayItem

    # Fail early: check tenant ID
    tenant_id = get_tenant_id()
    if not tenant_id:
        raise ValueError("No Xero tenant ID configured")

    results = {
        "leave_types": {"created": 0, "updated": 0},
        "earnings_rates": {"created": 0, "updated": 0},
    }

    # Fetch all data upfront - fail fast if API errors
    logger.info("Fetching Xero Leave Types and Earnings Rates")
    leave_types = get_leave_types()
    earnings_rates = get_earnings_rates()

    # Sync Leave Types
    logger.info(f"Syncing {len(leave_types)} leave types to XeroPayItem")
    for lt in leave_types:
        # Infer multiplier from leave type name: unpaid/annual leave → 0, others → 1
        name_lower = lt["name"].lower()
        if "unpaid" in name_lower:  # Unpaid is 0 because we don't have to pay them!
            leave_multiplier = Decimal("0.00")
        elif (
            "annual" in name_lower
        ):  # Annual is 0 because we use accrual so we've already set aside money
            leave_multiplier = Decimal("0.00")
        else:
            leave_multiplier = Decimal("1.00")

        pay_item, created = XeroPayItem.objects.update_or_create(
            name=lt["name"],
            uses_leave_api=True,
            defaults={
                "xero_id": str(lt["id"]),
                "xero_tenant_id": tenant_id,
                "multiplier": leave_multiplier,
                "xero_last_synced": timezone.now(),
            },
        )
        if created:
            results["leave_types"]["created"] += 1
            logger.info(f"Created XeroPayItem: {lt['name']} (leave type)")
        else:
            results["leave_types"]["updated"] += 1

    # Sync Earnings Rates
    logger.info(f"Syncing {len(earnings_rates)} earnings rates to XeroPayItem")
    for rate in earnings_rates:
        multiplier = rate.get("multiplier")
        if multiplier is not None:
            multiplier = Decimal(str(multiplier))

        pay_item, created = XeroPayItem.objects.update_or_create(
            name=rate["name"],
            uses_leave_api=False,
            defaults={
                "xero_id": str(rate["id"]),
                "xero_tenant_id": tenant_id,
                "multiplier": multiplier,
                "xero_last_synced": timezone.now(),
            },
        )
        if created:
            results["earnings_rates"]["created"] += 1
            logger.info(
                f"Created XeroPayItem: {rate['name']} (multiplier={multiplier})"
            )
        else:
            results["earnings_rates"]["updated"] += 1

    logger.info(
        f"XeroPayItem sync complete: "
        f"{results['leave_types']['created']} leave types created, "
        f"{results['leave_types']['updated']} updated. "
        f"{results['earnings_rates']['created']} earnings rates created, "
        f"{results['earnings_rates']['updated']} updated."
    )

    return results
