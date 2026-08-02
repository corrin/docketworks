#!/usr/bin/env python
"""KAN-326 verifier: empirically pin two undocumented Xero NZ Payroll contracts
against the dev demo tenant, BEFORE the leave-reconciliation fix is built.

Contract 1: is update_employee_leave (PUT) permitted while the employee is in a
            draft pay run? (Xero documents the block only for DELETE.)
Contract 2: does create_employee_leave accept explicit non-uniform per-day
            periods (8/8/8/4.5), and what shape does Xero echo back?

Run:      .venv/bin/python scripts/verify_kan326_leave_contracts.py
Cleanup:  .venv/bin/python scripts/verify_kan326_leave_contracts.py --cleanup <leave_id>
          (only AFTER deleting the draft pay run in the Xero UI - see checklist
          the main run prints)

DESTRUCTIVE to the demo tenant: creates a leave record and a draft pay run.
The draft pay run can only be deleted in the Xero UI and blocks all dev
payroll posting on the calendar until it is removed.

Temporary tooling - delete before the KAN-326 PR merges (outputs recorded in
the PR and Jira).
"""

import argparse
import os
import sys
import time
from datetime import timedelta

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
django.setup()

from xero_python.exceptions import ApiException
from xero_python.payrollnz import PayrollNzApi
from xero_python.payrollnz.models import EmployeeLeave, LeavePeriod

from apps.accounts.models import Staff
from apps.workflow.api.xero.auth import api_client
from apps.workflow.api.xero.payroll import (
    ensure_pay_run_for_week,
    get_tenant_id,
    next_postable_payroll_week,
)
from apps.workflow.models import XeroPayItem

PAUSE = 1.5  # be gentle with the daily API quota


def show(label: str, obj: object) -> None:
    print(f"\n=== {label} ===")
    print(obj)


def show_leave(leave: EmployeeLeave) -> None:
    print(
        f"leave_id={leave.leave_id} type={leave.leave_type_id} "
        f"start={leave.start_date} end={leave.end_date} desc={leave.description!r}"
    )
    for p in leave.periods or []:
        print(
            f"  period {p.period_start_date} -> {p.period_end_date} "
            f"units={p.number_of_units} units_taken={p.number_of_units_taken} "
            f"status={p.period_status}"
        )


