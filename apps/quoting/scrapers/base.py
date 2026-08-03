"""Supplier portal scraping: the run orchestration, and the browser it drives.

Ported from v1 ``apps/quoting/scrapers/base.py``. This is the code that gives
``SupplierScraperConfig``, ``SupplierCredential``, ``ScrapeJob``,
``SupplierPriceList`` and ``SupplierProduct`` — all already in v2 — something to
write them.

Two classes, because they answer two questions:

- ``BaseScraper`` owns the run and knows nothing about a browser: the
  ``ScrapeJob`` lifecycle, the sitemap-versus-database URL diff that marks
  products discontinued and un-marks the ones that reappear, batched
  persistence, and the end-of-run LLM parse. It is exercised end to end by a
  scripted subclass in the tests, with no Chrome anywhere.
- ``SeleniumScraper`` fills the browser seam (``open_browser`` /
  ``close_browser``) with v1's headless Chrome — the one place in v2 that starts
  a browser. A concrete scraper subclasses it and supplies only ``login``,
  ``product_urls`` and ``scrape_product``.

Nothing user-facing calls a scraper at request time. The only triggers are an
operator running ``manage.py run_scrapers`` and the Sunday-afternoon beat task
``apps.quoting.tasks.run_all_scrapers_task``.
"""

import logging
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from django.utils import timezone
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webdriver import WebDriver

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

# v1's headless-Chrome tuning, ported verbatim: these were arrived at against
# the real portal and a real (snap-packaged, WSL) Chromium, so they are data,
# not preference. Notes on the ones that look dated are in the port report;
# nothing here is changed without a run against the live site to justify it.
CHROME_FLAGS: Final = (
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--window-size=1920,1080",
    "--headless",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-default-apps",
    "--disable-sync",
    "--disable-translate",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-blink-features=AutomationControlled",
    "--disable-web-security",
    "--allow-running-insecure-content",
    "--disable-software-rasterizer",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-features=TranslateUI",
    "--disable-ipc-flooding-protection",
)

# Snap-packaged Chromium (the WSL dev box) will not start without an explicit
# binary and a debugging port; a normal Chrome install has neither line apply.
SNAP_CHROMIUM = Path("/snap/bin/chromium")
SNAP_REMOTE_DEBUGGING_PORT = 9222

# v1's user-agent, kept byte-for-byte: the portal serves different markup to
# agents it does not recognise, and this string is what the selectors below were
# written against. (It is a truncated Safari/macOS string — see the port report.)
USER_AGENT: Final = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


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
    """This scrape cannot authenticate — the portal refused, or timed out.

    Fatal by design: ``_visit`` re-raises it rather than counting it as one
    unreadable page, because an unauthenticated session makes every remaining
    page fail identically and would otherwise finish the run "completed" with
    nothing scraped.
    """


class ScraperCredentialError(ScraperLoginError):
    """The stored credential cannot drive a portal login (wrong type, or blank).

    A ``ScraperLoginError`` — it stops the run the same way — but named
    separately because the fix is different: a login error means "go and look at
    the portal", this means "go and fix the ``SupplierCredential`` row". Neither
    may be mistakable for a quiet zero-row run, which is how February 2026's
    stale portal password went unnoticed for months.
    """


class ScraperBrowserError(RuntimeError):
    """The browser was used outside ``open_browser``/``close_browser``."""


class ScraperPageError(RuntimeError):
    """A product page did not contain what the scraper's selectors expect.

    Raised — never swallowed — because a supplier redesign shows up as exactly
    this, on every page, and the operator's only signal is the failure count on
    the ``ScrapeJob`` plus the ``AppError`` rows ``_visit`` writes.
    """


