# quoting/scrapers/base.py
import logging
import os
import tempfile
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

from django.utils import timezone
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from apps.quoting.services.product_parser import create_mapping_record
from apps.workflow.services.error_persistence import persist_app_error


class BaseScraper(ABC):
    """Base class for all supplier scrapers"""

    DEFAULT_REFRESH_LIMIT = 100  # Clear default for refresh cycle

    def __init__(self, supplier, limit=None, force=False, refresh_old: bool = False):
        self.supplier = supplier
        self.limit = limit
        self.force = force
        self.refresh_old = refresh_old
        self.driver = None
        self.logger = logging.getLogger(
            f"scraper.{supplier.name.lower().replace(' ', '_')}"
        )

    def setup_driver(self):
        """Setup Selenium WebDriver - common for all scrapers"""
        chrome_options = Options()
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-background-networking")
        chrome_options.add_argument("--disable-default-apps")
        chrome_options.add_argument("--disable-sync")
        chrome_options.add_argument("--disable-translate")
        chrome_options.add_argument("--no-first-run")
        chrome_options.add_argument("--no-default-browser-check")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--allow-running-insecure-content")
        chrome_options.add_argument("--disable-software-rasterizer")
        chrome_options.add_argument("--disable-background-timer-throttling")
        chrome_options.add_argument("--disable-renderer-backgrounding")
        chrome_options.add_argument("--disable-features=TranslateUI")
        chrome_options.add_argument("--disable-ipc-flooding-protection")

        # Use unique temp directory with timestamp to avoid conflicts
        unique_id = f"{int(time.time())}_{str(uuid.uuid4())[:8]}"
        temp_dir = tempfile.mkdtemp(prefix=f"scraper_chrome_{unique_id}_")
        chrome_options.add_argument(f"--user-data-dir={temp_dir}")

        # Additional flags for snap Chromium compatibility (WSL)
        if os.path.exists("/snap/bin/chromium"):
            chrome_options.add_argument("--remote-debugging-port=9222")
            chrome_options.binary_location = "/snap/bin/chromium"

        user_agent = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        chrome_options.add_argument(f"user-agent={user_agent}")

        self.driver = webdriver.Chrome(options=chrome_options)
        return self.driver

    def get_credentials(self) -> dict[str, Any]:
        """Get credentials from the supplier scraper configuration."""
        from apps.quoting.models import SupplierScraperConfig

        config = SupplierScraperConfig.objects.select_related("active_credential").get(
            supplier=self.supplier, is_enabled=True
        )
        return config.active_credential.get_credential_dict()

    def cleanup(self):
        """Clean up resources"""
        if self.driver:
            self.driver.quit()

    @abstractmethod
    def get_product_urls(self):
        """Get list of product URLs to scrape"""

    @abstractmethod
    def scrape_product(self, url):
        """Scrape a single product page"""

    @abstractmethod
    def login(self):
        """Handle login process"""

    def run(self):
        """Main scraper execution"""
        from apps.quoting.models import ScrapeJob, SupplierPriceList, SupplierProduct

        # Create scrape job
        job = ScrapeJob.objects.create(
            supplier=self.supplier, status="running", started_at=timezone.now()
        )

        # Create price list for this scrape session
        self.price_list = SupplierPriceList.objects.create(
            supplier=self.supplier,
            file_name=f"Web Scrape {timezone.now().strftime('%Y-%m-%d %H:%M')}",
        )

        try:
            self.setup_driver()
            login_success = self.login()

            if not login_success:
                self.logger.error("Login failed, stopping scraper execution")
                raise Exception("Login failed - cannot proceed with scraping")

            # Get URLs to scrape
            product_urls = self.get_product_urls()

            if not product_urls:
                job.status = "failed"
                job.error_message = "No product URLs found"
                job.completed_at = timezone.now()
                job.save()
                return

            # Filter URLs based on refresh_old flag
            if not self.force:
                sitemap_urls = set(product_urls)

                # Get existing URLs we have (with discontinued status)
                existing_qs = SupplierProduct.objects.filter(
                    supplier=self.supplier
                ).values_list("url", flat=True)
                existing_urls = set(existing_qs)

                if self.refresh_old:
                    # Mark products not in sitemap as discontinued
                    disappeared_urls = existing_urls - sitemap_urls
                    if disappeared_urls:
                        marked = SupplierProduct.objects.filter(
                            supplier=self.supplier,
                            url__in=disappeared_urls,
                            is_discontinued=False,
                        ).update(is_discontinued=True)
                        self.logger.info(
                            f"Marked {marked} products as discontinued "
                            f"({len(disappeared_urls)} URLs not in sitemap)"
                        )

                    # Unmark products that reappeared in sitemap
                    reappeared = SupplierProduct.objects.filter(
                        supplier=self.supplier,
                        url__in=sitemap_urls,
                        is_discontinued=True,
                    ).update(is_discontinued=False)
                    if reappeared:
                        self.logger.info(
                            f"Unmarked {reappeared} products as no longer discontinued"
                        )

                    # New products (in sitemap, not in our DB)
                    new_urls = sitemap_urls - existing_urls

                    # Changed products (in both sitemap and our DB)
                    changed_urls = sitemap_urls & existing_urls

                    # Final URL list: new + changed (no oldest_urls rotation)
                    product_urls = list(new_urls | changed_urls)
                else:
                    # Original behavior: only scrape new products
                    product_urls = [
                        url for url in product_urls if url not in existing_urls
                    ]

            # Apply limit
            if self.limit:
                product_urls = product_urls[: self.limit]

            self.logger.info(
                f"Processing {len(product_urls)} URLs for {self.supplier.name}"
            )

            successful = 0
            failed = 0
            batch_data = []

            for i, url in enumerate(product_urls, 1):
                try:
                    self.logger.info(f"Processing {i}/{len(product_urls)}: {url}")
                    products_data = self.scrape_product(url)

                    if products_data:
                        batch_data.extend(products_data)
                        successful += 1
                    else:
                        failed += 1

                    # Save in batches
                    if len(batch_data) >= 50:
                        self.save_products(batch_data)
                        batch_data = []

                except Exception as e:
                    self.logger.error(f"Error processing {url}: {e}")
                    failed += 1

            # Save remaining data
            if batch_data:
                self.save_products(batch_data)

            # Process any unparsed products with LLM
            self.logger.info("Processing unparsed products with LLM...")
            try:
                from apps.quoting.services.product_parser import (
                    populate_all_mappings_with_llm,
                )

                populate_all_mappings_with_llm()
                self.logger.info("LLM parsing completed")
            except Exception as e:
                persist_app_error(e)
                self.logger.error(f"LLM parsing failed: {e}", exc_info=True)
                # Don't fail the entire job if LLM parsing fails

            # Update job status
            job.status = "completed"
            job.products_scraped = successful
            job.products_failed = failed
            job.completed_at = timezone.now()
            job.save()

            self.logger.info(f"Completed: {successful} successful, {failed} failed")

        except Exception as e:
            job.status = "failed"
            job.error_message = str(e)
            job.completed_at = timezone.now()
            job.save()
            self.logger.error(f"Scraper failed: {e}")
            raise
        finally:
            self.cleanup()

    def save_products(self, products_data):
        """Save products to database"""
        from apps.quoting.models import SupplierProduct

        for product_data in products_data:
            try:
                # Fail fast on missing essential fields
                item_no = product_data.get("item_no")
                if not item_no or item_no in ["N/A", "", None]:
                    raise ValueError(
                        f"Product missing required item_no: "
                        f"URL={product_data.get('url')}, "
                        f"Name={product_data.get('product_name')}, "
                        f"VariantID={product_data.get('variant_id')}"
                    )

                product_data["supplier"] = self.supplier
                product_data["price_list"] = self.price_list

                product, created = SupplierProduct.objects.update_or_create(
                    supplier=self.supplier,
                    item_no=product_data["item_no"],
                    variant_id=product_data["variant_id"],
                    defaults=product_data,
                )

                # Create mapping record for new products (LLM called at end of batch)
                if created:
                    create_mapping_record(product)

            except Exception as e:
                self.logger.error(f"Error saving product: {e}")
