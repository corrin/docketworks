"""Supplier portal scraping: everything that is ours rather than Chrome's.

The run orchestration, exercised through ``ScriptedScraper`` — a ``BaseScraper``
subclass whose four abstract methods return canned data instead of driving a
browser. That is the point of the seam: the ``ScrapeJob`` lifecycle, the
sitemap-versus-database URL diff, batched persistence and the end-of-run LLM fill
are testable with no browser and no Chrome binary anywhere near them. The
browser half (``SeleniumScraper``) and the one concrete site live in
``test_steel_and_tube.py``, mocked at the WebDriver boundary.

The LLM is mocked at ``LLM_BOUNDARY`` wherever a run reaches the end-of-run
fill; the fill's own behaviour is asserted in
``test_product_parser.TestScraperEndOfRunFill``, not here.
"""

import re
from collections.abc import Sequence
from decimal import Decimal
from enum import Enum, auto
from typing import ClassVar
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import DatabaseError

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
from apps.quoting.scrapers.base import OPTIONAL_TEXT_FIELDS, ScrapeOutcome
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


def blank_in(field: str) -> ScrapedProduct:
    """A scraped product whose one named optional text column is blank, not None."""
    blanks: dict[str, str | None] = dict.fromkeys(OPTIONAL_TEXT_FIELDS)
    blanks[field] = ""
    return ScrapedProduct(
        item_no="SHS-50",
        variant_id="v1",
        product_name=SHS,
        url="https://example.test/a",
        description=blanks["description"],
        specifications=blanks["specifications"],
        variant_width=blanks["variant_width"],
        variant_length=blanks["variant_length"],
        price_unit=blanks["price_unit"],
    )


class PortalSays(Enum):
    """Scripted page outcomes that are not a product list or an exception."""

    NOT_FOUND = auto()


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
        self.pages: dict[str, Sequence[ScrapedProduct] | Exception | PortalSays] = {}
        self.login_error: Exception | None = None
        self.open_error: Exception | None = None
        self.close_error: Exception | None = None
        self.events: list[str] = []

    def open_browser(self) -> None:
        self.events.append("open")
        if self.open_error is not None:
            raise self.open_error

    def close_browser(self) -> None:
        self.events.append("close")
        if self.close_error is not None:
            raise self.close_error

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
        if page is PortalSays.NOT_FOUND:
            # What a concrete scraper does with a portal 404: record, not act.
            self.not_found_urls.add(url)
            return []
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

    @pytest.mark.parametrize("field", OPTIONAL_TEXT_FIELDS)
    def test_a_blank_optional_field_is_refused_because_unset_is_null(self, field: str) -> None:
        """``element.text`` on a cell the page stopped rendering is ``""``.

        Every one of these columns carries a ``_not_blank`` CHECK, so a blank
        used to reach the database, raise mid-batch, and abandon the whole run.
        """
        with pytest.raises(ValueError, match=f"blank {field}"):
            blank_in(field)

    def test_a_product_with_no_name_is_refused(self) -> None:
        with pytest.raises(ValueError, match="no product_name"):
            ScrapedProduct(
                item_no="SHS-50", variant_id="v1", product_name="", url="https://example.test/a"
            )


