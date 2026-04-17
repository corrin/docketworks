import datetime

import requests
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from xero_python.accounting import AccountingApi
from xero_python.identity import IdentityApi
from xero_python.payrollnz import PayrollNzApi
from xero_python.payrollnz.models import CalendarType, PayRunCalendar
from xero_python.project import ProjectApi

from apps.accounts.models import Staff
from apps.timesheet.services import PayrollEmployeeSyncService
from apps.workflow.api.xero.auth import api_client, get_tenant_id, get_valid_token
from apps.workflow.api.xero.payroll import (
    get_earnings_rates,
    get_employees,
    get_leave_types,
    get_pay_runs,
    get_payroll_calendars,
)
from apps.workflow.models import XeroToken
from apps.workflow.models.company_defaults import CompanyDefaults


def get_employees_simple_dev():
    """
    DEV ONLY: Fetch employee basic info for demo company with invalid contractors.

    Returns simple dicts with just: employee_id, first_name, last_name, email.
    Skips contractors without dateOfBirth that crash the xero-python library.
    """
    token = XeroToken.objects.first()
    tenant_id = get_tenant_id()

    headers = {
        "Authorization": f"Bearer {token.access_token}",
        "Xero-Tenant-Id": tenant_id,
        "Accept": "application/json",
    }

    response = requests.get(
        "https://api.xero.com/payroll.xro/2.0/Employees", headers=headers
    )
    response.raise_for_status()

    raw_employees = response.json().get("employees", [])

    # Extract only needed fields, skip contractors (no dateOfBirth)
    employees = []
    skipped = 0
    for emp in raw_employees:
        if emp.get("dateOfBirth"):
            employees.append(
                {
                    "employee_id": emp.get("employeeID"),
                    "first_name": emp.get("firstName"),
                    "last_name": emp.get("lastName"),
                    "email": emp.get("email"),
                }
            )
        else:
            skipped += 1

    return employees, skipped


