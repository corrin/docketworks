import re

from django.db import migrations


def normalize_phone(value):
    digits = re.sub(r"\D+", "", str(value or ""))
    if not digits:
        return ""
    if digits.startswith("64"):
        return f"+{digits}"
    if digits.startswith("0") and len(digits) > 1:
        return f"+64{digits[1:]}"
    return f"+{digits}"


def phone_value_from_xero_item(item):
    if not isinstance(item, dict):
        return ""
    return (
        item.get("number")
        or item.get("phone_number")
        or item.get("PhoneNumber")
        or item.get("PhoneNumberString")
        or ""
    )


def label_from_xero_item(item):
    if not isinstance(item, dict):
        return ""
    return item.get("type") or item.get("phone_type") or item.get("PhoneType") or ""


def add_phone_method(
    ContactMethod,
    *,
    client=None,
    contact=None,
    value,
    label="",
    is_primary=False,
):
    normalized = normalize_phone(value)
    if not normalized:
        return

    owner_filter = {"contact": contact, "client": None} if contact else {
        "client": client,
        "contact": None,
    }
    method, created = ContactMethod.objects.get_or_create(
        **owner_filter,
        method_type="phone",
        normalized_value=normalized,
        defaults={
            "value": str(value).strip(),
            "label": label,
            "is_primary": is_primary,
            "source": "imported",
        },
    )
    if not created and is_primary and not method.is_primary:
        method.is_primary = True
        method.save(update_fields=["is_primary", "updated_at"])


def migrate_scalar_phones(apps, schema_editor):
    Client = apps.get_model("client", "Client")
    ClientContact = apps.get_model("client", "ClientContact")
    ContactMethod = apps.get_model("client", "ClientContactMethod")

    for client in Client.objects.all().iterator():
        add_phone_method(
            ContactMethod,
            client=client,
            value=client.phone,
            label="Main",
            is_primary=True,
        )
        if isinstance(client.all_phones, list):
            for item in client.all_phones:
                add_phone_method(
                    ContactMethod,
                    client=client,
                    value=phone_value_from_xero_item(item),
                    label=label_from_xero_item(item),
                )

    for contact in ClientContact.objects.filter(is_active=True).iterator():
        add_phone_method(
            ContactMethod,
            contact=contact,
            value=contact.phone,
            label="Main",
            is_primary=True,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0006_phone_endpoints_and_classification"),
        ("client", "0022_client_name_trgm_index"),
    ]

    operations = [
        migrations.RunPython(migrate_scalar_phones, migrations.RunPython.noop),
        migrations.RemoveField(model_name="client", name="phone"),
        migrations.RemoveField(model_name="client", name="all_phones"),
        migrations.RemoveField(model_name="clientcontact", name="phone"),
    ]
