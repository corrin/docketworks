import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


def backfill_actual_time_staff_and_sequence(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        raise RuntimeError(
            "CostLine staff/entry_seq backfill requires PostgreSQL window functions."
        )

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*)
            FROM job_costline cl
            JOIN job_costset cs ON cl.cost_set_id = cs.id
            WHERE cs.kind = 'actual'
              AND cl.kind = 'time'
              AND COALESCE(cl.meta->>'staff_id', cl.meta->>'consumed_by') IS NULL
            """)
        missing_staff_ref = cursor.fetchone()[0]
        if missing_staff_ref:
            raise RuntimeError(
                "Cannot backfill CostLine.staff: "
                f"{missing_staff_ref} actual time entries have no legacy staff reference."
            )

        cursor.execute("""
            SELECT COUNT(*)
            FROM job_costline cl
            JOIN job_costset cs ON cl.cost_set_id = cs.id
            LEFT JOIN accounts_staff staff
              ON COALESCE(cl.meta->>'staff_id', cl.meta->>'consumed_by')::uuid = staff.id
            WHERE cs.kind = 'actual'
              AND cl.kind = 'time'
              AND staff.id IS NULL
            """)
        invalid_staff_ref = cursor.fetchone()[0]
        if invalid_staff_ref:
            raise RuntimeError(
                "Cannot backfill CostLine.staff: "
                f"{invalid_staff_ref} actual time entries reference missing staff."
            )

        cursor.execute("""
            UPDATE job_costline cl
            SET staff_id = COALESCE(cl.meta->>'staff_id', cl.meta->>'consumed_by')::uuid
            FROM job_costset cs
            WHERE cl.cost_set_id = cs.id
              AND cs.kind = 'actual'
              AND cl.kind = 'time'
            """)

        cursor.execute("""
            WITH ordered AS (
                SELECT
                    cl.id,
                    ROW_NUMBER() OVER (
                        PARTITION BY cl.staff_id, cl.accounting_date
                        ORDER BY cl.created_at, cl.id
                    ) AS seq
                FROM job_costline cl
                JOIN job_costset cs ON cl.cost_set_id = cs.id
                WHERE cs.kind = 'actual'
                  AND cl.kind = 'time'
            )
            UPDATE job_costline cl
            SET entry_seq = ordered.seq
            FROM ordered
            WHERE cl.id = ordered.id
            """)

        cursor.execute("""
            SELECT COUNT(*)
            FROM job_costline cl
            JOIN job_costset cs ON cl.cost_set_id = cs.id
            WHERE cs.kind = 'actual'
              AND cl.kind = 'time'
              AND (cl.staff_id IS NULL OR cl.entry_seq IS NULL)
            """)
        incomplete_actual_time = cursor.fetchone()[0]
        if incomplete_actual_time:
            raise RuntimeError(
                "CostLine staff/entry_seq backfill left "
                f"{incomplete_actual_time} actual time entries incomplete."
            )

        cursor.execute("""
            SELECT COUNT(*)
            FROM (
                SELECT cl.staff_id, cl.accounting_date, cl.entry_seq, COUNT(*) AS n
                FROM job_costline cl
                JOIN job_costset cs ON cl.cost_set_id = cs.id
                WHERE cs.kind = 'actual'
                  AND cl.kind = 'time'
                GROUP BY cl.staff_id, cl.accounting_date, cl.entry_seq
                HAVING COUNT(*) > 1
            ) duplicates
            """)
        duplicate_sequences = cursor.fetchone()[0]
        if duplicate_sequences:
            raise RuntimeError(
                "CostLine staff/entry_seq backfill produced "
                f"{duplicate_sequences} duplicate staff/day/sequence groups."
            )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("job", "0086_repoint_stale_time_pay_items"),
    ]

    operations = [
        migrations.AddField(
            model_name="costline",
            name="entry_seq",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Sequence number within a staff member's daily actual time entries.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="costline",
            name="staff",
            field=models.ForeignKey(
                blank=True,
                help_text="Staff member for actual time entries.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="cost_lines",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(
            backfill_actual_time_staff_and_sequence,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddIndex(
            model_name="costline",
            index=models.Index(
                fields=["staff", "accounting_date", "entry_seq"],
                name="job_costlin_staff_i_2efa8d_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="costline",
            constraint=models.UniqueConstraint(
                condition=Q(
                    kind="time",
                    staff__isnull=False,
                    entry_seq__isnull=False,
                ),
                fields=("staff", "accounting_date", "entry_seq"),
                name="unique_time_entry_staff_day_seq",
            ),
        ),
        migrations.AddConstraint(
            model_name="costline",
            constraint=models.CheckConstraint(
                condition=(
                    Q(staff__isnull=True, entry_seq__isnull=True)
                    | Q(staff__isnull=False, entry_seq__isnull=False)
                ),
                name="costline_staff_entry_seq_pair",
            ),
        ),
    ]
