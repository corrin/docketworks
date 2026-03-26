# CompanyDefaults backup taken 2026-02-09 before running xero --setup
# To restore: python manage.py shell < company_defaults_backup_20260209.py

import datetime
from decimal import Decimal

from apps.workflow.models import CompanyDefaults

cd = CompanyDefaults.objects.first()

cd.company_name = "Morris Sheetmetal Works"
cd.company_acronym = None
cd.is_primary = True
cd.time_markup = Decimal("0.30")
cd.materials_markup = Decimal("0.20")
cd.charge_out_rate = Decimal("110.00")
cd.wage_rate = Decimal("32.00")
cd.starting_job_number = 95189
cd.starting_po_number = 1
cd.po_prefix = "JO-"
cd.master_quote_template_url = None
cd.master_quote_template_id = None
cd.gdrive_quotes_folder_url = None
cd.gdrive_quotes_folder_id = None
cd.xero_tenant_id = "75e57cfd-302d-4f84-8734-8aae354e76a7"
cd.xero_shortcode = None
cd.xero_payroll_calendar_name = "Weekly"
cd.xero_payroll_calendar_id = None
cd.mon_start = datetime.time(7, 0)
cd.mon_end = datetime.time(15, 0)
cd.tue_start = datetime.time(7, 0)
cd.tue_end = datetime.time(15, 0)
cd.wed_start = datetime.time(7, 0)
cd.wed_end = datetime.time(15, 0)
cd.thu_start = datetime.time(7, 0)
cd.thu_end = datetime.time(15, 0)
cd.fri_start = datetime.time(7, 0)
cd.fri_end = datetime.time(15, 0)
cd.created_at = datetime.datetime(2024, 1, 1, 0, 0, tzinfo=datetime.timezone.utc)
cd.updated_at = datetime.datetime(
    2026, 2, 9, 7, 55, 54, 887141, tzinfo=datetime.timezone.utc
)
cd.last_xero_sync = datetime.datetime(
    2026, 2, 9, 7, 55, 17, 384865, tzinfo=datetime.timezone.utc
)
cd.last_xero_deep_sync = datetime.datetime(
    2026, 1, 14, 22, 43, 9, 10727, tzinfo=datetime.timezone.utc
)
cd.address_line1 = None
cd.address_line2 = None
cd.suburb = None
cd.city = None
cd.post_code = None
cd.country = "New Zealand"
cd.company_email = None
cd.company_url = None
cd.shop_client_name = "MSM (Shop)"
cd.test_client_name = "Testing - please ignore"
cd.billable_threshold_green = Decimal("45.00")
cd.billable_threshold_amber = Decimal("30.00")
cd.daily_gp_target = Decimal("1250.00")
cd.shop_hours_target_percentage = Decimal("20.00")

cd.save()
print("CompanyDefaults restored from backup")
