import re

from django.db import migrations, models


def normalize_phone(value):
    digits = re.sub(r"\D+", "", str(value or ""))
    if not digits:
        return ""
    if digits.startswith("64"):
        return f"+{digits}"
    if digits.startswith("0") and len(digits) > 1:
        return f"+64{digits[1:]}"
    return f"+{digits}"


def backfill_normalized_numbers(apps, schema_editor):
    PhoneCallRecord = apps.get_model("crm", "PhoneCallRecord")
    updates = []
    for call in PhoneCallRecord.objects.all().iterator():
        call.normalized_origin = normalize_phone(call.origin)
        call.normalized_destination = normalize_phone(call.destination)
        updates.append(call)
        if len(updates) >= 1000:
            PhoneCallRecord.objects.bulk_update(
                updates,
                ["normalized_origin", "normalized_destination"],
            )
            updates = []
    if updates:
        PhoneCallRecord.objects.bulk_update(
            updates,
            ["normalized_origin", "normalized_destination"],
        )


def clear_ambiguous_unknown_external_numbers(apps, schema_editor):
    PhoneCallRecord = apps.get_model("crm", "PhoneCallRecord")
    PhoneCallRecord.objects.filter(direction="unknown").exclude(
        normalized_origin=""
    ).exclude(normalized_destination="").update(external_number="")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("crm", "0008_phone_call_number_indexes"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="phonecallrecord",
            name="crm_phone_origin_num_idx",
        ),
        migrations.RemoveIndex(
            model_name="phonecallrecord",
            name="crm_phone_dest_num_idx",
        ),
        migrations.AddField(
            model_name="phonecallrecord",
            name="normalized_origin",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="phonecallrecord",
            name="normalized_destination",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.RunPython(
            backfill_normalized_numbers,
            migrations.RunPython.noop,
        ),
        migrations.RunPython(
            clear_ambiguous_unknown_external_numbers,
            migrations.RunPython.noop,
        ),
        migrations.AddIndex(
            model_name="phonecallrecord",
            index=models.Index(
                fields=["normalized_origin"],
                name="crm_phone_origin_norm_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="phonecallrecord",
            index=models.Index(
                fields=["normalized_destination"],
                name="crm_phone_dest_norm_idx",
            ),
        ),
    ]
