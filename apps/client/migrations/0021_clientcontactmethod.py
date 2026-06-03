import re
import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


def normalize_phone(value):
    digits = re.sub(r"\D+", "", str(value or ""))
    if not digits:
        return ""
    if digits.startswith("64"):
        return f"+{digits}"
    if digits.startswith("0") and len(digits) > 1:
        return f"+64{digits[1:]}"
    return f"+{digits}"


def normalize_value(method_type, value):
    if method_type == "phone":
        return normalize_phone(value)
    if method_type == "email":
        return str(value or "").strip().lower()
    raise ValueError(f"unknown contact method type: {method_type}")


def add_contact_method(
    methods,
    *,
    client_id=None,
    contact_id=None,
    method_type,
    value,
    label="",
    is_primary=False,
):
    normalized = normalize_value(method_type, value)
    if not normalized:
        return

    owner_kind = "contact" if contact_id else "client"
    owner_id = contact_id or client_id
    key = (
        owner_kind,
        owner_id,
        method_type,
        normalized,
    )
    if key in methods:
        if is_primary:
            methods[key]["is_primary"] = True
        return

    methods[key] = {
        "client_id": client_id,
        "contact_id": contact_id,
        "method_type": method_type,
        "value": str(value).strip(),
        "normalized_value": normalized,
        "label": label,
        "is_primary": is_primary,
        "source": "imported",
    }


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


def backfill_contact_methods(apps, schema_editor):
    Client = apps.get_model("client", "Client")
    ClientContact = apps.get_model("client", "ClientContact")
    ContactMethod = apps.get_model("client", "ClientContactMethod")
    methods = {}

    for client in Client.objects.all().iterator():
        add_contact_method(
            methods,
            client_id=client.id,
            method_type="email",
            value=client.email,
            label="Main",
            is_primary=True,
        )
        add_contact_method(
            methods,
            client_id=client.id,
            method_type="phone",
            value=client.phone,
            label="Main",
            is_primary=True,
        )

        if isinstance(client.all_phones, list):
            for item in client.all_phones:
                add_contact_method(
                    methods,
                    client_id=client.id,
                    method_type="phone",
                    value=phone_value_from_xero_item(item),
                    label=label_from_xero_item(item),
                    is_primary=False,
                )

    for contact in ClientContact.objects.filter(is_active=True).iterator():
        add_contact_method(
            methods,
            contact_id=contact.id,
            method_type="email",
            value=contact.email,
            label="Main",
            is_primary=True,
        )
        add_contact_method(
            methods,
            contact_id=contact.id,
            method_type="phone",
            value=contact.phone,
            label="Main",
            is_primary=True,
        )

    now = timezone.now()
    ContactMethod.objects.bulk_create(
        [
            ContactMethod(
                **method,
                created_at=now,
                updated_at=now,
            )
            for method in methods.values()
        ],
        batch_size=1000,
    )


def remove_contact_methods(apps, schema_editor):
    ContactMethod = apps.get_model("client", "ClientContactMethod")
    ContactMethod.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("client", "0020_suppliersearchalias_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClientContactMethod",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "method_type",
                    models.CharField(
                        choices=[("phone", "Phone"), ("email", "Email")],
                        max_length=20,
                    ),
                ),
                ("value", models.CharField(max_length=255)),
                ("normalized_value", models.CharField(db_index=True, max_length=255)),
                ("label", models.CharField(blank=True, max_length=255)),
                ("is_primary", models.BooleanField(default=False)),
                (
                    "source",
                    models.CharField(
                        choices=[("imported", "Imported"), ("local", "Local")],
                        default="local",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "client",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="contact_methods",
                        to="client.client",
                    ),
                ),
                (
                    "contact",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="contact_methods",
                        to="client.clientcontact",
                    ),
                ),
            ],
            options={
                "verbose_name": "Client Contact Method",
                "verbose_name_plural": "Client Contact Methods",
                "ordering": ["method_type", "-is_primary", "label", "value"],
            },
        ),
        migrations.AddConstraint(
            model_name="clientcontactmethod",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("client__isnull", False), ("contact__isnull", True))
                    | models.Q(("client__isnull", True), ("contact__isnull", False))
                ),
                name="client_contact_method_one_owner",
            ),
        ),
        migrations.AddConstraint(
            model_name="clientcontactmethod",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("client__isnull", False), ("contact__isnull", True)
                ),
                fields=("client", "method_type", "normalized_value"),
                name="unique_client_contact_method_value",
            ),
        ),
        migrations.AddConstraint(
            model_name="clientcontactmethod",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("client__isnull", True), ("contact__isnull", False)
                ),
                fields=("contact", "method_type", "normalized_value"),
                name="unique_contact_contact_method_value",
            ),
        ),
        migrations.AddConstraint(
            model_name="clientcontactmethod",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("client__isnull", False),
                    ("contact__isnull", True),
                    ("is_primary", True),
                ),
                fields=("client", "method_type"),
                name="unique_client_primary_contact_method",
            ),
        ),
        migrations.AddConstraint(
            model_name="clientcontactmethod",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("client__isnull", True),
                    ("contact__isnull", False),
                    ("is_primary", True),
                ),
                fields=("contact", "method_type"),
                name="unique_contact_primary_contact_method",
            ),
        ),
        migrations.RunPython(backfill_contact_methods, remove_contact_methods),
    ]