@dataclass(frozen=True, slots=True)
class PortalLogin:
    """The username and password a portal login form needs, both known present."""

    username: str
    password: str


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
        """Start the browser this scraper drives (``SeleniumScraper`` supplies one)."""

    @abstractmethod
    def close_browser(self) -> None:
        """Shut the browser down; called whatever the run did."""

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

    def portal_login(self) -> PortalLogin:
        """Return the username/password pair for this portal, or a named failure.

        ``credentials()`` is generic over every credential type, so its dict is
        the wrong shape for a login form whenever the configured credential is
        an API key, or is a username/password row with a blank column. Both are
        configuration errors and both raise here rather than reaching Selenium
        as a ``KeyError`` or, worse, a login attempt with ``None``.
        """
        material = self.credentials()
        username = material.get("username")
        password = material.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            raise ScraperCredentialError(
                f"{self.supplier.name}'s active credential cannot log in to a portal: "
                f"expected a username_password credential, got fields {sorted(material)} "
                f"(username={username!r}). Fix the SupplierCredential row."
            )
        return PortalLogin(username=username, password=password)

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
            except ScraperLoginError:
                # The session is gone. Every remaining URL would redirect to the
                # login page and be counted as a page failure, and the run would
                # still finish "completed" with nothing scraped — February 2026's
                # failure mode. Abort instead: run() marks the job failed.
                raise
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


class SeleniumScraper(BaseScraper):
    """A ``BaseScraper`` whose browser seam is v1's headless Chrome.

    The only place in v2 that starts a browser. Subclasses get ``self.driver``
    between ``open_browser`` and ``close_browser`` and implement the three
    site-specific methods; the driver lifetime is owned here so a scraper cannot
    leak a Chrome process or a profile directory when a page blows up.
    """

    def __init__(
        self,
        supplier: Company,
        *,
        limit: int | None = None,
        force: bool = False,
        refresh_old: bool = False,
    ) -> None:
        """Configure one run; the browser is not started until ``open_browser``."""
        super().__init__(supplier, limit=limit, force=force, refresh_old=refresh_old)
        self._driver: WebDriver | None = None
        self._profile: tempfile.TemporaryDirectory[str] | None = None

    @property
    def driver(self) -> WebDriver:
        """The running browser. Raises if called outside the open/close window."""
        if self._driver is None:
            raise ScraperBrowserError(
                f"{type(self).__name__} used the browser before open_browser() "
                f"(or after close_browser()); supplier={self.supplier.name}"
            )
        return self._driver

    def chrome_options(self) -> Options:
        """Build v1's headless-Chrome configuration for one run.

        The profile directory is per-run and temporary: Chrome refuses to start a
        second instance against a profile already in use, and the weekly run and
        an operator's ``manage.py run_scrapers`` can overlap.
        """
        if self._profile is not None:
            raise ScraperBrowserError("chrome_options() called with a profile already open")
        # ignore_cleanup_errors: this is scratch space Chrome may still be
        # unlinking as it exits, and a failure to delete it must not fail an
        # otherwise good scrape. (v1 called mkdtemp and never removed the
        # directory at all — one leaked profile per run, forever.)
        self._profile = tempfile.TemporaryDirectory(
            prefix="scraper_chrome_", ignore_cleanup_errors=True
        )

        options = Options()
        for flag in CHROME_FLAGS:
            options.add_argument(flag)
        options.add_argument(f"--user-data-dir={self._profile.name}")
        if SNAP_CHROMIUM.exists():
            options.add_argument(f"--remote-debugging-port={SNAP_REMOTE_DEBUGGING_PORT}")
            options.binary_location = str(SNAP_CHROMIUM)
        options.add_argument(f"user-agent={USER_AGENT}")
        return options

    def open_browser(self) -> None:
        """Start the headless Chrome this scraper drives."""
        if self._driver is not None:
            raise ScraperBrowserError(
                f"{type(self).__name__}.open_browser() called with a browser already running"
            )
        self._driver = webdriver.Chrome(options=self.chrome_options())
        self.logger.info("Started headless Chrome for %s", self.supplier.name)

    def close_browser(self) -> None:
        """Quit the browser and delete its profile. Safe to call when not open."""
        driver, self._driver = self._driver, None
        profile, self._profile = self._profile, None
        try:
            if driver is not None:
                driver.quit()
        finally:
            if profile is not None:
                profile.cleanup()