class TestSelectUrls:
    """The sitemap-versus-database diff: what a run visits. It retires nothing."""

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

    def test_refresh_old_revisits_known_urls_as_well_as_new_ones(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        price_list = make_price_list(supplier)
        make_product(supplier, price_list, "https://example.test/known")
        scraper.refresh_old = True

        selected = scraper.select_urls(["https://example.test/known", "https://example.test/new"])

        assert selected == ["https://example.test/known", "https://example.test/new"]

    def test_selecting_urls_never_retires_anything(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        """Retirement is a conclusion about the catalogue; it waits for the scrape."""
        price_list = make_price_list(supplier)
        vanished = make_product(supplier, price_list, "https://example.test/gone")
        scraper.refresh_old = True

        scraper.select_urls(["https://example.test/new"])

        vanished.refresh_from_db()
        assert vanished.is_discontinued is False

    def test_the_limit_is_applied_to_the_sorted_selection(self, scraper: ScriptedScraper) -> None:
        scraper.limit = 2

        selected = scraper.select_urls(
            ["https://example.test/c", "https://example.test/a", "https://example.test/b"]
        )

        assert selected == ["https://example.test/a", "https://example.test/b"]


class TestReconcileCatalogue:
    """What a run retires — only ever after a scrape that actually read pages."""

    def test_a_url_that_left_the_sitemap_is_retired_at_exactly_the_coverage_floor(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        """1 of 2 known URLs listed IS the MIN_SITEMAP_COVERAGE floor (50%),
        and the sweep must still run there: the floor is `<`, not `<=`. Keep
        the 1-of-2 shape — adding fixture products would silently move this
        test off the boundary it pins."""
        price_list = make_price_list(supplier)
        still_listed = make_product(supplier, price_list, "https://example.test/known")
        vanished = make_product(supplier, price_list, "https://example.test/gone", variant="v2")

        scraper.reconcile_catalogue(["https://example.test/known"])

        vanished.refresh_from_db()
        still_listed.refresh_from_db()
        assert vanished.is_discontinued is True
        assert still_listed.is_discontinued is False

    def test_a_product_that_came_back_is_un_retired(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        price_list = make_price_list(supplier)
        returned = make_product(
            supplier, price_list, "https://example.test/back", is_discontinued=True
        )

        scraper.reconcile_catalogue(["https://example.test/back"])

        returned.refresh_from_db()
        assert returned.is_discontinued is False

    def test_another_suppliers_products_are_never_retired(self, scraper: ScriptedScraper) -> None:
        other = make_company("Other Supplier", is_supplier=True)
        theirs = make_product(other, make_price_list(other), "https://example.test/gone")

        scraper.reconcile_catalogue(["https://example.test/new"])

        theirs.refresh_from_db()
        assert theirs.is_discontinued is False

    def test_a_half_empty_sitemap_retires_nothing(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        """The sitemap-shard defence: a sitemap that lost most of the catalogue
        is evidence about the SITEMAP, not about the products. Left alone, the
        day steelandtube.co.nz grows a sitemap_1.xml this sweep would retire
        every product that moved into it."""
        price_list = make_price_list(supplier)
        products = [
            make_product(supplier, price_list, f"https://example.test/p{index}", variant=str(index))
            for index in range(4)
        ]

        scraper.reconcile_catalogue(["https://example.test/p0"])

        for product in products:
            product.refresh_from_db()
            assert product.is_discontinued is False
        assert AppError.objects.filter(message__contains="sitemap").exists()

    def test_accumulated_discontinued_rows_do_not_wedge_the_floor(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        """The floor measures coverage of the LIVE catalogue.

        Retired rows are never deleted, so counting them in the denominator
        makes the ratio decay monotonically until the floor trips forever on a
        perfectly healthy sitemap — the defence becomes the outage.
        """
        price_list = make_price_list(supplier)
        for index in range(3):
            make_product(
                supplier,
                price_list,
                f"https://example.test/old{index}",
                variant=f"old{index}",
                is_discontinued=True,
            )
        listed = make_product(supplier, price_list, "https://example.test/live", variant="a")
        vanished = make_product(supplier, price_list, "https://example.test/gone", variant="b")

        # 1 of 2 LIVE products listed (at the floor, sweep runs); 1 of 5 known.
        scraper.reconcile_catalogue(["https://example.test/live"])

        vanished.refresh_from_db()
        listed.refresh_from_db()
        assert vanished.is_discontinued is True
        assert listed.is_discontinued is False
        assert not AppError.objects.exists()

    def test_a_limited_run_retires_nothing(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        """``--limit 2 --refresh-old`` retired 9 of 10 products before this."""
        price_list = make_price_list(supplier)
        vanished = make_product(supplier, price_list, "https://example.test/gone")
        scraper.limit = 2

        scraper.reconcile_catalogue(["https://example.test/new"])

        vanished.refresh_from_db()
        assert vanished.is_discontinued is False


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
        error = AppError.objects.get(message="Variant table missing")
        # ADR 0019: the handler exists to say which supplier, run and page.
        assert error.data is not None
        assert (
            error.data.items()
            >= {
                "supplier": scraper.supplier.name,
                "supplier_id": str(scraper.supplier.id),
                "scrape_job_id": str(job.id),
                "phase": "scrape",
                "url": "https://example.test/bad",
            }.items()
        )

    def test_a_page_with_no_variants_counts_as_a_failure(self, scraper: ScriptedScraper) -> None:
        scraper.published = ["https://example.test/empty", "https://example.test/good"]
        scraper.pages = {
            "https://example.test/empty": [],
            "https://example.test/good": [scraped("https://example.test/good")],
        }

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "SHS-50"})):
            job = scraper.run()

        assert job.products_scraped == 1
        assert job.products_failed == 1

    def test_a_browser_that_will_not_start_still_gets_closed(
        self, scraper: ScriptedScraper
    ) -> None:
        """open_browser leaves a profile directory behind even when it dies."""
        scraper.open_error = RuntimeError("chromedriver is not on PATH")

        with pytest.raises(RuntimeError, match="chromedriver"):
            scraper.run()

        assert scraper.events == ["open", "close"]
        assert ScrapeJob.objects.get().status == "failed"

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
        """The scrape is the valuable part; parsing can be retried."""
        self._script(scraper, {"https://example.test/shs": [scraped("https://example.test/shs")]})

        with patch(
            "apps.quoting.scrapers.base.populate_all_mappings_with_llm",
            side_effect=RuntimeError("Gemini is down"),
        ):
            job = scraper.run()

        assert job.status == "completed"
        assert job.products_scraped == 1
        assert AppError.objects.filter(message="Gemini is down").exists()


class TestARunMustHaveReadSomething:
    """A supplier redesign breaks every page at once; that is not a success.

    The damage is not the empty run — it is what a "successful" empty run then
    concludes: that the catalogue it could not read no longer exists.
    """

    def _pages(self, scraper: ScriptedScraper, urls: list[str], broken: set[str]) -> None:
        scraper.published = urls
        scraper.pages = {
            url: ValueError(f"Variant table missing on {url}")
            if url in broken
            else [scraped(url, item_no=f"ITEM-{position}")]
            for position, url in enumerate(urls)
        }

    def test_a_run_where_every_page_failed_is_recorded_failed(
        self, scraper: ScriptedScraper
    ) -> None:
        urls = [f"https://example.test/p{index}" for index in range(5)]
        self._pages(scraper, urls, broken=set(urls))

        job = scraper.run()

        assert job.status == "failed"
        assert job.error_message is not None
        assert "all 5 failed" in job.error_message
        assert job.products_failed == 5

    def test_a_run_that_mostly_failed_is_recorded_failed(self, scraper: ScriptedScraper) -> None:
        urls = [f"https://example.test/p{index}" for index in range(5)]
        self._pages(scraper, urls, broken=set(urls[:4]))

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "SHS-50"})):
            job = scraper.run()

        assert job.status == "failed"
        assert job.error_message is not None
        assert "4 of 5" in job.error_message

    def test_a_failed_run_retires_nothing(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        """The whole point: a green run that has already retired the catalogue."""
        price_list = make_price_list(supplier)
        known = make_product(supplier, price_list, "https://example.test/p0")
        urls = ["https://example.test/p0", "https://example.test/p1"]
        self._pages(scraper, urls, broken=set(urls))
        scraper.refresh_old = True

        job = scraper.run()

        assert job.status == "failed"
        known.refresh_from_db()
        assert known.is_discontinued is False

    def test_a_run_with_nothing_new_to_visit_is_still_a_success(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        """Zero pages attempted is a quiet week, not a broken portal."""
        price_list = make_price_list(supplier)
        make_product(supplier, price_list, "https://example.test/known")
        scraper.published = ["https://example.test/known"]

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "SHS-50"})):
            job = scraper.run()

        assert job.status == "completed"
        assert job.products_scraped == 0

    def test_a_healthy_refresh_run_still_retires_what_vanished(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        price_list = make_price_list(supplier)
        vanished = make_product(supplier, price_list, "https://example.test/gone")
        scraper.published = ["https://example.test/p0"]
        scraper.pages = {"https://example.test/p0": [scraped("https://example.test/p0")]}
        scraper.refresh_old = True

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "SHS-50"})):
            job = scraper.run()

        assert job.status == "completed"
        vanished.refresh_from_db()
        assert vanished.is_discontinued is True

    def test_a_limited_refresh_run_scrapes_but_retires_nothing(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        price_list = make_price_list(supplier)
        vanished = make_product(supplier, price_list, "https://example.test/gone")
        scraper.published = ["https://example.test/p0", "https://example.test/p1"]
        scraper.pages = {
            url: [scraped(url, item_no=f"ITEM-{url[-1]}")] for url in scraper.published
        }
        scraper.refresh_old = True
        scraper.limit = 1

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "SHS-50"})):
            job = scraper.run()

        assert job.status == "completed"
        assert job.products_scraped == 1
        vanished.refresh_from_db()
        assert vanished.is_discontinued is False


