"""Supplier portal scraping: everything that is ours rather than Chrome's.

The run orchestration, exercised through ``ScriptedScraper`` — a ``BaseScraper``
subclass whose four abstract methods return canned data instead of driving a
browser. That is the point of the seam: the ``ScrapeJob`` lifecycle, the
sitemap-versus-database URL diff, batched persistence and the end-of-run LLM fill
are testable with no browser and no Chrome binary anywhere near them. The
browser half (``SeleniumScraper``) and the one concrete site live in
``test_steel_and_tube.py``, mocked at the WebDriver boundary.

The LLM is mocked at ``LLM_BOUNDARY`` wherever a run reaches the end-of-run
fill, so no test here depends on the state of that (defective — see
``test_product_parser.TestScraperEndOfRunFillIsBroken``) code path.
"""

import re
from collections.abc import Sequence
from decimal import Decimal
from typing import ClassVar
from unittest.mock import patch

import pytest
from django.core.management import call_command

from apps.company.models import Company
from apps.company.tests.conftest import make_company
from apps.core.models import AppError
from apps.quoting.models import (
    ProductParsingMapping,
    ScrapeJob,
    SupplierCredential,
    SupplierPriceList,
    SupplierProduct,
    SupplierScraperConfig,
)
from apps.quoting.scrapers import BaseScraper, ScrapedProduct, resolve_scraper
from apps.quoting.tests.conftest import LLM_BOUNDARY, llm_reply, make_price_list

pytestmark = [pytest.mark.django_db]

SHS = "50x50x3 SHS Mild Steel"


def scraped(
    url: str,
    *,
    item_no: str = "SHS-50",
    variant: str = "v1",
    variant_price: Decimal | None = None,
    variant_available_stock: int | None = None,
) -> ScrapedProduct:
    """One variant as a scraper would hand it over."""
    return ScrapedProduct(
        item_no=item_no,
        variant_id=variant,
        product_name=SHS,
        url=url,
        description=SHS,
        variant_price=variant_price,
        variant_available_stock=variant_available_stock,
    )


class ScriptedScraper(BaseScraper):
    """A BaseScraper with the Selenium seam filled by a script, not a browser."""

    def __init__(
        self,
        supplier: Company,
        *,
        limit: int | None = None,
        force: bool = False,
        refresh_old: bool = False,
    ) -> None:
        super().__init__(supplier, limit=limit, force=force, refresh_old=refresh_old)
        self.published: list[str] = []
        self.pages: dict[str, Sequence[ScrapedProduct] | Exception] = {}
        self.login_error: Exception | None = None
        self.events: list[str] = []

    def open_browser(self) -> None:
        self.events.append("open")

    def close_browser(self) -> None:
        self.events.append("close")

    def login(self) -> None:
        self.events.append("login")
        if self.login_error is not None:
            raise self.login_error

    def product_urls(self) -> list[str]:
        return list(self.published)

    def scrape_product(self, url: str) -> Sequence[ScrapedProduct]:
        self.events.append(f"scrape:{url}")
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return page


@pytest.fixture
def scraper(supplier: Company) -> ScriptedScraper:
    """A scripted scraper for the fixture supplier, with nothing published yet."""
    return ScriptedScraper(supplier)


def make_product(
    supplier: Company,
    price_list: SupplierPriceList,
    url: str,
    *,
    variant: str = "v1",
    is_discontinued: bool = False,
) -> SupplierProduct:
    """A SupplierProduct already in the database, as a previous run left it."""
    return SupplierProduct.objects.create(
        supplier=supplier,
        price_list=price_list,
        product_name=SHS,
        item_no="SHS-50",
        variant_id=variant,
        url=url,
        is_discontinued=is_discontinued,
    )


class TestScrapedProductGuards:
    """v1 filtered placeholder identifiers downstream with ``in ["N/A", "", None]``."""

    @pytest.mark.parametrize("item_no", ["", "N/A"])
    def test_a_product_with_no_real_item_number_is_refused_at_construction(
        self, item_no: str
    ) -> None:
        with pytest.raises(ValueError, match="no item_no"):
            ScrapedProduct(
                item_no=item_no, variant_id="v1", product_name=SHS, url="https://example.test/a"
            )

    @pytest.mark.parametrize("variant_id", ["", "N/A"])
    def test_a_product_with_no_real_variant_id_is_refused_at_construction(
        self, variant_id: str
    ) -> None:
        with pytest.raises(ValueError, match="no variant_id"):
            ScrapedProduct(
                item_no="SHS-50",
                variant_id=variant_id,
                product_name=SHS,
                url="https://example.test/a",
            )

    def test_the_message_names_the_page_the_operator_has_to_go_and_look_at(self) -> None:
        with pytest.raises(ValueError, match=re.escape("https://example.test/broken")):
            ScrapedProduct(
                item_no="N/A",
                variant_id="v1",
                product_name=SHS,
                url="https://example.test/broken",
            )


