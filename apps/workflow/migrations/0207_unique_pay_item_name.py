"""Deduplicate XeroPayItem records and add unique constraint.

Production has duplicates from migration seeds + Xero sync creating separate
records. This migration keeps the record referenced by Jobs/CostLines (or the
one with a xero_id), reassigns FKs, and deletes the rest.
"""

from django.db import migrations, models


def deduplicate_pay_items(apps, _schema_editor):
    """Merge duplicate XeroPayItem records before adding unique constraint."""
    XeroPayItem = apps.get_model("workflow", "XeroPayItem")
    Job = apps.get_model("job", "Job")
    CostLine = apps.get_model("job", "CostLine")

    from collections import defaultdict

    # Group by (name, uses_leave_api)
    groups = defaultdict(list)
    for item in XeroPayItem.objects.all():
        groups[(item.name, item.uses_leave_api)].append(item)

    merged = 0
    for (name, uses_leave_api), items in groups.items():
        if len(items) < 2:
            continue

        # Pick the keeper: prefer the one referenced by Jobs/CostLines
        keeper = None
        for item in items:
            job_refs = Job.objects.filter(default_xero_pay_item=item).count()
            cl_refs = CostLine.objects.filter(xero_pay_item=item).count()
            if job_refs or cl_refs:
                keeper = item
                break

        if not keeper:
            # No references — keep whichever has a xero_id, or just the first
            keeper = next((i for i in items if i.xero_id), items[0])

        # Reassign FKs from duplicates to keeper, then delete duplicates
        for item in items:
            if item.pk == keeper.pk:
                continue
            # Copy xero_id to keeper if keeper doesn't have one
            if not keeper.xero_id and item.xero_id:
                keeper.xero_id = item.xero_id
                keeper.xero_tenant_id = item.xero_tenant_id
                keeper.save(update_fields=["xero_id", "xero_tenant_id"])

            Job.objects.filter(default_xero_pay_item=item).update(
                default_xero_pay_item=keeper
            )
            CostLine.objects.filter(xero_pay_item=item).update(xero_pay_item=keeper)
            item.delete()
            merged += 1

    if merged:
        print(f"  Deduplicated {merged} XeroPayItem records")


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0206_companydefaults_logo_companydefaults_logo_wide"),
        ("job", "0071_add_rdti_type"),
    ]

    operations = [
        migrations.RunPython(deduplicate_pay_items, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="xeropayitem",
            constraint=models.UniqueConstraint(
                fields=["name", "uses_leave_api"],
                name="unique_pay_item_name_per_api",
            ),
        ),
    ]
