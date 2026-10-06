"""Repair the two shapes of restored purchase order Xero refuses.

A purchase order line is one of two things: an item code the stock list
carries, or a description with no code (owner ruling, 2026-10-04). Five
production lines name a code no stock item has, and Xero answers an order
holding one with ``Item code '...' is not valid``. They become the second
kind of line: the description, quantity and cost are untouched.

Five production orders have an expected delivery in the year 0025, a
two-digit year stored as typed. Xero answers ``The date 8/20/0025 is not
valid``. The century is restored; nothing else about the date moves.

Both were found when the restore seed first sent every order to Xero, and
both are repaired here rather than tolerated by the seed (ADR 0059). The
reverse is a no-op: the code and the year that were there are not worth
putting back.
"""

from django.db import migrations

BLANK_UNKNOWN_ITEM_CODES_SQL = """
UPDATE purchasing_purchaseorderline AS line
SET item_code = NULL
WHERE line.item_code IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM purchasing_stock AS stock WHERE stock.item_code = line.item_code
  )
"""

RESTORE_CENTURY_SQL = """
UPDATE purchasing_purchaseorder
SET expected_delivery = expected_delivery + INTERVAL '2000 years'
WHERE expected_delivery < DATE '0100-01-01'
"""


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0020_purchaseorderevent_shares_the_audit_base"),
    ]

    operations = [
        migrations.RunSQL(BLANK_UNKNOWN_ITEM_CODES_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(RESTORE_CENTURY_SQL, migrations.RunSQL.noop),
    ]
