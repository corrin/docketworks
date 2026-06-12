from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.client.models import Client
from apps.quoting.management.commands.run_scrapers import Command
from apps.quoting.models import SupplierCredential, SupplierScraperConfig
from apps.quoting.scrapers.steel_and_tube import SteelAndTubeScraper
from apps.testing import BaseTestCase


class DummyScraper:
    pass


class SupplierScraperCredentialTests(BaseTestCase):
    def setUp(self) -> None:
        self.supplier = Client.objects.create(
            name="S&T Stainless Limited",
            is_supplier=True,
            xero_last_modified=timezone.now(),
        )

    def test_username_password_credential_dict(self) -> None:
        credential = SupplierCredential.objects.create(
            supplier=self.supplier,
            label="Portal",
            credential_type=SupplierCredential.CredentialType.USERNAME_PASSWORD,
            username="user@example.com",
            password="secret",
        )

        self.assertEqual(
            credential.get_credential_dict(),
            {"username": "user@example.com", "password": "secret"},
        )

    def test_username_password_requires_username_and_password(self) -> None:
        credential = SupplierCredential(
            supplier=self.supplier,
            label="Portal",
            credential_type=SupplierCredential.CredentialType.USERNAME_PASSWORD,
            username="user@example.com",
            password="",
        )

        with self.assertRaises(ValidationError) as context:
            credential.full_clean()

        self.assertIn("password", context.exception.message_dict)

    def test_supplier_scraper_config_requires_same_supplier_credential(self) -> None:
        other_supplier = Client.objects.create(
            name="Other Supplier",
            is_supplier=True,
            xero_last_modified=timezone.now(),
        )
        other_credential = SupplierCredential.objects.create(
            supplier=other_supplier,
            label="Portal",
            credential_type=SupplierCredential.CredentialType.USERNAME_PASSWORD,
            username="other@example.com",
            password="secret",
        )
        config = SupplierScraperConfig(
            supplier=self.supplier,
            scraper_class="apps.quoting.tests.test_supplier_scraper_credentials.InvalidScraper",
            portal_url="https://portal.steelandtube.co.nz/",
            active_credential=other_credential,
        )

        with self.assertRaises(ValidationError) as context:
            config.full_clean()

        self.assertIn("active_credential", context.exception.message_dict)

    def test_base_scraper_reads_credentials_from_active_config(self) -> None:
        credential = SupplierCredential.objects.create(
            supplier=self.supplier,
            label="Portal",
            credential_type=SupplierCredential.CredentialType.USERNAME_PASSWORD,
            username="user@example.com",
            password="secret",
        )
        SupplierScraperConfig.objects.create(
            supplier=self.supplier,
            scraper_class="apps.quoting.tests.test_supplier_scraper_credentials.BaseLookupScraper",
            portal_url="https://portal.steelandtube.co.nz/",
            active_credential=credential,
        )

        scraper = SteelAndTubeScraper(self.supplier)

        self.assertEqual(
            scraper.get_credentials(),
            {"username": "user@example.com", "password": "secret"},
        )

    def test_run_scrapers_finds_supplier_via_enabled_config(self) -> None:
        credential = SupplierCredential.objects.create(
            supplier=self.supplier,
            label="Portal",
            credential_type=SupplierCredential.CredentialType.USERNAME_PASSWORD,
            username="user@example.com",
            password="secret",
        )
        SupplierScraperConfig.objects.create(
            supplier=self.supplier,
            scraper_class=(
                "apps.quoting.tests.test_supplier_scraper_credentials.DummyScraper"
            ),
            portal_url="https://portal.steelandtube.co.nz/",
            active_credential=credential,
        )
        command = Command()

        config = command.find_config_for_scraper(
            {
                "class_obj": DummyScraper,
                "class_name": "DummyScraper",
            }
        )

        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config.supplier, self.supplier)