class TestSelectUrls:
    """The sitemap-versus-database diff: what a run visits, and what it retires."""

    def test_by_default_only_urls_never_seen_before_are_visited(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        price_list = make_price_list(supplier)
        make_product(supplier, price_list, "https://example.test/known")

        selected = scraper.select_urls(["https://example.test/known", "https://example.test/new"])

        assert selected == ["https://example.test/new"]

    def test_force_visits_everything_published(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        price_list = make_price_list(supplier)
        make_product(supplier, price_list, "https://example.test/known")
        scraper.force = True

        selected = scraper.select_urls(["https://example.test/known", "https://example.test/new"])

        assert selected == ["https://example.test/known", "https://example.test/new"]

    def test_refresh_old_revisits_known_urls_and_retires_the_ones_that_vanished(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        price_list = make_price_list(supplier)
        still_listed = make_product(supplier, price_list, "https://example.test/known")
        vanished = make_product(supplier, price_list, "https://example.test/gone", variant="v2")
        scraper.refresh_old = True

        selected = scraper.select_urls(["https://example.test/known", "https://example.test/new"])

        assert selected == ["https://example.test/known", "https://example.test/new"]
        vanished.refresh_from_db()
        still_listed.refresh_from_db()
        assert vanished.is_discontinued is True
        assert still_listed.is_discontinued is False

    def test_refresh_old_un_retires_a_product_that_came_back(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        price_list = make_price_list(supplier)
        returned = make_product(
            supplier, price_list, "https://example.test/back", is_discontinued=True
        )
        scraper.refresh_old = True

        scraper.select_urls(["https://example.test/back"])

        returned.refresh_from_db()
        assert returned.is_discontinued is False

    def test_another_suppliers_products_are_never_retired(self, scraper: ScriptedScraper) -> None:
        other = make_company("Other Supplier", is_supplier=True)
        theirs = make_product(other, make_price_list(other), "https://example.test/gone")
        scraper.refresh_old = True

        scraper.select_urls(["https://example.test/new"])

        theirs.refresh_from_db()
        assert theirs.is_discontinued is False

    def test_the_limit_is_a_throttle_applied_to_the_sorted_selection(
        self, scraper: ScriptedScraper
    ) -> None:
        scraper.limit = 2

        selected = scraper.select_urls(
            ["https://example.test/c", "https://example.test/a", "https://example.test/b"]
        )

        assert selected == ["https://example.test/a", "https://example.test/b"]


class TestSaveProducts:
    def test_a_new_variant_is_stored_and_its_mapping_reserved(self, supplier: Company) -> None:
        price_list = make_price_list(supplier)
        scraper = ScriptedScraper(supplier)

        scraper.save_products(
            price_list,
            [scraped("https://example.test/shs-50", variant_price=Decimal("45.20"))],
        )

        product = SupplierProduct.objects.get()
        assert product.variant_price == Decimal("45.20")
        assert product.mapping_hash is not None
        assert ProductParsingMapping.objects.filter(input_hash=product.mapping_hash).exists()

    def test_a_second_run_updates_the_row_rather_than_duplicating_it(
        self, supplier: Company
    ) -> None:
        price_list = make_price_list(supplier)
        scraper = ScriptedScraper(supplier)
        scraper.save_products(
            price_list,
            [scraped("https://example.test/shs-50", variant_price=Decimal("45.20"))],
        )

        scraper.save_products(
            price_list,
            [
                scraped(
                    "https://example.test/shs-50",
                    variant_price=Decimal("47.00"),
                    variant_available_stock=12,
                )
            ],
        )

        product = SupplierProduct.objects.get()
        assert product.variant_price == Decimal("47.00")
        assert product.variant_available_stock == 12
        # The description did not change, so the mapping is not re-reserved.
        assert ProductParsingMapping.objects.count() == 1


class TestRun:
    """The ScrapeJob lifecycle: one row per run, whatever the outcome."""

    def _script(self, scraper: ScriptedScraper, pages: dict[str, list[ScrapedProduct]]) -> None:
        scraper.published = sorted(pages)
        scraper.pages = dict(pages)

    def test_a_clean_run_is_recorded_completed_with_its_counts(
        self, scraper: ScriptedScraper
    ) -> None:
        self._script(
            scraper,
            {
                "https://example.test/shs": [scraped("https://example.test/shs")],
                "https://example.test/rhs": [
                    scraped("https://example.test/rhs", item_no="RHS-100")
                ],
            },
        )

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "SHS-50"})):
            job = scraper.run()

        assert job.status == "completed"
        assert job.products_scraped == 2
        assert job.products_failed == 0
        assert job.completed_at is not None
        assert SupplierProduct.objects.count() == 2
        assert SupplierPriceList.objects.count() == 1
        assert ScrapeJob.objects.count() == 1

    def test_the_browser_is_opened_and_always_closed(self, scraper: ScriptedScraper) -> None:
        self._script(scraper, {"https://example.test/shs": [scraped("https://example.test/shs")]})

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "SHS-50"})):
            scraper.run()

        assert scraper.events[0] == "open"
        assert scraper.events[1] == "login"
        assert scraper.events[-1] == "close"

    def test_a_login_failure_fails_the_job_closes_the_browser_and_re_raises(
        self, scraper: ScriptedScraper
    ) -> None:
        scraper.published = ["https://example.test/shs"]
        scraper.login_error = RuntimeError("Portal refused the credentials")

        with pytest.raises(RuntimeError, match="Portal refused the credentials"):
            scraper.run()

        job = ScrapeJob.objects.get()
        assert job.status == "failed"
        assert job.error_message == "Portal refused the credentials"
        assert job.completed_at is not None
        assert scraper.events[-1] == "close"
        assert AppError.objects.filter(message="Portal refused the credentials").exists()

    def test_an_empty_sitemap_fails_the_job_without_raising(self, scraper: ScriptedScraper) -> None:
        """Nothing published is a supplier-side condition, not a crash."""
        scraper.published = []

        job = scraper.run()

        assert job.status == "failed"
        assert job.error_message == "No product URLs found"
        assert scraper.events[-1] == "close"
        assert SupplierProduct.objects.count() == 0

    def test_one_unreadable_page_is_counted_and_the_run_continues(
        self, scraper: ScriptedScraper
    ) -> None:
        scraper.published = ["https://example.test/bad", "https://example.test/good"]
        scraper.pages = {
            "https://example.test/bad": ValueError("Variant table missing"),
            "https://example.test/good": [scraped("https://example.test/good")],
        }

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "SHS-50"})):
            job = scraper.run()

        assert job.status == "completed"
        assert job.products_scraped == 1
        assert job.products_failed == 1
        assert SupplierProduct.objects.count() == 1
        assert AppError.objects.filter(message="Variant table missing").exists()

    def test_a_page_with_no_variants_counts_as_a_failure(self, scraper: ScriptedScraper) -> None:
        scraper.published = ["https://example.test/empty"]
        scraper.pages = {"https://example.test/empty": []}

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "SHS-50"})):
            job = scraper.run()

        assert job.products_scraped == 0
        assert job.products_failed == 1

    def test_products_are_saved_in_batches_during_a_long_run(
        self, scraper: ScriptedScraper, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A full scrape is thousands of variants; nothing waits for the end."""
        monkeypatch.setattr("apps.quoting.scrapers.base.SAVE_BATCH_SIZE", 2)
        urls = [f"https://example.test/p{index}" for index in range(5)]
        scraper.published = urls
        scraper.pages = {
            url: [scraped(url, item_no=f"SHS-{index}")] for index, url in enumerate(urls)
        }

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "SHS-50"})):
            job = scraper.run()

        assert job.products_scraped == 5
        assert SupplierProduct.objects.count() == 5

    def test_a_failing_end_of_run_llm_fill_does_not_fail_the_run(
        self, scraper: ScriptedScraper
    ) -> None:
        """The scrape is the valuable part; parsing can be retried (v1 behaviour)."""
        self._script(scraper, {"https://example.test/shs": [scraped("https://example.test/shs")]})

        with patch(
            "apps.quoting.scrapers.base.populate_all_mappings_with_llm",
            side_effect=RuntimeError("Gemini is down"),
        ):
            job = scraper.run()

        assert job.status == "completed"
        assert job.products_scraped == 1
        assert AppError.objects.filter(message="Gemini is down").exists()


class TestCredentials:
    def test_the_enabled_config_supplies_the_portal_credentials(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        credential = SupplierCredential.objects.create(
            supplier=supplier,
            label="Portal login",
            credential_type=SupplierCredential.CredentialType.USERNAME_PASSWORD,
            username="scraper@example.test",
            password="hunter2",
        )
        SupplierScraperConfig.objects.create(
            supplier=supplier,
            scraper_class="apps.quoting.tests.test_scrapers.ScriptedScraper",
            portal_url="https://portal.example.test/",
            active_credential=credential,
        )

        assert scraper.credentials() == {
            "username": "scraper@example.test",
            "password": "hunter2",
        }

    def test_a_supplier_with_no_enabled_config_is_a_loud_failure(
        self, scraper: ScriptedScraper
    ) -> None:
        with pytest.raises(SupplierScraperConfig.DoesNotExist):
            scraper.credentials()


class TestResolveScraper:
    """One lookup mechanism: the stored dotted path, imported."""

    def test_a_stored_dotted_path_resolves_to_its_class(self) -> None:
        resolved = resolve_scraper("apps.quoting.tests.test_scrapers.ScriptedScraper")

        assert resolved is ScriptedScraper

    def test_a_bare_class_name_is_refused_with_an_example(self) -> None:
        with pytest.raises(ValueError, match="is not a dotted path"):
            resolve_scraper("ScriptedScraper")

    def test_a_class_that_is_not_a_scraper_is_refused(self) -> None:
        with pytest.raises(TypeError, match="is not a BaseScraper subclass"):
            resolve_scraper("apps.quoting.models.SupplierProduct")


class CommandScraper(BaseScraper):
    """A scraper the management command can construct: BaseScraper's own signature."""

    runs: ClassVar[list[str]] = []
    fail_for: ClassVar[set[str]] = set()

    def open_browser(self) -> None:
        pass

    def close_browser(self) -> None:
        pass

    def login(self) -> None:
        if self.supplier.name in self.fail_for:
            raise RuntimeError(f"{self.supplier.name} portal is down")

    def product_urls(self) -> list[str]:
        CommandScraper.runs.append(self.supplier.name)
        return [f"https://example.test/{self.supplier.name}"]

    def scrape_product(self, url: str) -> Sequence[ScrapedProduct]:
        return [scraped(url, item_no=f"ITEM-{self.supplier.name}")]


class SecondCommandScraper(CommandScraper):
    """A second class, because SupplierScraperConfig.scraper_class is unique."""


COMMAND_SCRAPER = "apps.quoting.tests.test_scrapers.CommandScraper"
SECOND_COMMAND_SCRAPER = "apps.quoting.tests.test_scrapers.SecondCommandScraper"


@pytest.fixture
def _reset_command_scraper() -> None:
    CommandScraper.runs = []
    CommandScraper.fail_for = set()


def make_config(supplier: Company, *, dotted_path: str, enabled: bool = True) -> None:
    """Enable a scraper for a supplier."""
    credential = SupplierCredential.objects.create(
        supplier=supplier,
        label=f"{supplier.name} portal",
        credential_type=SupplierCredential.CredentialType.API_KEY,
        api_key="portal-key",
    )
    SupplierScraperConfig.objects.create(
        supplier=supplier,
        scraper_class=dotted_path,
        portal_url="https://portal.example.test/",
        active_credential=credential,
        is_enabled=enabled,
    )


@pytest.mark.usefixtures("_reset_command_scraper")
class TestRunScrapersCommand:
    def test_every_enabled_config_runs(self, supplier: Company) -> None:
        make_config(supplier, dotted_path=COMMAND_SCRAPER)

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "SHS-50"})):
            call_command("run_scrapers")

        assert CommandScraper.runs == [supplier.name]
        assert ScrapeJob.objects.get().status == "completed"

    def test_a_disabled_config_is_skipped(self, supplier: Company) -> None:
        make_config(supplier, dotted_path=COMMAND_SCRAPER, enabled=False)

        with pytest.raises(SupplierScraperConfig.DoesNotExist):
            call_command("run_scrapers")

        assert CommandScraper.runs == []

    def test_the_supplier_filter_narrows_the_run(self, supplier: Company) -> None:
        other = make_company("Vulcan Steel", is_supplier=True)
        make_config(supplier, dotted_path=COMMAND_SCRAPER)
        make_config(other, dotted_path=SECOND_COMMAND_SCRAPER)

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "SHS-50"})):
            call_command("run_scrapers", supplier="Vulcan")

        assert CommandScraper.runs == ["Vulcan Steel"]

    def test_no_matching_config_is_a_loud_failure_naming_the_filters(
        self, supplier: Company
    ) -> None:
        make_config(supplier, dotted_path=COMMAND_SCRAPER)

        with pytest.raises(SupplierScraperConfig.DoesNotExist, match="NoSuchScraper"):
            call_command("run_scrapers", scraper="NoSuchScraper")

    def test_one_broken_supplier_does_not_cancel_the_others(self, supplier: Company) -> None:
        """The weekly run must finish; the failure lands on the job row and an AppError."""
        other = make_company("Vulcan Steel", is_supplier=True)
        make_config(supplier, dotted_path=COMMAND_SCRAPER)
        make_config(other, dotted_path=SECOND_COMMAND_SCRAPER)
        CommandScraper.fail_for = {supplier.name}

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "SHS-50"})):
            call_command("run_scrapers")

        assert CommandScraper.runs == ["Vulcan Steel"]
        statuses = dict(ScrapeJob.objects.values_list("supplier__name", "status"))
        assert statuses == {supplier.name: "failed", "Vulcan Steel": "completed"}
        assert AppError.objects.filter(message=f"{supplier.name} portal is down").exists()
