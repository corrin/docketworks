"""Backfill JobEvent.delta_after on legacy job_created events.

Two sources, in order:

1. Chain: for each job_created event missing delta_after, find the earliest
   subsequent status_changed event for the same job. Take its
   delta_before.status (modern format) or detail.changes[0].old_value (legacy
   format) — whichever is populated. That value is the initial status of the
   job at creation time. After migration 0080 runs, all status_changed rows
   have delta_before populated, so the COALESCE always resolves via
   delta_before; the detail.changes path remains as a guard if 0081 is
   re-applied against partially-rolled state.

2. Current Job.status: for jobs that have never moved status (5 rows in the
   prod-restore DB), the linked Job's current status equals its initial
   status by construction.

job_created.delta_before stays NULL — creation events have no prior state.

Census: 954 job_created rows match (delta_after IS NULL). 949 have a
chainable subsequent event; 5 require the Job.status path.

Idempotent: WHERE delta_after IS NULL guards both UPDATE statements.
"""

from django.db import migrations

CHAIN_SQL = """
WITH chain AS (
  SELECT DISTINCT ON (c.id) c.id AS event_id,
         COALESCE(
             s.delta_before->>'status',
             s.detail->'changes'->0->>'old_value'
         ) AS source_value
  FROM job_jobevent c
  JOIN job_jobevent s
    ON s.job_id = c.job_id
   AND s.event_type = 'status_changed'
   AND s.timestamp > c.timestamp
  WHERE c.event_type = 'job_created'
    AND c.delta_after IS NULL
  ORDER BY c.id, s.timestamp ASC
)
UPDATE job_jobevent e
SET delta_after = jsonb_build_object(
    'status',
    lower(replace(chain.source_value, ' ', '_'))
)
FROM chain
WHERE e.id = chain.event_id
  AND e.delta_after IS NULL
  AND chain.source_value IS NOT NULL
  AND chain.source_value <> '';
"""


CURRENT_STATUS_SQL = """
UPDATE job_jobevent e
SET delta_after = jsonb_build_object('status', j.status)
FROM job_job j
WHERE e.event_type = 'job_created'
  AND e.delta_after IS NULL
  AND e.job_id = j.id;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("job", "0080_backfill_jobevent_status_delta"),
    ]

    operations = [
        migrations.RunSQL(CHAIN_SQL, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(CURRENT_STATUS_SQL, reverse_sql=migrations.RunSQL.noop),
    ]
