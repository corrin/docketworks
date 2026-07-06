"""Seed XeroPayItem records with fixed UUIDs matching production.

These UUIDs are canonical — they match the PKs used by production
Job.default_xero_pay_item and CostLine.xero_pay_item FKs. This means
backups can exclude XeroPayItem and the FK references still resolve.
Idempotent; reverse deletes the seeded rows. (Content carried over from
the pre-squash workflow/0187_create_xero_pay_item.)
"""

from decimal import Decimal

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

SEED_ITEMS: list[dict[str, str | bool | Decimal | None]] = [
    {
        "id": "3829750d-1528-440c-8260-0ce4a7b620f3",
        "name": "Ordinary Time",
        "uses_leave_api": False,
        "multiplier": Decimal("1.00"),
    },
    {
        "id": "adc9d1ba-5ba7-4692-b71f-785e36ce35c8",
        "name": "Time and one half",
        "uses_leave_api": False,
        "multiplier": Decimal("1.50"),
    },
    {
        "id": "8ad696a0-f0cd-42b4-9700-39a942d9ccfd",
        "name": "Double Time",
        "uses_leave_api": False,
        "multiplier": Decimal("2.00"),
    },
    {
        "id": "90909bb3-7c5f-473a-8b51-e4d5cfcb3a5a",
        "name": "Annual Leave",
        "uses_leave_api": True,
        "multiplier": None,
    },
    {
        "id": "e678e692-312d-4f38-b9f8-31c84d6d6ba8",
        "name": "Sick Leave",
        "uses_leave_api": True,
        "multiplier": None,
    },
    {
        "id": "b58930e0-2bb9-4dde-b7ec-5a16ea78b4cb",
        "name": "Unpaid Leave",
        "uses_leave_api": True,
        "multiplier": None,
    },
    {
        "id": "c4848bba-737e-45a8-adaa-61cd072a84ca",
        "name": "Bereavement Leave",
        "uses_leave_api": True,
        "multiplier": None,
    },
]


def create_seed_xero_pay_items(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    XeroPayItem = apps.get_model("workflow", "XeroPayItem")
    for item in SEED_ITEMS:
        if not XeroPayItem.objects.filter(id=item["id"]).exists():
            XeroPayItem.objects.create(**item)


def delete_seed_xero_pay_items(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    XeroPayItem = apps.get_model("workflow", "XeroPayItem")
    XeroPayItem.objects.filter(id__in=[item["id"] for item in SEED_ITEMS]).delete()


class Migration(migrations.Migration):
    replaces = [
        ("workflow", "0187_create_xero_pay_item"),
    ]

    dependencies = [
        ("workflow", "0001_baseline"),
    ]

    operations = [
        migrations.RunPython(create_seed_xero_pay_items, delete_seed_xero_pay_items),
    ]
