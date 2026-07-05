import re

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps
from django.db.models import Model


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if not digits:
        return ""
    if digits.startswith("64"):
        return f"+{digits}"
    if digits.startswith("0") and len(digits) > 1:
        return f"+64{digits[1:]}"
    return f"+{digits}"


def phone_value_from_xero_item(item: dict[str, str]) -> str:
    if not isinstance(item, dict):
        return ""
    return (
        item.get("number")
        or item.get("phone_number")
        or item.get("PhoneNumber")
        or item.get("PhoneNumberString")
        or ""
    )


def label_from_xero_item(item: dict[str, str]) -> str:
    if not isinstance(item, dict):
        return ""
    return item.get("type") or item.get("phone_type") or item.get("PhoneType") or ""


def add_phone_method(
    apps: StateApps,
    *,
    client: Model | None = None,
    contact: Model | None = None,
    value: str,
    label: str = "",
    is_primary: bool = False,
) -> None:
    ContactMethod = apps.get_model("client", "ClientContactMethod")
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


def migrate_scalar_phones(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    Client = apps.get_model("client", "Client")
    ClientContact = apps.get_model("client", "ClientContact")

    for client in Client.objects.all().iterator():
        add_phone_method(
            apps,
            client=client,
            value=client.phone,
            label="Main",
            is_primary=True,
        )
        if isinstance(client.all_phones, list):
            for item in client.all_phones:
                add_phone_method(
                    apps,
                    client=client,
                    value=phone_value_from_xero_item(item),
                    label=label_from_xero_item(item),
                )

    # Every contact, including soft-deleted (is_active=False) ones: RemoveField
    # drops the column for all rows, and Jobs keep FKs to inactive contacts, so
    # skipping them would destroy their phone numbers irreversibly.
    for contact in ClientContact.objects.all().iterator():
        add_phone_method(
            apps,
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
