"""Repair JobEvent.staff_id on installs where 0075 ran before it was fixed.

Migration 0075 originally created JobEvents without propagating
HistoricalJob.history_user_id into JobEvent.staff_id. On installs where
that first version of 0075 has already been applied, ~38,629 events have
staff_id IS NULL. This migration joins each NULL JobEvent to the nearest
HistoricalJob record (within +/- 1 minute of the event timestamp) on the
same job_id, and copies history_user_id into staff_id.

A further ~2,411 events cannot be repaired because the matching
HistoricalJob row was itself anonymous (history_user_id IS NULL). We do
not fabricate attribution; those rows are deleted.

Idempotent: UPDATE filters on staff_id IS NULL, so a re-run is a no-op
on fresh installs where 0075 already populated staff_id correctly.

Data only. The NOT NULL schema constraint lands in migration 0079, once
this migration's result has been verified on dev.
"""

from django.db import migrations

REPAIR_SQL = """
UPDATE job_jobevent e
SET staff_id = h.history_user_id
FROM (
  SELECT DISTINCT ON (e2.id) e2.id AS event_id, h.history_user_id
  FROM job_jobevent e2
  JOIN job_historicaljob h
    ON h.id = e2.job_id
   AND h.history_date BETWEEN e2.timestamp - interval '1 minute'
                          AND e2.timestamp + interval '1 minute'
   AND h.history_user_id IS NOT NULL
  WHERE e2.staff_id IS NULL
  ORDER BY e2.id, abs(extract(epoch from h.history_date - e2.timestamp))
) h
WHERE e.id = h.event_id;
"""

DELETE_SQL = """
DELETE FROM job_jobevent WHERE staff_id IS NULL;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("job", "0077_backfill_jobevent_detail"),
    ]

    operations = [
        migrations.RunSQL(REPAIR_SQL, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(DELETE_SQL, reverse_sql=migrations.RunSQL.noop),
    ]
