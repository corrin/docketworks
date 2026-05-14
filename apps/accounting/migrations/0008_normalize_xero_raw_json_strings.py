import json

from django.db import migrations


def _underscore_keys(value):
    if isinstance(value, list):
        return [_underscore_keys(item) for item in value]
    if not isinstance(value, dict):
        return value

    normalized = {}
    for key, item in value.items():
        normalized_key = key if key.startswith("_") else f"_{key}"
        normalized[normalized_key] = _underscore_keys(item)
    return normalized


def _normalize_raw_json(value, model_name, row_id):
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return value

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{model_name} {row_id} raw_json is a non-JSON string"
        ) from exc

    if not isinstance(parsed, dict):
        raise ValueError(
            f"{model_name} {row_id} raw_json string did not decode to an object"
        )

    raw = parsed.get("full") if isinstance(parsed.get("full"), dict) else parsed
    return _underscore_keys(raw)


def normalize_raw_json_strings(apps, schema_editor):
    for app_label, model_name in (("accounting", "Invoice"), ("accounting", "Quote")):
        model = apps.get_model(app_label, model_name)
        for row in model.objects.all().only("id", "raw_json").iterator():
            normalized = _normalize_raw_json(row.raw_json, model_name, row.id)
            if normalized != row.raw_json:
                row.raw_json = normalized
                row.save(update_fields=["raw_json"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0007_partial_invoice_billing_metadata"),
    ]

    operations = [
        migrations.RunPython(normalize_raw_json_strings, migrations.RunPython.noop),
    ]
