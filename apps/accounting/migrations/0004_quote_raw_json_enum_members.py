"""Five mirrored quotes hold an enum's Python name where every other row holds its member.

``process_xero_data`` stores an SDK enum as the member's ``__dict__``
(``{"_name_": "DRAFT", "_value_": "DRAFT", "_sort_order_": 0}``), and every
reader — the renderer behind the fake Xero included — reads ``_value_``. Five
quotes created on 2025-11-17/18 carry ``str(member)`` instead
(``"QuoteStatusCodes.DRAFT"``, ``"QuoteLineAmountTypes.EXCLUSIVE"``), a shape
no current writer produces; this one-off migration is the only code that
knows it (ADR 0059, ADR 0015).
"""

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

_KEYS = {"_status": "QuoteStatusCodes", "_line_amount_types": "QuoteLineAmountTypes"}


def _member(enum_name: str, member_name: str) -> dict[str, object]:
    from xero_python import accounting  # noqa: PLC0415 -- resolved when the migration runs

    enum = getattr(accounting, enum_name)
    member = enum[member_name]
    return {
        "_name_": member.name,
        "_value_": member.value,
        "_sort_order_": list(enum).index(member),
    }


def forwards(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    del schema_editor
    quote_model = apps.get_model("accounting", "Quote")
    for quote in quote_model.objects.exclude(raw_json__isnull=True).iterator():
        raw = quote.raw_json
        changed = False
        for key, enum_name in _KEYS.items():
            value = raw.get(key)
            if isinstance(value, str) and value.startswith(f"{enum_name}."):
                raw[key] = _member(enum_name, value.removeprefix(f"{enum_name}."))
                changed = True
        if changed:
            quote.save(update_fields=["raw_json"])


class Migration(migrations.Migration):
    dependencies = [("accounting", "0003_backfill_quote_numbers_from_raw_json")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