class Command(BaseCommand):
    help = "Interactive Xero API utility - get tenant IDs, users, and other data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--setup",
            action="store_true",
            help="Configure Xero tenant ID, shortcode, and payroll calendar",
        )
        parser.add_argument(
            "--no-set",
            action="store_true",
            help="Do not automatically set the tenant ID if only one tenant is found",
        )
        parser.add_argument(
            "--tenant",
            action="store_true",
            help="Get available Xero tenant IDs and names",
        )
        parser.add_argument(
            "--users",
            action="store_true",
            help="Get Xero users from Projects API",
        )
        parser.add_argument(
            "--payroll-employees",
            action="store_true",
            help="Get Xero Payroll employees",
        )
        parser.add_argument(
            "--payroll-rates",
            action="store_true",
            help="Get Xero Payroll earnings rates",
        )
        parser.add_argument(
            "--payroll-calendars",
            action="store_true",
            help="Get Xero Payroll calendars",
        )
        parser.add_argument(
            "--payroll-leave-types",
            action="store_true",
            help="Get Xero Payroll leave types",
        )
        parser.add_argument(
            "--payroll-pay-runs",
            action="store_true",
            help="Get Xero Payroll pay runs",
        )
        parser.add_argument(
            "--create-missing-xero-items",
            action="store_true",
            help="Create the payroll calendar in Xero if it does not exist (use when restoring to dev after a demo org reset)",
        )
        parser.add_argument(
            "--configure-payroll",
            action="store_true",
            help="Interactively configure payroll earnings rate mappings",
        )
        parser.add_argument(
            "--link-staff",
            action="store_true",
            help="Link staff to Xero Payroll employees by matching email addresses",
        )
        parser.add_argument(
            "--link-staff-emails",
            help="Comma separated list of staff emails to limit linking operations",
        )
        parser.add_argument(
            "--link-staff-dry-run",
            action="store_true",
            help="Preview staff linking without modifying the database",
        )
        parser.add_argument(
            "--create-staff",
            action="store_true",
            help="Create Xero Payroll employees for unlinked staff (use with --create-staff-emails)",
        )
        parser.add_argument(
            "--create-staff-emails",
            help="Comma separated list of staff emails to create in Xero Payroll",
        )
        parser.add_argument(
            "--create-staff-dry-run",
            action="store_true",
            help="Preview staff creation without modifying Xero or the database",
        )
        parser.add_argument(
            "--import-staff",
            action="store_true",
            help="Import employees from Xero Payroll as local Staff records (for fresh prospect instances)",
        )
        parser.add_argument(
            "--import-staff-dry-run",
            action="store_true",
            help="Preview staff import without creating records",
        )
        parser.add_argument(
            "--import-staff-password",
            type=str,
            default="Default-staff-password",
            help="Initial password for imported staff (default: Default-staff-password)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Bypass safety checks (e.g. allow --import-staff when Staff already exist)",
        )
        parser.add_argument(
            "--raw-api",
            action="store_true",
            help="DEV ONLY: Use the RAW API workaround for demo company with invalid contractor data",
        )

    def handle(self, *args, **options):
        # First check we have a valid token
        token = get_valid_token()
        if not token:
            self.stdout.write(
                self.style.ERROR(
                    "No valid Xero token found.\n"
                    "Connect to Xero via Admin > Xero Settings in the web app first."
                )
            )
            return

        # Handle specific flags
        if options["setup"]:
            self.run_setup(
                create_missing_xero_items=options["create_missing_xero_items"]
            )
            return

        if options["users"]:
            self.get_users()
            return

        if options["payroll_employees"]:
            self.get_payroll_employees(use_raw_api=options.get("raw_api", False))
            return

        if options["payroll_rates"]:
            self.get_payroll_rates()
            return

        if options["payroll_calendars"]:
            self.get_payroll_calendars()
            return

        if options["payroll_leave_types"]:
            self.get_payroll_leave_types()
            return

        if options["payroll_pay_runs"]:
            self.get_payroll_pay_runs()
            return

        if options["configure_payroll"]:
            self.configure_payroll()
            return

        import_staff_requested = options["import_staff"] or options.get(
            "import_staff_dry_run"
        )
        if import_staff_requested:
            self.import_staff(options)
            return

        link_staff_requested = (
            options["link_staff"]
            or bool(options.get("link_staff_dry_run"))
            or bool(options.get("link_staff_emails"))
        )

        if link_staff_requested:
            self.link_staff(options)
            return

        create_staff_requested = (
            options["create_staff"]
            or bool(options.get("create_staff_dry_run"))
            or bool(options.get("create_staff_emails"))
        )

        if create_staff_requested:
            self.create_staff(options)
            return

        if options["tenant"]:
            self.get_tenants(options)
            return

        # Default behavior: show tenant IDs (for backwards compatibility)
        self.get_tenants(options)

    def get_tenants(self, options):
        """Get available Xero tenant IDs and names"""
        identity_api = IdentityApi(api_client)
        connections = identity_api.get_connections()

        self.stdout.write("Available Xero Organizations:")
        self.stdout.write("-----------------------------")
        for conn in connections:
            self.stdout.write(self.style.SUCCESS(f"Tenant ID: {conn.tenant_id}"))
            self.stdout.write(f"Name: {conn.tenant_name}")
            self.stdout.write("-----------------------------")

        # If only one tenant and --no-set not specified, automatically set it
        if len(connections) == 1 and not options["no_set"]:
            tenant_id = connections[0].tenant_id
            tenant_name = connections[0].tenant_name

            try:
                company_defaults = CompanyDefaults.get_solo()
                company_defaults.xero_tenant_id = tenant_id
                company_defaults.save()

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Automatically set tenant ID to {tenant_id} "
                        f"({tenant_name}) in CompanyDefaults"
                    )
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Failed to set tenant ID in CompanyDefaults: {e}")
                )
        elif len(connections) == 1 and options["no_set"]:
            self.stdout.write(
                self.style.WARNING(
                    "Single tenant found but --no-set specified, "
                    "not updating CompanyDefaults"
                )
            )
        elif len(connections) > 1:
            self.stdout.write(
                self.style.WARNING(
                    f"Multiple tenants found ({len(connections)}), "
                    "not automatically setting tenant ID"
                )
            )

    def _ensure_demo_xero_items_exist(self, calendar_name: str, tenant_id: str) -> None:
        """Create any Xero payroll items missing from the demo org (e.g. after a demo org reset)."""
        from xero_python.payrollnz.models import EarningsRate, LeaveType

        from apps.workflow.models import XeroPayItem

        payroll_api = PayrollNzApi(api_client)

        # Calendar
        if calendar_name:
            calendars = get_payroll_calendars()
            if not any(c["name"] == calendar_name for c in calendars):
                self.stdout.write(
                    f"Payroll calendar '{calendar_name}' not found — creating it."
                )
                today = datetime.date.today()
                period_start = today - datetime.timedelta(days=today.weekday())
                payroll_api.create_pay_run_calendar(
                    xero_tenant_id=tenant_id,
                    pay_run_calendar=PayRunCalendar(
                        name=calendar_name,
                        calendar_type=CalendarType.WEEKLY,
                        period_start_date=period_start,
                        payment_date=period_start + datetime.timedelta(days=4),
                    ),
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Created payroll calendar: {calendar_name}")
                )

        # Pay items with no xero_id — present in DB (from prod backup) but missing in this Xero org
        missing = XeroPayItem.objects.filter(xero_id__isnull=True)
        if not missing.exists():
            return

        all_rates = get_earnings_rates()
        existing_rates = {r["name"] for r in all_rates}
        existing_leave = {lt["name"] for lt in get_leave_types()}

        # Use the expense account from an existing OtherGrossEarnings rate
        expense_account_id = next(
            (r["expense_account_id"] for r in all_rates if r.get("expense_account_id")),
            None,
        )
        if not expense_account_id:
            self.stdout.write(
                self.style.ERROR(
                    "Cannot create earnings rates: no existing rate has an expense_account_id."
                )
            )
            return

        for item in missing:
            if item.uses_leave_api:
                if item.name in existing_leave:
                    continue
                self.stdout.write(f"Leave type '{item.name}' not found — creating it.")
                payroll_api.create_leave_type(
                    xero_tenant_id=tenant_id,
                    leave_type=LeaveType(
                        name=item.name,
                        is_paid_leave=item.multiplier != 0,
                        show_on_payslip=True,
                    ),
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Created leave type: {item.name}")
                )
            else:
                if item.name in existing_rates:
                    continue
                self.stdout.write(
                    f"Earnings rate '{item.name}' not found — creating it."
                )
                multiplier = (
                    float(item.multiplier) if item.multiplier is not None else 1.0
                )
                payroll_api.create_earnings_rate(
                    xero_tenant_id=tenant_id,
                    earnings_rate=EarningsRate(
                        name=item.name,
                        earnings_type="OtherGrossEarnings",
                        rate_type="MultipleOfOrdinaryEarningsRate",
                        multiple_of_ordinary_earnings_rate=multiplier,
                        type_of_units="Hours",
                        expense_account_id=expense_account_id,
                    ),
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Created earnings rate: {item.name} ({multiplier}x)"
                    )
                )

    def run_setup(self, create_missing_xero_items: bool):
        """Configure Xero tenant ID, shortcode, and payroll calendar."""
        self.stdout.write("Setting up Xero connection...")

        # Step 1: Get connected organisations
        try:
            identity_api = IdentityApi(api_client)
            connections = identity_api.get_connections()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to get Xero connections: {e}"))
            raise

        if not connections:
            self.stdout.write(
                self.style.ERROR(
                    "No Xero organisations connected.\n"
                    "Please connect an organisation in Xero first."
                )
            )
            return

        # Step 2: Use first connected organisation
        connection = connections[0]
        tenant_id = connection.tenant_id
        tenant_name = connection.tenant_name

        self.stdout.write(f"Using organisation: {tenant_name}")

        if len(connections) > 1:
            self.stdout.write(
                self.style.WARNING(
                    f"Note: {len(connections)} organisations connected. Using first one."
                )
            )

        # Step 3: Get CompanyDefaults
        company = CompanyDefaults.get_solo()
        if not company:
            self.stdout.write(
                self.style.ERROR(
                    "No CompanyDefaults found.\n"
                    "Run: python manage.py loaddata apps/workflow/fixtures/company_defaults.json"
                )
            )
            return

        # Step 3b: Save tenant_id immediately so subsequent API calls can use it
        if company.xero_tenant_id != tenant_id:
            company.xero_tenant_id = tenant_id
            company.save(update_fields=["xero_tenant_id"])
        # Always update cache to prevent stale tenant ID from being used
        cache.set("xero_tenant_id", tenant_id)

        if create_missing_xero_items:
            self._ensure_demo_xero_items_exist(
                company.xero_payroll_calendar_name, tenant_id
            )

        # Step 4: Fetch organisation shortcode for deep linking
        accounting_api = AccountingApi(api_client)
        org_response = accounting_api.get_organisations(xero_tenant_id=tenant_id)

        if not org_response or not org_response.organisations:
            self.stdout.write(
                self.style.ERROR("Failed to fetch organisation details from Xero.")
            )
            return

        shortcode = org_response.organisations[0].short_code

        # Step 5: Fetch payroll calendar ID
        calendar_name = company.xero_payroll_calendar_name
        if not calendar_name:
            self.stdout.write(
                self.style.WARNING(
                    "xero_payroll_calendar_name not configured in CompanyDefaults. "
                    "Skipping payroll calendar setup."
                )
            )
            payroll_calendar_id = None
        else:
            calendars = get_payroll_calendars()
            matching_calendar = next(
                (c for c in calendars if c["name"] == calendar_name), None
            )
            if not matching_calendar:
                available = [c["name"] for c in calendars]
                self.stdout.write(
                    self.style.ERROR(
                        f"Payroll calendar '{calendar_name}' not found in Xero.\n"
                        f"Available calendars: {available}\n"
                        f"If restoring to dev after a demo org reset, re-run with --create-missing-xero-items."
                    )
                )
                return
            payroll_calendar_id = matching_calendar["id"]

        # Step 6: Save to CompanyDefaults
        company.xero_tenant_id = tenant_id
        company.xero_shortcode = shortcode
        company.xero_payroll_calendar_id = payroll_calendar_id
        company.save()

        self.stdout.write(self.style.SUCCESS(f"Tenant ID: {tenant_id}"))
        self.stdout.write(self.style.SUCCESS(f"Shortcode: {shortcode}"))
        if payroll_calendar_id:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Payroll Calendar: {calendar_name} ({payroll_calendar_id})"
                )
            )
        self.stdout.write(self.style.SUCCESS("Xero setup complete."))
        self.stdout.write("")
        self.stdout.write("Next step: python manage.py start_xero_sync")

    def get_users(self):
        """Get Xero users from Projects API"""
        tenant_id = get_tenant_id()
        if not tenant_id:
            self.stdout.write(
                self.style.ERROR(
                    "No Xero tenant ID configured. Run with --tenant first."
                )
            )
            return

        try:
            project_api = ProjectApi(api_client)
            users_response = project_api.get_project_users(xero_tenant_id=tenant_id)

            self.stdout.write(
                f"Xero Users (Projects API) - Total: {len(users_response.items)}:"
            )
            self.stdout.write("---------------------------")

            for i, user in enumerate(users_response.items, 1):
                self.stdout.write(f"Entry #{i}:")
                self.stdout.write(f"  User ID: {user.user_id}")
                self.stdout.write(f"  Name: {user.name}")
                self.stdout.write(f"  Email: {user.email}")
                # Show all available attributes to help debug
                self.stdout.write(f"  Full object: {user.to_dict()}")
                self.stdout.write("---------------------------")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to get users: {e}"))

    def get_payroll_employees(self, use_raw_api):
        """Get Xero Payroll employees"""
        self.stdout.write(self.style.SUCCESS("\n=== Xero Payroll Employees ===\n"))

        try:
            if use_raw_api:
                # DEV ONLY workaround for demo company
                employees, skipped = get_employees_simple_dev()
                if skipped > 0:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipped {skipped} contractors (no dateOfBirth)\n"
                        )
                    )
            else:
                # Proper API - use xero-python library
                employee_objects = get_employees()
                employees = [
                    {
                        "employee_id": emp.employee_id,
                        "first_name": emp.first_name,
                        "last_name": emp.last_name,
                        "email": emp.email,
                    }
                    for emp in employee_objects
                ]

            if not employees:
                self.stdout.write(
                    self.style.WARNING("No employees found in Xero Payroll")
                )
                return

            for emp in employees:
                self.stdout.write(
                    f"ID: {emp['employee_id']}\n"
                    f"  Name: {emp['first_name']} {emp['last_name']}\n"
                    f"  Email: {emp['email'] or 'N/A'}\n"
                )

            self.stdout.write(
                self.style.SUCCESS(f"\nTotal: {len(employees)} employees")
            )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to fetch employees: {e}"))

    def get_payroll_rates(self):
        """Get Xero Payroll earnings rates"""
        self.stdout.write(self.style.SUCCESS("\n=== Xero Payroll Earnings Rates ===\n"))

        try:
            rates = get_earnings_rates()

            if not rates:
                self.stdout.write(
                    self.style.WARNING("No earnings rates found in Xero Payroll")
                )
                return

            for rate in rates:
                self.stdout.write(
                    f"ID: {rate['id']}\n"
                    f"  Name: {rate['name']}\n"
                    f"  Type: {rate['earnings_type']}\n"
                    f"  Rate Type: {rate['rate_type']}\n"
                    f"  Units: {rate['type_of_units']}\n"
                )

            self.stdout.write(
                self.style.SUCCESS(f"\nTotal: {len(rates)} earnings rates")
            )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to fetch earnings rates: {e}"))

    def get_payroll_calendars(self):
        """Get Xero Payroll calendars"""
        self.stdout.write(self.style.SUCCESS("\n=== Xero Payroll Calendars ===\n"))

        try:
            calendars = get_payroll_calendars()

            if not calendars:
                self.stdout.write(
                    self.style.WARNING("No payroll calendars found in Xero Payroll")
                )
                return

            for cal in calendars:
                self.stdout.write(
                    f"ID: {cal['id']}\n"
                    f"  Name: {cal['name']}\n"
                    f"  Type: {cal['calendar_type']}\n"
                    f"  Period: {cal['period_start_date']} to {cal['period_end_date']}\n"
                    f"  Payment Date: {cal['payment_date']}\n"
                )

            self.stdout.write(
                self.style.SUCCESS(f"\nTotal: {len(calendars)} calendars")
            )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Failed to fetch payroll calendars: {e}")
            )

    def get_payroll_leave_types(self):
        """Get Xero Payroll leave types"""
        self.stdout.write(self.style.SUCCESS("\n=== Xero Payroll Leave Types ===\n"))

        try:
            leave_types = get_leave_types()

            if not leave_types:
                self.stdout.write(
                    self.style.WARNING("No leave types found in Xero Payroll")
                )
                return

            for lt in leave_types:
                self.stdout.write(f"ID: {lt['id']}\n" f"  Name: {lt['name']}\n")

            self.stdout.write(
                self.style.SUCCESS(f"\nTotal: {len(leave_types)} leave types")
            )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to fetch leave types: {e}"))

    def get_payroll_pay_runs(self):
        """Get Xero Payroll pay runs"""
        self.stdout.write(self.style.SUCCESS("\n=== Xero Payroll Pay Runs ===\n"))

        try:
            pay_runs = get_pay_runs()

            if not pay_runs:
                self.stdout.write(
                    self.style.WARNING("No pay runs found in Xero Payroll")
                )
                return

            for pr in pay_runs:
                self.stdout.write(f"Pay Run ID: {pr['pay_run_id']}")
                self.stdout.write(
                    f"  Period: {pr['period_start_date']} to {pr['period_end_date']}"
                )
                self.stdout.write(f"  Payment Date: {pr['payment_date']}")
                self.stdout.write(f"  Status: {pr['pay_run_status']}")
                self.stdout.write(f"  Type: {pr['pay_run_type']}")
                self.stdout.write(f"  Calendar ID: {pr['payroll_calendar_id']}\n")

            self.stdout.write(self.style.SUCCESS(f"\nTotal: {len(pay_runs)} pay runs"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to fetch pay runs: {e}"))

    def configure_payroll(self):
        """Sync XeroPayItem from Xero Leave Types and Earnings Rates."""
        from apps.workflow.api.xero.payroll import sync_xero_pay_items

        self.stdout.write(self.style.SUCCESS("\n=== Sync Xero Pay Items ===\n"))

        try:
            result = sync_xero_pay_items()

            self.stdout.write(
                f"Leave types: {result['leave_types']['created']} created, "
                f"{result['leave_types']['updated']} updated"
            )
            self.stdout.write(
                f"Earnings rates: {result['earnings_rates']['created']} created, "
                f"{result['earnings_rates']['updated']} updated"
            )
            self.stdout.write(self.style.SUCCESS("\n✓ XeroPayItem sync completed!"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to sync pay items: {e}"))

    def _prompt_for_id(self, label, items, current_value):
        """Prompt user to select an ID from a list of items (leave types, earnings rates, etc.)"""
        current_display = current_value if current_value else "Not set"
        prompt = f"\n{label} (current: {current_display})\nEnter ID (or press Enter to skip): "

        item_id = input(prompt).strip()

        if not item_id:
            return current_value  # Keep existing value

        # Validate that the ID exists
        if not any(item["id"] == item_id for item in items):
            self.stdout.write(
                self.style.WARNING(f"Warning: {item_id} not found in available items")
            )
            confirm = input("Use this ID anyway? (y/N): ").strip().lower()
            if confirm != "y":
                return current_value

        return item_id

    def link_staff(self, options):
        """Link Staff rows to existing Xero Payroll employees by email/name match.

        Includes all staff (active and inactive) so that historical timesheets
        can be posted for departed employees.
        """
        emails_option = options.get("link_staff_emails")
        dry_run = options.get("link_staff_dry_run", False)

        # Only include staff with wage rates (excludes admin-only users)
        queryset = Staff.objects.filter(wage_rate__gt=0)
        if emails_option:
            emails = [
                email.strip() for email in emails_option.split(",") if email.strip()
            ]
            if not emails:
                self.stdout.write(
                    self.style.WARNING(
                        "No valid emails provided via --link-staff-emails; nothing to do."
                    )
                )
                return

            email_filter = Q()
            for email in emails:
                email_filter |= Q(email__iexact=email)
            queryset = queryset.filter(email_filter)

        if not queryset.exists():
            self.stdout.write(
                self.style.WARNING(
                    "No staff records matched the provided filters. Aborting."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Linking {queryset.count()} staff member(s) (dry run={dry_run})"
            )
        )

        try:
            summary = PayrollEmployeeSyncService.sync_staff(
                staff_queryset=queryset,
                dry_run=dry_run,
                allow_create=False,  # Link only, no creation
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self._print_link_staff_summary(summary)

    def create_staff(self, options):
        """Create Xero Payroll employees for specified staff members."""
        emails_option = options.get("create_staff_emails")
        dry_run = options.get("create_staff_dry_run", False)

        if not emails_option:
            self.stdout.write(
                self.style.ERROR(
                    "--create-staff-emails is required. Specify which staff to create."
                )
            )
            return

        emails = [email.strip() for email in emails_option.split(",") if email.strip()]
        if not emails:
            self.stdout.write(
                self.style.WARNING("No valid emails provided; nothing to do.")
            )
            return

        email_filter = Q()
        for email in emails:
            email_filter |= Q(email__iexact=email)
        # Include all staff (active and inactive) for historical timesheet support
        queryset = Staff.objects.filter(email_filter)

        if not queryset.exists():
            self.stdout.write(
                self.style.WARNING("No staff records matched the provided emails.")
            )
            return

        # Check for already-linked staff
        already_linked = queryset.exclude(xero_user_id__isnull=True).exclude(
            xero_user_id=""
        )
        if already_linked.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"Skipping {already_linked.count()} already-linked staff:"
                )
            )
            for s in already_linked:
                self.stdout.write(f"  {s.email} -> {s.xero_user_id}")

        # Only process unlinked staff
        unlinked = queryset.filter(Q(xero_user_id__isnull=True) | Q(xero_user_id=""))

        if not unlinked.exists():
            self.stdout.write(self.style.WARNING("No unlinked staff to create."))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Creating {unlinked.count()} Xero Payroll employee(s) (dry run={dry_run})"
            )
        )

        try:
            summary = PayrollEmployeeSyncService.sync_staff(
                staff_queryset=unlinked,
                dry_run=dry_run,
                allow_create=True,  # Create in Xero
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self._print_create_staff_summary(summary)

    def _print_create_staff_summary(self, summary):
        """Print summary of staff creation."""
        dry_run = summary.get("dry_run", False)
        created = summary.get("created", [])
        missing = summary.get("missing", [])

        if created:
            verb = "Would create" if dry_run else "Created"
            self.stdout.write(
                self.style.SUCCESS(f"{verb} {len(created)} Xero Payroll employee(s):")
            )
            for entry in created:
                emp_id = entry.get("xero_employee_id") or "NEW"
                self.stdout.write(f"  {entry['email']} -> {emp_id}")

        if missing:
            self.stdout.write(
                self.style.ERROR(f"{len(missing)} staff could not be created:")
            )
            for entry in missing:
                self.stdout.write(f"  {entry['email']}")

    def _print_link_staff_summary(self, summary):
        total = summary.get("total", 0)
        dry_run = summary.get("dry_run", False)
        self.stdout.write(f"Total evaluated: {total}")
        self.stdout.write(f"Dry run: {'Yes' if dry_run else 'No'}")

        linked = summary.get("linked", [])
        created = summary.get("created", [])
        already = summary.get("already_linked", [])
        missing = summary.get("missing", [])

        if linked:
            self.stdout.write(self.style.SUCCESS(f"Linked {len(linked)} staff:"))
            for entry in linked:
                self.stdout.write(
                    f"  {entry['email']} -> {entry['xero_employee_id']} "
                    f"(Xero: {entry['xero_name'] or 'N/A'})"
                )

        if created:
            verb = "Would create" if dry_run else "Created"
            self.stdout.write(
                self.style.SUCCESS(f"{verb} {len(created)} Xero payroll employee(s):")
            )
            for entry in created:
                target = entry["xero_employee_id"] or "NEW"
                self.stdout.write(f"  {entry['email']} -> {target}")

        if already:
            self.stdout.write(
                self.style.WARNING(f"Skipped {len(already)} already-linked staff:")
            )
            for entry in already:
                self.stdout.write(f"  {entry['email']} (existing link)")

        if missing:
            self.stdout.write(
                self.style.ERROR(
                    f"{len(missing)} staff have no matching Xero employee. "
                    "Rerun with --link-staff-create-missing once their data is complete."
                )
            )
            for entry in missing:
                self.stdout.write(f"  {entry['email']}")

    def _prompt_for_rate_name(self, label, rates, current_value):
        """Prompt user to select an earnings rate by name (IDs looked up at runtime)."""
        current_display = current_value if current_value else "Not set"
        prompt = f"\n{label} (current: {current_display})\nEnter earnings rate name (or press Enter to keep): "

        rate_name = input(prompt).strip()

        if not rate_name:
            return current_value  # Keep existing value

        # Validate that the rate name exists
        if not any(r["name"] == rate_name for r in rates):
            self.stdout.write(
                self.style.WARNING(
                    f"Warning: '{rate_name}' not found in available rates"
                )
            )
            confirm = input("Use this name anyway? (y/N): ").strip().lower()
            if confirm != "y":
                return current_value

        return rate_name

    def _prompt_for_leave_type_name(self, label, leave_types, current_value):
        """Prompt user to select a leave type by name (IDs looked up at runtime)."""
        current_display = current_value if current_value else "Not set"
        prompt = f"\n{label} (current: {current_display})\nEnter leave type name (or press Enter to keep): "

        type_name = input(prompt).strip()

        if not type_name:
            return current_value  # Keep existing value

        # Validate that the leave type name exists
        if not any(lt["name"] == type_name for lt in leave_types):
            self.stdout.write(
                self.style.WARNING(
                    f"Warning: '{type_name}' not found in available leave types"
                )
            )
            confirm = input("Use this name anyway? (y/N): ").strip().lower()
            if confirm != "y":
                return current_value

        return type_name

    def import_staff(self, options):
        """Import employees from Xero Payroll as local Staff records."""
        dry_run = options.get("import_staff_dry_run", False)
        force = options.get("force", False)
        initial_password = options.get(
            "import_staff_password", "Default-staff-password"
        )

        # Guard against double-import
        existing_staff = Staff.objects.filter(base_wage_rate__gt=0).count()
        if existing_staff > 0 and not force:
            raise CommandError(
                f"Found {existing_staff} existing Staff with wage rates. "
                "This command is for fresh instances only. "
                "Use --force to bypass this check."
            )

        mode = "DRY RUN" if dry_run else "IMPORTING"
        self.stdout.write(f"\n{'=' * 50}")
        self.stdout.write(f"  {mode}: Import Staff from Xero Payroll")
        self.stdout.write(f"{'=' * 50}\n")

        summary = PayrollEmployeeSyncService.import_staff_from_xero(
            dry_run=dry_run,
            initial_password=initial_password,
        )

        # Print results
        self.stdout.write(f"\nXero employees found: {summary['total_xero_employees']}")
        self.stdout.write(f"Active employees: {summary['active_employees']}")

        if summary["created"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n{'Created' if not dry_run else 'Would create'}: {len(summary['created'])} staff"
                )
            )
            for item in summary["created"]:
                self.stdout.write(
                    f"  + {item['employee']} — ${item['hourly_rate']:.2f}/hr, "
                    f"{item['hours_per_week']:.0f} hrs/week"
                )

        if summary["skipped"]:
            self.stdout.write(
                self.style.WARNING(f"\nSkipped: {len(summary['skipped'])}")
            )
            for item in summary["skipped"]:
                self.stdout.write(f"  - {item['employee']}: {item['reason']}")

        if summary["errors"]:
            self.stdout.write(self.style.ERROR(f"\nErrors: {len(summary['errors'])}"))
            for item in summary["errors"]:
                self.stdout.write(f"  ! {item['employee']}: {item['reason']}")

        if not dry_run and summary["created"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nDone. {len(summary['created'])} staff imported. "
                    f"Initial password: {initial_password}"
                )
            )
            self.stdout.write("All imported staff have password_needs_reset=True.")