def oversized(url: str, *, item_no: str = "OVERSIZE") -> ScrapedProduct:
    """A variant the database will refuse.

    product_name is varchar(500); 600 characters is a DataError, and the kind of
    thing a page that starts rendering its whole body into the <h1> produces.
    """
    return ScrapedProduct(item_no=item_no, variant_id="v1", product_name="x" * 600, url=url)


class TestARowTheDatabaseRefuses:
    """One unsaveable variant must not take the batch — or the run — with it."""

    def test_the_rest_of_the_batch_is_saved_and_the_failure_is_persisted(
        self, supplier: Company
    ) -> None:
        price_list = make_price_list(supplier)
        scraper = ScriptedScraper(supplier)

        refused = scraper.save_products(
            price_list,
            [
                oversized("https://example.test/bad"),
                scraped("https://example.test/good"),
            ],
        )

        assert refused == 1
        assert SupplierProduct.objects.count() == 1
        assert SupplierProduct.objects.get().item_no == "SHS-50"
        assert AppError.objects.count() == 1

    def test_the_run_completes_and_says_how_many_rows_were_lost(
        self, scraper: ScriptedScraper
    ) -> None:
        scraper.published = ["https://example.test/p0"]
        scraper.pages = {
            "https://example.test/p0": [
                oversized("https://example.test/p0"),
                scraped("https://example.test/p0"),
            ]
        }

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "SHS-50"})):
            job = scraper.run()

        assert job.status == "completed"
        assert job.error_message is not None
        assert "1 scraped products were refused" in job.error_message


