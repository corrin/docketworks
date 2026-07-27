"""Finalise a freshly created instance after its Xero OAuth connection exists."""

from django.core.management import call_command

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.timesheet.services import PayrollEmployeeSyncService
from apps.workflow.api.xero.auth import get_valid_token
from apps.workflow.api.xero.payroll import sync_xero_pay_items
from apps.workflow.api.xero.sync import one_way_sync_all_xero_data
from apps.workflow.models import CompanyDefaults, XeroAccount

CANONICAL_SHOP_JOB_NAMES = (
    "Annual Leave",
    "Bench - busy work",
    "Bereavement Leave",
    "Business Development",
    "Office Admin",
    "Sick Leave",
    "Training",
    "Travel",
    "Worker Admin",
)


def _sync_accounts() -> None:
    errors = [
        event.get("message", "Unknown account sync error")
        for event in one_way_sync_all_xero_data(entities=["accounts"], force=True)
        if event.get("severity") == "error"
    ]
    if errors:
        raise RuntimeError("Xero account sync failed: " + "; ".join(errors))
    if not XeroAccount.objects.exists():
        raise RuntimeError(
            "Xero account sync completed without importing any accounts."
        )


def _sync_staff(*, seed_xero: bool) -> None:
    if seed_xero:
        staff = Staff.objects.filter(base_wage_rate__gt=0)
        summary = PayrollEmployeeSyncService.sync_staff(
            staff,
            dry_run=False,
            allow_create=True,
        )
        if summary["missing"]:
            raise RuntimeError("Demo staff could not all be linked to Xero Payroll.")
    else:
        summary = PayrollEmployeeSyncService.import_staff_from_xero(
            dry_run=False,
            initial_password="Default-staff-password",
        )
        if summary["errors"]:
            messages = [item["reason"] for item in summary["errors"]]
            raise RuntimeError("Xero staff import failed: " + "; ".join(messages))

    wage_staff = Staff.objects.filter(base_wage_rate__gt=0)
    if not wage_staff.exists():
        raise RuntimeError("No wage-earning staff were configured during onboarding.")
    staff_without_xero = wage_staff.filter(
        xero_user_id__isnull=True,
    )
    if staff_without_xero.exists():
        raise RuntimeError("One or more wage-earning staff are not linked to Xero.")


def _validate_completion() -> CompanyDefaults:
    company = CompanyDefaults.get_solo()
    required_xero_values = {
        "xero_tenant_id": company.xero_tenant_id,
        "xero_shortcode": company.xero_shortcode,
        "xero_sales_branding_theme_id": company.xero_sales_branding_theme_id,
        "xero_payroll_calendar_id": company.xero_payroll_calendar_id,
    }
    missing = [name for name, value in required_xero_values.items() if not value]
    if missing:
        raise RuntimeError(
            "Xero onboarding left required CompanyDefaults unset: " + ", ".join(missing)
        )
    shop_job_count = Job.objects.filter(
        company=company.shop_company,
        status="special",
        name__in=CANONICAL_SHOP_JOB_NAMES,
    ).count()
    if shop_job_count != 9:
        raise RuntimeError(f"Expected 9 canonical shop jobs, found {shop_job_count}.")
    return company


def finalize_instance_onboarding(*, seed_xero: bool = False) -> None:
    """Complete Xero-dependent setup and enable automated sync last."""
    CompanyDefaults.set_xero_sync_enabled(enabled=False)

    if not get_valid_token():
        raise RuntimeError("Complete Xero OAuth before finalising instance onboarding.")
    xero_setup_args = ["--setup"]
    if seed_xero:
        xero_setup_args.append("--seed-xero")
    call_command("xero", *xero_setup_args)
    sync_xero_pay_items()
    _sync_accounts()
    _sync_staff(seed_xero=seed_xero)
    call_command("create_shop_jobs")

    _validate_completion()
    CompanyDefaults.set_xero_sync_enabled(enabled=True)
