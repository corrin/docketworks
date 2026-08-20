from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

MAPPINGS = (
    ("annual_leave", "Annual Leave", "Annual Leave", "Annual Leave", True),
    ("sick_leave", "Sick Leave", "Sick Leave", "Sick Leave", True),
    ("unpaid_leave", "Unpaid Leave", "Unpaid Leave", "Unpaid Leave", True),
    (
        "bereavement_leave",
        "Bereavement Leave",
        "Bereavement Leave",
        "Bereavement Leave",
        True,
    ),
    ("public_holiday", "Public Holiday", "Statutory holiday", "Ordinary Time", False),
)


def seed_leave_types(apps: StateApps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    LeaveType = apps.get_model("timesheet", "LeaveType")
    Job = apps.get_model("job", "Job")
    XeroPayItem = apps.get_model("xero", "XeroPayItem")

    for code, display_name, job_name, pay_item_name, uses_leave_api in MAPPINGS:
        job = Job.objects.filter(name=job_name, status="special").first()
        if job is not None:
            pay_item = XeroPayItem.objects.filter(
                name=pay_item_name, uses_leave_api=uses_leave_api
            ).first()
            if pay_item is not None:
                Job.objects.filter(pk=job.pk).update(default_xero_pay_item=pay_item)
        LeaveType.objects.update_or_create(
            code=code,
            defaults={"display_name": display_name, "job": job},
        )


class Migration(migrations.Migration):
    dependencies = [("timesheet", "0001_initial"), ("xero", "0001_initial")]

    operations = [migrations.RunPython(seed_leave_types, migrations.RunPython.noop)]