class TestARunMustHaveWrittenSomething:
    """Pages can read fine while the database refuses every row.

    February 2026's shape through a second door: ``succeeded`` counts *pages*,
    so a run that persisted nothing still looked healthy, recorded itself
    completed, and went on to retire the catalogue it had failed to write.
    """

    def test_all_rows_refused_is_unhealthy(self) -> None:
        outcome = ScrapeOutcome(succeeded=2, failed=0, refused=2, saved=0)
        assert outcome.unhealthy_reason() is not None

    def test_exactly_half_refused_is_tolerated(self) -> None:
        # The same boundary as page failures: over MAX_FAILURE_RATIO, not at it.
        outcome = ScrapeOutcome(succeeded=2, failed=0, refused=1, saved=1)
        assert outcome.unhealthy_reason() is None

    def test_a_run_where_every_row_was_refused_is_recorded_failed(
        self, scraper: ScriptedScraper
    ) -> None:
        scraper.published = ["https://example.test/p0", "https://example.test/p1"]
        scraper.pages = {
            url: [oversized(url, item_no=f"ITEM-{url[-1]}")] for url in scraper.published
        }

        job = scraper.run()

        assert job.status == "failed"
        assert job.error_message is not None
        assert "refused" in job.error_message

    def test_a_refused_dominated_run_is_recorded_failed(self, scraper: ScriptedScraper) -> None:
        scraper.published = ["https://example.test/p0"]
        scraper.pages = {
            "https://example.test/p0": [
                oversized("https://example.test/p0", item_no="BAD-1"),
                oversized("https://example.test/p0", item_no="BAD-2"),
                scraped("https://example.test/p0"),
            ]
        }

        job = scraper.run()

        assert job.status == "failed"
        assert job.error_message is not None
        assert "refused" in job.error_message

    def test_a_run_whose_rows_were_all_refused_retires_nothing(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        price_list = make_price_list(supplier)
        vanished = make_product(supplier, price_list, "https://example.test/gone")
        scraper.published = ["https://example.test/p0"]
        scraper.pages = {"https://example.test/p0": [oversized("https://example.test/p0")]}
        scraper.refresh_old = True

        job = scraper.run()

        assert job.status == "failed"
        vanished.refresh_from_db()
        assert vanished.is_discontinued is False


class TestTheOutcomeSurvivesTeardownAndAftermath:
    """Neither a teardown failure nor a post-scrape failure may falsify the job.

    ``close_browser`` raising in the ``finally`` used to REPLACE the run's real
    outcome (a successful scrape ended "failed", named after the teardown; a
    real failure was masked by the teardown's). And anything raising after the
    scrape left the job ``running`` forever — the one status nothing alerts on.
    """

    def test_a_close_failure_does_not_fail_a_successful_run(self, scraper: ScriptedScraper) -> None:
        scraper.published = ["https://example.test/p0"]
        scraper.pages = {"https://example.test/p0": [scraped("https://example.test/p0")]}
        scraper.close_error = RuntimeError("Chrome would not shut down")

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "SHS-50"})):
            job = scraper.run()

        assert job.status == "completed"
        assert AppError.objects.filter(message="Chrome would not shut down").exists()

    def test_a_close_failure_does_not_mask_the_scrapes_own_failure(
        self, scraper: ScriptedScraper
    ) -> None:
        scraper.login_error = RuntimeError("Portal refused the credentials")
        scraper.close_error = RuntimeError("Chrome would not shut down")

        with pytest.raises(RuntimeError, match="Portal refused the credentials"):
            scraper.run()

        job = ScrapeJob.objects.get()
        assert job.status == "failed"
        assert job.error_message == "Portal refused the credentials"

    def test_a_failure_after_the_scrape_still_fails_the_job(self, scraper: ScriptedScraper) -> None:
        """Not left ``running`` forever — the one status nothing alerts on."""
        scraper.published = ["https://example.test/p0"]
        scraper.pages = {"https://example.test/p0": [scraped("https://example.test/p0")]}
        scraper.refresh_old = True

        with (
            patch.object(
                ScriptedScraper,
                "reconcile_catalogue",
                side_effect=RuntimeError("sweep exploded"),
            ),
            pytest.raises(RuntimeError, match="sweep exploded"),
        ):
            scraper.run()

        job = ScrapeJob.objects.get()
        assert job.status == "failed"
        assert job.error_message == "sweep exploded"

    def test_the_failure_is_persisted_even_when_the_job_row_cannot_be_saved(
        self, scraper: ScriptedScraper
    ) -> None:
        """persist_app_error must run BEFORE job.save in the failure net: a dead
        connection at bookkeeping time otherwise destroys the only record."""
        scraper.login_error = RuntimeError("Portal down")

        with (
            patch.object(ScrapeJob, "save", side_effect=[None, DatabaseError("connection lost")]),
            pytest.raises(DatabaseError, match="connection lost"),
        ):
            scraper.run()

        assert AppError.objects.filter(message="Portal down").exists()

    def test_a_failing_completion_save_is_persisted_not_lost(
        self, scraper: ScriptedScraper
    ) -> None:
        """The success epilogue is inside the failure net too: its save raising
        must leave an AppError, not vanish with the job stuck `running`."""
        scraper.published = ["https://example.test/p0"]
        scraper.pages = {"https://example.test/p0": [scraped("https://example.test/p0")]}

        saves = [0]

        def save_then_die(*_args: object, **_kwargs: object) -> None:
            # The job row's connection dies after creation and STAYS dead —
            # the failure net's own save must not resurrect the test.
            saves[0] += 1
            if saves[0] > 1:
                raise DatabaseError("connection lost")

        with (
            patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "SHS-50"})),
            patch.object(ScrapeJob, "save", side_effect=save_then_die),
            pytest.raises(DatabaseError, match="connection lost"),
        ):
            scraper.run()

        assert AppError.objects.filter(message="connection lost").exists()


