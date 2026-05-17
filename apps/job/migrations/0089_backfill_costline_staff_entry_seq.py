from django.db import migrations


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
              AND cl.meta->>'staff_id' IS NULL
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
              ON (cl.meta->>'staff_id')::uuid = staff.id
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
            SET staff_id = (cl.meta->>'staff_id')::uuid
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
    dependencies = [
        ("job", "0088_reclassify_stock_consumption_costlines"),
    ]

    operations = [
        migrations.RunPython(
            backfill_actual_time_staff_and_sequence,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
