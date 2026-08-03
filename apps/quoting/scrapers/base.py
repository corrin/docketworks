"""Supplier portal scraping: the run orchestration, minus the browser.

Ported from v1 ``apps/quoting/scrapers/base.py``. This is the code that gives
``SupplierScraperConfig``, ``SupplierCredential``, ``ScrapeJob``,
``SupplierPriceList`` and ``SupplierProduct`` — all already in v2 — something to
write them.

SELENIUM SEAM. v1's ``BaseScraper.setup_driver()`` built a headless Chrome with
twenty tuning flags, and the one concrete subclass
(``scrapers/steel_and_tube.py``, 509 lines) drove that browser through the Steel
& Tube portal's login form and per-product variant tables. Neither is ported:

- ``selenium`` plus a Chrome/Chromium binary is a heavy runtime dependency this
  slice may not add (reported instead — see the port report).
- ``steel_and_tube.py`` is a wall of CSS selectors against a live third-party
  DOM. Nothing about it can be tested here, and it drifts with their site rather
  than with our code, so translating it by hand buys nothing over lifting it
  verbatim on the day the dependency lands.
- Nothing user-facing calls a scraper at request time. The only triggers are an
  operator running ``manage.py run_scrapers`` and the Sunday-afternoon beat task
  ``apps.quoting.tasks.run_all_scrapers_task``.

What IS ported is everything a scraper does that is ours rather than Chrome's:
the ``ScrapeJob`` lifecycle, the sitemap-versus-database URL diff that marks
products discontinued and un-marks the ones that reappear, batched persistence,
and the end-of-run LLM parse. ``open_browser``/``close_browser`` and the three
site-specific methods are abstract, so a subclass supplies the browser and the
selectors and this class keeps owning the run.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.utils import timezone

from apps.company.models import Company
from apps.core.errors import persist_app_error
from apps.quoting.models import (
    ScrapeJob,
    SupplierPriceList,
    SupplierProduct,
    SupplierScraperConfig,
)
from apps.quoting.services.product_parser import (
    create_mapping_record,
    populate_all_mappings_with_llm,
)

logger = logging.getLogger(__name__)

SAVE_BATCH_SIZE = 50


@dataclass(frozen=True, slots=True)
class ScrapedProduct:
    """One product variant as read off a supplier portal page.

    v1 passed untyped dicts straight into ``update_or_create(defaults=...)``,
    which is why a missing ``item_no`` had to be caught with a hand-written
    ``in ["N/A", "", None]`` check. The required fields are required here (ADR
    0028), so that check becomes a constructor guard.
    """

    item_no: str
    variant_id: str
    product_name: str
    url: str
    description: str | None = None
    specifications: str | None = None
    variant_width: str | None = None
    variant_length: str | None = None
    variant_price: Decimal | None = None
    price_unit: str | None = None
    variant_available_stock: int | None = None

    def __post_init__(self) -> None:
        """Reject the placeholder identifiers v1 had to filter downstream."""
        if not self.item_no or self.item_no == "N/A":
            raise ValueError(
                f"Scraped product has no item_no: url={self.url} "
                f"name={self.product_name} variant_id={self.variant_id}"
            )
        if not self.variant_id or self.variant_id == "N/A":
            raise ValueError(
                f"Scraped product has no variant_id: url={self.url} "
                f"name={self.product_name} item_no={self.item_no}"
            )


class ScraperLoginError(RuntimeError):
    """The supplier portal refused the configured credentials."""


class BaseScraper(ABC):
    """Runs one supplier's scrape end to end; subclasses supply the browser.

    Subclass contract: ``open_browser``/``close_browser`` own the driver (the
    Selenium seam), ``login`` authenticates or raises ``ScraperLoginError``,
    ``product_urls`` lists what is available, and ``scrape_product`` turns one
    page into ``ScrapedProduct`` rows.
    """

    def __init__(
        self,
        supplier: Company,
        *,
        limit: int | None = None,
        force: bool = False,
        refresh_old: bool = False,
    ) -> None:
        """Configure one run. ``force`` re-scrapes everything, ignoring the URL diff."""
        self.supplier = supplier
        self.limit = limit
        self.force = force
        self.refresh_old = refresh_old
        self.logger = logging.getLogger(f"scraper.{supplier.name.lower().replace(' ', '_')}")

    # ── Subclass seam ────────────────────────────────────────────────────

    @abstractmethod
    def open_browser(self) -> None:
        """SELENIUM SEAM: start the browser this scraper drives."""

    @abstractmethod
    def close_browser(self) -> None:
        """SELENIUM SEAM: shut the browser down; always called."""

    @abstractmethod
    def login(self) -> None:
        """Authenticate against the supplier portal, or raise ScraperLoginError."""

    @abstractmethod
    def product_urls(self) -> list[str]:
        """Every product URL the supplier currently publishes."""

    @abstractmethod
    def scrape_product(self, url: str) -> Sequence[ScrapedProduct]:
        """Read one product page into its variant rows."""

    # ── Shared orchestration ─────────────────────────────────────────────

    def credentials(self) -> dict[str, Any]:
        """Credential material for this supplier's enabled scraper config."""
        config = SupplierScraperConfig.objects.select_related("active_credential").get(
            supplier=self.supplier, is_enabled=True
        )
        return config.active_credential.get_credential_dict()

    def select_urls(self, published: Iterable[str]) -> list[str]:
        """Decide which published URLs this run should visit.

        ``force`` visits everything. Otherwise v1's diff applies: with
        ``refresh_old`` the run covers new *and* previously seen URLs, marks
        anything that vanished from the sitemap discontinued, and clears that
        flag on anything that came back; without it, only URLs never seen
        before. The ``limit`` is applied last, as a testing throttle.
        """
        published_urls = set(published)
        if self.force:
            selected = list(published_urls)
        else:
            known_urls = set(
                SupplierProduct.objects.filter(supplier=self.supplier).values_list("url", flat=True)
            )
            if self.refresh_old:
                self._mark_discontinued(known_urls - published_urls)
                self._clear_discontinued(published_urls)
                selected = list(published_urls)
            else:
                selected = [url for url in published_urls if url not in known_urls]

        selected.sort()
        if self.limit is not None:
            return selected[: self.limit]
        return selected

    def _mark_discontinued(self, vanished: set[str]) -> None:
        if not vanished:
            return
        marked = SupplierProduct.objects.filter(
            supplier=self.supplier, url__in=vanished, is_discontinued=False
        ).update(is_discontinued=True)
        self.logger.info(
            "Marked %s products discontinued (%s URLs left the sitemap)", marked, len(vanished)
        )

    def _clear_discontinued(self, published_urls: set[str]) -> None:
        reappeared = SupplierProduct.objects.filter(
            supplier=self.supplier, url__in=published_urls, is_discontinued=True
        ).update(is_discontinued=False)
        if reappeared:
            self.logger.info("Cleared the discontinued flag on %s products", reappeared)

    def save_products(
        self, price_list: SupplierPriceList, products: Sequence[ScrapedProduct]
    ) -> None:
        """Upsert a batch of scraped variants and reserve a mapping for new ones."""
        for product in products:
            supplier_product, created = SupplierProduct.objects.update_or_create(
                supplier=self.supplier,
                item_no=product.item_no,
                variant_id=product.variant_id,
                defaults={
                    "price_list": price_list,
                    "product_name": product.product_name,
                    "url": product.url,
                    "description": product.description,
                    "specifications": product.specifications,
                    "variant_width": product.variant_width,
                    "variant_length": product.variant_length,
                    "variant_price": product.variant_price,
                    "price_unit": product.price_unit,
                    "variant_available_stock": product.variant_available_stock,
                },
            )
            if created:
                # The LLM runs once, in bulk, at the end of the run.
                create_mapping_record(supplier_product)

    def run(self) -> ScrapeJob:
        """Execute the whole scrape, recording it as a ``ScrapeJob``."""
        job = ScrapeJob.objects.create(
            supplier=self.supplier, status="running", started_at=timezone.now()
        )
        price_list = SupplierPriceList.objects.create(
            supplier=self.supplier,
            file_name=f"Web Scrape {timezone.now().strftime('%Y-%m-%d %H:%M')}",
        )

        try:
            self.open_browser()
            try:
                self.login()
                published = self.product_urls()
                if not published:
                    return self._fail(job, "No product URLs found")
                succeeded, failed = self._visit(price_list, self.select_urls(published))
            finally:
                self.close_browser()
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc) or exc.__class__.__name__
            job.completed_at = timezone.now()
            job.save()
            persist_app_error(exc)
            self.logger.exception("Scraper failed for %s", self.supplier.name)
            raise

        self._parse_new_products()

        job.status = "completed"
        job.products_scraped = succeeded
        job.products_failed = failed
        job.completed_at = timezone.now()
        job.save()
        self.logger.info("Completed: %s successful, %s failed", succeeded, failed)
        return job

    def _visit(self, price_list: SupplierPriceList, urls: list[str]) -> tuple[int, int]:
        """Scrape each URL, saving in batches. Returns (succeeded, failed) URL counts."""
        self.logger.info("Processing %s URLs for %s", len(urls), self.supplier.name)
        succeeded = 0
        failed = 0
        batch: list[ScrapedProduct] = []
        for position, url in enumerate(urls, 1):
            self.logger.info("Processing %s/%s: %s", position, len(urls), url)
            try:
                products = self.scrape_product(url)
            except Exception as exc:
                # One unreadable product page must not abandon the run; the
                # failure is counted on the ScrapeJob and persisted.
                failed += 1
                persist_app_error(exc)
                self.logger.exception("Error processing %s", url)
                continue

            if not products:
                failed += 1
                continue
            batch.extend(products)
            succeeded += 1
            if len(batch) >= SAVE_BATCH_SIZE:
                self.save_products(price_list, batch)
                batch = []

        if batch:
            self.save_products(price_list, batch)
        return succeeded, failed

    def _parse_new_products(self) -> None:
        """Fill the run's new mappings via the LLM; never fails the run (v1)."""
        self.logger.info("Processing unparsed products with LLM...")
        try:
            populated = populate_all_mappings_with_llm()
        except Exception as exc:
            persist_app_error(exc)
            self.logger.exception("LLM parsing failed")
            return
        self.logger.info("LLM parsing completed: %s mappings populated", populated)

    def _fail(self, job: ScrapeJob, reason: str) -> ScrapeJob:
        job.status = "failed"
        job.error_message = reason
        job.completed_at = timezone.now()
        job.save()
        self.logger.error("Scrape failed for %s: %s", self.supplier.name, reason)
        return job