class TestANotFoundPageRetiresOnlyBehindTheGates:
    """A portal 404 retires its product via run(), never mid-visit.

    Mid-visit retirement bypassed both gates: a portal serving one error page
    for every URL retired each visited product BEFORE the run was declared
    unhealthy, and ``--limit`` did not apply.
    """

    def test_a_healthy_run_retires_what_the_portal_no_longer_serves(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        price_list = make_price_list(supplier)
        withdrawn = make_product(supplier, price_list, "https://example.test/p0")
        scraper.published = ["https://example.test/p0", "https://example.test/p1"]
        scraper.pages = {
            "https://example.test/p0": PortalSays.NOT_FOUND,
            "https://example.test/p1": [scraped("https://example.test/p1")],
        }
        scraper.force = True

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "SHS-50"})):
            job = scraper.run()

        assert job.status == "completed"
        withdrawn.refresh_from_db()
        assert withdrawn.is_discontinued is True

    def test_an_unhealthy_run_retires_none_of_its_not_found_pages(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        """The February shape: every page lands on an error page. Retire nothing."""
        price_list = make_price_list(supplier)
        withdrawn = make_product(supplier, price_list, "https://example.test/p0")
        scraper.published = ["https://example.test/p0", "https://example.test/p1"]
        scraper.pages = dict.fromkeys(scraper.published, PortalSays.NOT_FOUND)
        scraper.force = True

        job = scraper.run()

        assert job.status == "failed"
        withdrawn.refresh_from_db()
        assert withdrawn.is_discontinued is False

    def test_a_limited_run_retires_none_of_its_not_found_pages(
        self, supplier: Company, scraper: ScriptedScraper
    ) -> None:
        price_list = make_price_list(supplier)
        withdrawn = make_product(supplier, price_list, "https://example.test/p0")
        scraper.published = [
            "https://example.test/p0",
            "https://example.test/p1",
            "https://example.test/p2",
        ]
        scraper.pages = {
            "https://example.test/p0": PortalSays.NOT_FOUND,
            "https://example.test/p1": [scraped("https://example.test/p1")],
        }
        scraper.force = True
        scraper.limit = 2

        with patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "SHS-50"})):
            job = scraper.run()

        assert job.status == "completed"
        withdrawn.refresh_from_db()
        assert withdrawn.is_discontinued is False


