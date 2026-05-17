from django.db import migrations


def reclassify_stock_consumption_costlines(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            UPDATE job_costline cl
            SET
                kind = 'material',
                staff_id = NULL,
                entry_seq = NULL,
                meta = jsonb_build_object(
                    'comments',
                    'Legacy material entry, recorded by staff '
                        || (cl.meta->>'consumed_by')
                        || '; reverted from kind=time set by migration 0061',
                    'source',
                    'legacy_0061_revert'
                ),
                updated_at = NOW()
            FROM job_costset cs
            WHERE cl.cost_set_id = cs.id
              AND cs.kind = 'actual'
              AND cl.kind = 'time'
              AND cl.meta ? 'consumed_by'
              AND NOT (cl.meta ? 'staff_id')
              AND cl.unit_cost > 0
            """)

        cursor.execute("""
            UPDATE job_costline cl
            SET
                kind = 'adjust',
                staff_id = NULL,
                entry_seq = NULL,
                meta = jsonb_build_object(
                    'comments',
                    'Legacy billing adjustment, recorded by staff '
                        || (cl.meta->>'consumed_by')
                        || '; reverted from kind=time set by migration 0061',
                    'source',
                    'legacy_0061_revert'
                ),
                updated_at = NOW()
            FROM job_costset cs
            WHERE cl.cost_set_id = cs.id
              AND cs.kind = 'actual'
              AND cl.kind = 'time'
              AND cl.meta ? 'consumed_by'
              AND NOT (cl.meta ? 'staff_id')
              AND (cl.unit_cost IS NULL OR cl.unit_cost = 0)
            """)

        cursor.execute("""
            SELECT COUNT(*)
            FROM job_costline cl
            JOIN job_costset cs ON cl.cost_set_id = cs.id
            WHERE cs.kind = 'actual'
              AND cl.kind = 'time'
              AND NOT (cl.meta ? 'staff_id')
            """)
        remaining = cursor.fetchone()[0]
        if remaining:
            raise RuntimeError(
                f"Still {remaining} actual time entries without meta.staff_id."
            )


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0087_costline_staff_entry_seq"),
    ]

    operations = [
        migrations.RunPython(
            reclassify_stock_consumption_costlines,
            migrations.RunPython.noop,
        ),
    ]
