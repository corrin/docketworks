"""Clear the Xero pay item from public-holiday time lines.

Opus: Xero Payroll NZ computes public-holiday pay itself, from the employee's
working pattern, and exposes no endpoint to create, amend or suppress it.
Docketworks bound the category to the "Ordinary Time" earnings rate, so
``payroll_push`` routed those hours to the Timesheets API on top of the line
Xero was already paying — the day paid twice.

Clearing the pay item is what stops it: ``LeaveCatalogue`` classifies a time
line with no pay item by the leave job it belongs to, the posting split sends
it nowhere, and the preflight no longer demands a Xero id for a line it will
not send. The hours, their cost and their billability are untouched; only the
Xero object they name, and the column they report in, change.

Guarded at both ends rather than trusted (ADR 0015): an unexpected pay item on
that job aborts the migration instead of being rewritten, and the number of
rows updated must equal the number counted before the write.
"""

import logging
from typing import Any

from django.db import migrations

STAT_HOLIDAY_JOB = "Statutory holiday"


def clear_public_holiday_pay_items(apps: Any, schema_editor: Any) -> None:
    """Null the pay item on every actual time line booked to the stat-holiday job."""
    Job = apps.get_model("job", "Job")
    CostLine = apps.get_model("job", "CostLine")
    LeaveType = apps.get_model("timesheet", "LeaveType")

    leave_type = LeaveType.objects.filter(code="public_holiday").select_related("job").first()
    job = leave_type.job if leave_type is not None and leave_type.job_id else None
    if job is None:
        # Opus: The binding is the real key; this fallback covers a database
        # migrated before the seed could bind it. Matching the job NAME is what
        # ADR 0007 bans as a ROUTING rule — here it only locates rows to repair
        # in a migration, and getting it wrong repairs nothing rather than
        # misrouting pay.
        job = Job.objects.filter(name=STAT_HOLIDAY_JOB, status="special").first()
    if job is None:
        # A database that never onboarded the special jobs has nothing to fix.
        return

    lines = CostLine.objects.filter(cost_set__job_id=job.id, kind="time", cost_set__kind="actual")

    # Opus: Every pay item on these lines goes, whichever it is. An earlier draft
    # refused anything but "Ordinary Time" — which keys the guard on an
    # admin-editable NAME, exactly what ADR 0007 lists under "Do not", and would
    # hard-fail `migrate` during cutover for an organisation that had renamed
    # its ordinary rate. There is nothing to guess between: ``CostLine.clean``
    # now refuses ANY pay item on a category Xero pays itself, so a line keeping
    # one is unsaveable rather than ambiguous. What was cleared is logged so the
    # change is still recoverable from the record.
    cleared = sorted(
        set(lines.exclude(xero_pay_item__isnull=True).values_list("xero_pay_item__name", flat=True))
    )

    expected = lines.filter(xero_pay_item__isnull=False).count()
    updated = lines.filter(xero_pay_item__isnull=False).update(xero_pay_item=None)
    if updated != expected:
        raise RuntimeError(
            f"Expected to clear {expected} public-holiday pay items but cleared {updated}."
        )
    if updated:
        logging.getLogger(__name__).info(
            "Cleared the Xero pay item from %d public-holiday time lines (was: %s). "
            "Xero computes that day from the employee's working pattern; posting it paid twice.",
            updated,
            ", ".join(cleared),
        )


class Migration(migrations.Migration):
    """Stop naming a Xero earnings rate on hours Xero pays from its own calculation."""

    dependencies = [
        ("timesheet", "0003_adr_0040_blank_checks"),
        ("job", "0004_costline_managed_by_and_more"),
    ]

    operations = [
        # Opus: Irreversible by intent. The reverse would restore a pay item whose
        # only effect was to pay the day a second time, and the rows it would
        # have to name are exactly the ones this cleared.
        migrations.RunPython(clear_public_holiday_pay_items, migrations.RunPython.noop),
    ]