class TestTheUpsertKeyMatchesTheDatabase:
    """``update_or_create`` must key on what ``unique_together`` enforces."""

    def test_the_same_variant_at_a_new_url_becomes_a_new_row(self, supplier: Company) -> None:
        """The DB permits it, so the app must not assume it cannot happen."""
        price_list = make_price_list(supplier)
        scraper = ScriptedScraper(supplier)
        scraper.save_products(price_list, [scraped("https://example.test/old")])

        scraper.save_products(price_list, [scraped("https://example.test/new")])

        assert SupplierProduct.objects.count() == 2

    def test_a_duplicate_on_the_old_key_no_longer_wedges_the_supplier(
        self, supplier: Company
    ) -> None:
        """Keying on a subset raised MultipleObjectsReturned here, forever."""
        price_list = make_price_list(supplier)
        scraper = ScriptedScraper(supplier)
        scraper.save_products(price_list, [scraped("https://example.test/old")])
        scraper.save_products(price_list, [scraped("https://example.test/new")])

        refused = scraper.save_products(
            price_list, [scraped("https://example.test/old", variant_price=Decimal("9.99"))]
        )

        assert refused == 0
        updated = SupplierProduct.objects.get(url="https://example.test/old")
        assert updated.variant_price == Decimal("9.99")


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

    def test_a_scraper_that_cannot_even_be_resolved_is_persisted_with_its_supplier(
        self, supplier: Company
    ) -> None:
        """A failure before run() has no ScrapeJob; the AppError is the only trace.

        ADR 0019: without the supplier and class on the row, a broken dotted
        path in a SupplierScraperConfig is a bare ImportError joined to nothing.
        """
        make_config(supplier, dotted_path=COMMAND_SCRAPER)
        SupplierScraperConfig.objects.filter(supplier=supplier).update(
            scraper_class="apps.quoting.tests.test_scrapers.NoSuchScraper"
        )

        call_command("run_scrapers")

        error = AppError.objects.get()
        assert error.data is not None
        assert error.data["supplier"] == supplier.name
        assert error.data["scraper_class"] == "apps.quoting.tests.test_scrapers.NoSuchScraper"