def api_error_body(exc: ApiException) -> str:
    return f"status={exc.status} reason={exc.reason} body={exc.body}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup", metavar="LEAVE_ID")
    parser.add_argument("--employee-name", default="Jack Allen")
    parser.add_argument(
        "--probe-single-period",
        metavar="LEAVE_ID",
        help="Follow-up probe: update the given leave with ONE pay-period-wide "
        "period carrying custom total units (28.5), while the draft pay run "
        "still exists. Tests both update-during-draft and custom-units.",
    )
    parser.add_argument(
        "--probe-create-single",
        action="store_true",
        help="Follow-up probe on a DRAFT-FREE week: does create honor custom "
        "units in a single lumped period? Can update change the date span? "
        "Cleans up after itself (delete works with no draft).",
    )
    args = parser.parse_args()

    tenant_id = get_tenant_id()
    if not tenant_id:
        raise SystemExit("No Xero tenant ID configured")
    payroll_api = PayrollNzApi(api_client)

    staff = Staff.objects.filter(
        first_name=args.employee_name.split()[0],
        last_name=args.employee_name.split()[1],
    ).first()
    if staff is None or not staff.xero_user_id:
        raise SystemExit(f"Staff {args.employee_name!r} with xero_user_id not found")
    employee_id = str(staff.xero_user_id)
    print(f"Employee: {args.employee_name} ({employee_id})")

    if args.cleanup:
        show("CLEANUP: deleting test leave", args.cleanup)
        resp = payroll_api.delete_employee_leave(
            xero_tenant_id=tenant_id, employee_id=employee_id, leave_id=args.cleanup
        )
        print(f"delete response: {resp}")
        return

    if args.probe_single_period:
        sick_item = XeroPayItem.objects.get(name="Sick Leave", uses_leave_api=True)
        week_pair = next_postable_payroll_week()
        if week_pair is None:
            raise SystemExit("No postable payroll week")
        mon, sun = week_pair
        single = EmployeeLeave(
            leave_type_id=str(sick_item.xero_id),
            description="KAN-326 verifier: single-period custom units",
            start_date=mon,
            end_date=mon + timedelta(days=3),
            periods=[
                LeavePeriod(
                    period_start_date=mon,
                    period_end_date=sun,
                    number_of_units=28.5,
                    period_status="Approved",
                )
            ],
        )
        try:
            resp = payroll_api.update_employee_leave(
                xero_tenant_id=tenant_id,
                employee_id=employee_id,
                leave_id=args.probe_single_period,
                employee_leave=single,
            )
            show("PROBE: single-period update SUCCEEDED during draft", "")
            show_leave(resp.leave)
        except ApiException as exc:
            show("PROBE: single-period update REJECTED during draft", "")
            print(api_error_body(exc))
        time.sleep(PAUSE)
        echo = payroll_api.get_employee_leaves(
            xero_tenant_id=tenant_id, employee_id=employee_id
        )
        ours = [
            lv
            for lv in (echo.leave or [])
            if str(lv.leave_id) == args.probe_single_period
        ]
        show("PROBE: echo after single-period update", "")
        if ours:
            show_leave(ours[0])
        else:
            print("leave not found in echo")
        return

    if args.probe_create_single:
        annual = XeroPayItem.objects.get(name="Annual Leave", uses_leave_api=True)
        week_pair = next_postable_payroll_week()
        if week_pair is None:
            raise SystemExit("No postable payroll week")
        # One week AFTER the draft week: no draft pay run covers it.
        mon = week_pair[0] + timedelta(days=7)
        sun = mon + timedelta(days=6)
        lumped = EmployeeLeave(
            leave_type_id=str(annual.xero_id),
            description="KAN-326 verifier: create single lumped period",
            start_date=mon,
            end_date=mon + timedelta(days=2),
            periods=[
                LeavePeriod(
                    period_start_date=mon,
                    period_end_date=sun,
                    number_of_units=10.5,
                    period_status="Approved",
                )
            ],
        )
        try:
            resp = payroll_api.create_employee_leave(
                xero_tenant_id=tenant_id,
                employee_id=employee_id,
                employee_leave=lumped,
            )
            show("PROBE: create with single lumped period (10.5 units) response", "")
            show_leave(resp.leave)
        except ApiException as exc:
            show("PROBE: create with single lumped period REJECTED", "")
            print(api_error_body(exc))
            return
        probe_leave_id = str(resp.leave.leave_id)
        time.sleep(PAUSE)

        respan = EmployeeLeave(
            leave_type_id=str(annual.xero_id),
            description="KAN-326 verifier: respan +1 day",
            start_date=mon,
            end_date=mon + timedelta(days=3),
            periods=[
                LeavePeriod(
                    period_start_date=mon,
                    period_end_date=sun,
                    number_of_units=14.0,
                    period_status="Approved",
                )
            ],
        )
        try:
            resp2 = payroll_api.update_employee_leave(
                xero_tenant_id=tenant_id,
                employee_id=employee_id,
                leave_id=probe_leave_id,
                employee_leave=respan,
            )
            show("PROBE: update changing date span SUCCEEDED", "")
            show_leave(resp2.leave)
        except ApiException as exc:
            show("PROBE: update changing date span REJECTED", "")
            print(api_error_body(exc))
        time.sleep(PAUSE)

        try:
            payroll_api.delete_employee_leave(
                xero_tenant_id=tenant_id,
                employee_id=employee_id,
                leave_id=probe_leave_id,
            )
            show("PROBE: cleanup delete succeeded (no draft covers that week)", "")
        except ApiException as exc:
            show(
                "PROBE: cleanup delete FAILED - manual cleanup needed for "
                f"leave {probe_leave_id}",
                "",
            )
            print(api_error_body(exc))
        return

    sick = XeroPayItem.objects.get(name="Sick Leave", uses_leave_api=True)
    week = next_postable_payroll_week()
    if week is None:
        raise SystemExit("No postable payroll week (calendar not configured?)")
    monday, _sunday = week
    print(f"Target week: {monday} (next postable on the configured calendar)")

    # --- Contract 2: create with non-uniform per-day periods -----------------
    days_units = [
        (monday, 8.0),
        (monday + timedelta(days=1), 8.0),
        (monday + timedelta(days=2), 8.0),
        (monday + timedelta(days=3), 4.5),
    ]
    periods = [
        LeavePeriod(
            period_start_date=d,
            period_end_date=d,
            number_of_units=units,
            period_status="Approved",
        )
        for d, units in days_units
    ]
    employee_leave = EmployeeLeave(
        leave_type_id=str(sick.xero_id),
        description="KAN-326 contract verifier (safe to delete)",
        start_date=days_units[0][0],
        end_date=days_units[-1][0],
        periods=periods,
    )
    try:
        resp = payroll_api.create_employee_leave(
            xero_tenant_id=tenant_id,
            employee_id=employee_id,
            employee_leave=employee_leave,
        )
    except ApiException as exc:
        show("CONTRACT 2 FAIL: create rejected non-uniform per-day periods", "")
        print(api_error_body(exc))
        raise SystemExit(1)
    leave_id = str(resp.leave.leave_id)
    show("CONTRACT 2: create accepted; immediate response", "")
    show_leave(resp.leave)
    time.sleep(PAUSE)

    echo = payroll_api.get_employee_leaves(
        xero_tenant_id=tenant_id, employee_id=employee_id
    )
    ours = [lv for lv in (echo.leave or []) if str(lv.leave_id) == leave_id]
    show("CONTRACT 2: echo from get_employee_leaves", "")
    if ours:
        show_leave(ours[0])
    else:
        print(f"leave {leave_id} NOT found in echo of {len(echo.leave or [])} leaves")
    time.sleep(PAUSE)

    # --- Draft pay run covering the employee --------------------------------
    show("Creating draft pay run via ensure_pay_run_for_week", monday)
    pay_run = ensure_pay_run_for_week(monday)
    pay_run_id = pay_run["pay_run_id"]
    print(f"draft pay run: {pay_run_id} status={pay_run['pay_run_status']}")
    time.sleep(PAUSE)

    slips = payroll_api.get_pay_slips(xero_tenant_id=tenant_id, pay_run_id=pay_run_id)
    in_draft = any(str(s.employee_id) == employee_id for s in (slips.pay_slips or []))
    show(
        "Employee included in draft pay run (block precondition)",
        f"{in_draft} ({len(slips.pay_slips or [])} slips total)",
    )
    if not in_draft:
        print(
            "WARNING: employee not in draft - block results below are NOT "
            "interpretable; fix the calendar assignment and re-run."
        )
    time.sleep(PAUSE)

    # --- Contract 1a: update while draft exists -----------------------------
    updated_units = [
        (monday, 8.0),
        (monday + timedelta(days=1), 8.0),
        (monday + timedelta(days=2), 4.5),
        (monday + timedelta(days=3), 4.5),
    ]
    updated = EmployeeLeave(
        leave_type_id=str(sick.xero_id),
        description="KAN-326 contract verifier UPDATED (safe to delete)",
        start_date=updated_units[0][0],
        end_date=updated_units[-1][0],
        periods=[
            LeavePeriod(
                period_start_date=d,
                period_end_date=d,
                number_of_units=units,
                period_status="Approved",
            )
            for d, units in updated_units
        ],
    )
    try:
        upd_resp = payroll_api.update_employee_leave(
            xero_tenant_id=tenant_id,
            employee_id=employee_id,
            leave_id=leave_id,
            employee_leave=updated,
        )
        show("CONTRACT 1a: update_employee_leave SUCCEEDED during draft", "")
        show_leave(upd_resp.leave)
    except ApiException as exc:
        show("CONTRACT 1a: update_employee_leave REJECTED during draft", "")
        print(api_error_body(exc))
    time.sleep(PAUSE)

    # --- Contract 1b: delete while draft exists (expect block) --------------
    try:
        payroll_api.delete_employee_leave(
            xero_tenant_id=tenant_id, employee_id=employee_id, leave_id=leave_id
        )
        show(
            "CONTRACT 1b: delete_employee_leave SUCCEEDED during draft "
            "(unexpected - no block!)",
            "",
        )
        print("Test leave already deleted; skip --cleanup for the leave.")
    except ApiException as exc:
        show("CONTRACT 1b: delete_employee_leave blocked (capture string)", "")
        print(api_error_body(exc))
    time.sleep(PAUSE)

    echo2 = payroll_api.get_employee_leaves(
        xero_tenant_id=tenant_id, employee_id=employee_id
    )
    ours2 = [lv for lv in (echo2.leave or []) if str(lv.leave_id) == leave_id]
    show("Final echo of test leave", "")
    if ours2:
        show_leave(ours2[0])
    else:
        print("test leave no longer present in Xero")

    show("CLEANUP CHECKLIST", "")
    print(
        f"1. In demo-tenant Xero UI: Payroll -> Pay runs -> delete the DRAFT pay "
        f"run for week {monday} (id {pay_run_id}). It blocks all dev payroll "
        f"posting until removed. API deletion is impossible.\n"
        f"2. Run Xero sync (or delete the local XeroPayRun mirror row for "
        f"{pay_run_id}) so the mirror matches.\n"
        f"3. Re-run this script with --cleanup {leave_id} to delete the test "
        f"leave (only works once the draft pay run is gone)."
    )


if __name__ == "__main__":
    main()
