"""Backfill JobEvent.delta_before/delta_after on legacy status_changed events.

Source: detail.changes[0].old_value / new_value, populated by migration 0077.

Migration 0075 was meant to populate delta_before/delta_after for these events
from HistoricalJob, but HistoricalJob is empty in this DB, so 0075 was a no-op
for status_changed rows whose corresponding HistoricalJob records never
existed. The status values are still preserved in detail.changes (written by
0077's regex parsers), so delta_after.status is recoverable in-row.

Census against the prod-restore DB: 1,299 status_changed rows match
(delta_after IS NULL AND detail->'changes'->0->>'field_name' = 'Status').
All have non-empty new_value AND old_value.

Slug normalisation: lower-case + spaces-to-underscores. Most values are
already slugs and pass through unchanged. Two display-label outliers
('Recently Completed', 'Archived') normalise to 'recently_completed' /
'archived'. Historical statuses no longer in the current Job.Status enum
(e.g. 'completed', 'accepted_quote', 'awaiting_materials') are real past
states and are preserved as-is.

Idempotent: WHERE delta_after IS NULL means a re-run touches nothing already
populated. The same predicate guards skipping rows whose detail.changes shape
is unexpected — they remain NULL, which is the starting state, so no harm.
"""

from django.db import migrations

BACKFILL_SQL = """
UPDATE job_jobevent
SET delta_before = jsonb_build_object(
        'status',
        lower(replace(detail->'changes'->0->>'old_value', ' ', '_'))
    ),
    delta_after  = jsonb_build_object(
        'status',
        lower(replace(detail->'changes'->0->>'new_value', ' ', '_'))
    )
WHERE event_type = 'status_changed'
  AND delta_after IS NULL
  AND detail->'changes'->0->>'field_name' = 'Status'
  AND detail->'changes'->0->>'old_value' IS NOT NULL
  AND detail->'changes'->0->>'old_value' <> ''
  AND detail->'changes'->0->>'new_value' IS NOT NULL
  AND detail->'changes'->0->>'new_value' <> '';
"""


class Migration(migrations.Migration):

    dependencies = [
        ("job", "0079_alter_jobevent_staff_not_null"),
    ]

    operations = [
        migrations.RunSQL(BACKFILL_SQL, reverse_sql=migrations.RunSQL.noop),
    ]
