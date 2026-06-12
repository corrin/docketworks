import os

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps
from django.utils import timezone

SUPPLIER_NAME = "S&T Stainless Limited"
SCRAPER_CLASS = "apps.quoting.scrapers.steel_and_tube.SteelAndTubeScraper"
PORTAL_URL = "https://portal.steelandtube.co.nz/"


def migrate_steel_and_tube_credentials(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    username = os.getenv("STEEL_TUBE_USERNAME")
    password = os.getenv("STEEL_TUBE_PASSWORD")
    if not username or not password:
        return

    Client = apps.get_model("client", "Client")
    SupplierCredential = apps.get_model("quoting", "SupplierCredential")
    SupplierScraperConfig = apps.get_model("quoting", "SupplierScraperConfig")

    supplier, created = Client.objects.get_or_create(
        name=SUPPLIER_NAME,
        defaults={
            "is_supplier": True,
            "xero_last_modified": timezone.now(),
        },
    )
    if not created and not supplier.is_supplier:
        supplier.is_supplier = True
        supplier.save(update_fields=["is_supplier"])

    credential, _ = SupplierCredential.objects.update_or_create(
        supplier=supplier,
        label="Steel & Tube portal",
        defaults={
            "credential_type": "username_password",
            "username": username,
            "password": password,
            "is_active": True,
        },
    )

    SupplierScraperConfig.objects.update_or_create(
        supplier=supplier,
        defaults={
            "scraper_class": SCRAPER_CLASS,
            "portal_url": PORTAL_URL,
            "is_enabled": True,
            "active_credential": credential,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("quoting", "0020_suppliercredential_supplierscraperconfig_and_more"),
    ]

    operations = [
        migrations.RunPython(
            migrate_steel_and_tube_credentials,
            migrations.RunPython.noop,
        ),
    ]
