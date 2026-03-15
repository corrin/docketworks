import os
import re
import time

import requests
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from .base import BaseScraper


class SteelAndTubeScraper(BaseScraper):
    """Steel & Tube specific scraper implementation with comprehensive variant extraction"""

    SUPPLIER_NAME = "S&T Stainless Limited"

    def get_credentials(self):
        """Get Steel & Tube credentials from environment variables"""
        username = os.getenv("STEEL_TUBE_USERNAME")
        password = os.getenv("STEEL_TUBE_PASSWORD")
        return username, password

    def login(self):
        """Login to Steel & Tube portal"""
        username, password = self.get_credentials()

        if not username or not password:
            self.logger.error("Credentials not found in environment variables")
            return False

        try:
            login_url = "https://portal.steelandtube.co.nz/"
            self.logger.info(f"Attempting to log in with username: {username}")
            self.driver.get(login_url)

            # Find and fill username field
            username_field = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "UserName"))
            )
            username_field.clear()
            username_field.send_keys(username)

            # Find and fill password field
            password_field = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.ID, "Password"))
            )
            password_field.clear()
            password_field.send_keys(password)

            # Click login button
            login_button = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "button.btn-medium.btn-login")
                )
            )
            login_button.click()

            # Wait for login to complete
            time.sleep(2)
            WebDriverWait(self.driver, 15).until(
                EC.invisibility_of_element_located((By.ID, "UserName"))
            )

            self.logger.info("✅ Login successful")
            return True

        except Exception as e:
            self.logger.error(f"❌ Login failed: {e}")
            return False

    def get_product_urls(self):
        """Get product URLs from Steel & Tube sitemap"""
        sitemap_url = "https://portal.steelandtube.co.nz/sitemap_0.xml"
        url_patterns = [
            "https://portal.steelandtube.co.nz/stainless/",
            "https://portal.steelandtube.co.nz/steel/",
        ]

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            self.logger.info(f"Requesting sitemap from {sitemap_url}...")
            response = requests.get(sitemap_url, headers=headers, timeout=15)
            response.raise_for_status()

            self.logger.info("Parsing sitemap XML...")
            soup = BeautifulSoup(response.content, "xml")

            url_entries = soup.find_all("url")
            self.logger.info(f"Found {len(url_entries)} entries in sitemap")

            product_urls = []
            for url_entry in url_entries:
                loc_tag = url_entry.find("loc")
                if not loc_tag:
                    continue

                url = loc_tag.get_text(strip=True)

                # Check if it matches our patterns and is a product URL
                if any(url.startswith(pattern) for pattern in url_patterns):
                    if self.is_product_url(url):
                        product_urls.append(url)

            self.logger.info(f"Found {len(product_urls)} product URLs")
            return product_urls

        except Exception as e:
            self.logger.error(f"Error fetching product URLs: {e}")
            return []

    def is_product_url(self, url):
        """Check if URL is a product page"""
        return bool(re.search(r"p\d{7}", url) or re.search(r"-p\d+", url))

    def scrape_product(self, url):
        """Scrape a single product page with comprehensive variant extraction"""
        self.driver.get(url)
        time.sleep(3)

        # Check if login required
        if (
            "login" in self.driver.current_url.lower()
            or "signin" in self.driver.current_url.lower()
        ):
            self.logger.info("Login required, attempting to login...")
            if not self.login():
                self.logger.error("Login failed. Stopping entire scraping process.")
                raise Exception("Login failed - cannot proceed with scraping")
            # Navigate back to product page after login
            self.driver.get(url)
            time.sleep(2)

            # Verify we're actually logged in by checking if we're still on login page
            if (
                "login" in self.driver.current_url.lower()
                or "signin" in self.driver.current_url.lower()
            ):
                self.logger.error(
                    "Still on login page after login attempt. Login failed. Stopping entire scraping process."
                )
                raise Exception(
                    "Login verification failed - cannot proceed with scraping"
                )

        try:
            # Check for page not found - mark existing records as discontinued
            if "The requested page cannot be found" in self.driver.page_source:
                from apps.quoting.models import SupplierProduct

                marked = SupplierProduct.objects.filter(
                    supplier=self.supplier,
                    url=url,
                    is_discontinued=False,
                ).update(is_discontinued=True)
                self.logger.warning(
                    f"Page not found for URL: {url} "
                    f"(marked {marked} products as discontinued)"
                )
                return []

            # Extract basic product info
            product_name = self.extract_text_by_selector(
                'h1[itemprop="name"]', default="N/A"
            )
            item_no = self.extract_text_by_selector(
                'span[itemprop="productID sku"]', default="N/A"
            )
            description = self.extract_description()
            specifications = self.extract_specifications()
            price_unit = self.extract_price_unit()

            # Validate essential fields
            if not product_name or product_name in ["N/A", "Page Not Found"]:
                self.logger.warning(
                    f"Invalid product_name '{product_name}' for URL: {url}"
                )
                return []

            if not item_no or item_no == "N/A":
                self.logger.warning(f"Invalid item_no '{item_no}' for URL: {url}")
                return []

            # Extract variants using comprehensive method
            variants_data = self.extract_all_variants(
                url, product_name, item_no, description, specifications, price_unit
            )

            # Filter out invalid variants
            valid_variants = []
            for variant in variants_data:
                if (
                    variant.get("variant_id")
                    and variant.get("variant_id") not in [None, "N/A", ""]
                    and variant.get("product_name")
                    and variant.get("product_name")
                    not in [None, "N/A", "Page Not Found"]
                ):
                    valid_variants.append(variant)
                else:
                    self.logger.warning(f"Skipping invalid variant: {variant}")

            return valid_variants

        except Exception as e:
            self.logger.error(f"Error scraping product {url}: {e}")
            return []

    def extract_text_by_selector(self, selector, default="N/A"):
        """Helper to extract text by CSS selector"""
        try:
            element = self.driver.find_element(By.CSS_SELECTOR, selector)
            return element.text.strip() if element else default
        except Exception:
            return default

    def extract_description(self):
        """Extract product description"""
        try:
            description_div = self.driver.find_element(
                By.CSS_SELECTOR, 'div[itemprop="description"]'
            )
            if description_div:
                try:
                    inner_div = description_div.find_element(By.CLASS_NAME, "fr-view")
                    return inner_div.text.strip()
                except Exception:
                    return description_div.text.strip()
        except Exception:
            pass
        return "N/A"

    def extract_specifications(self):
        """Extract product specifications"""
        try:
            spec_elements = self.driver.find_elements(
                By.CSS_SELECTOR, "#specifications table.gvi-name-value tr"
            )
            spec_parts = []
            for row in spec_elements:
                try:
                    name_cell = row.find_element(By.CLASS_NAME, "name")
                    value_cell = row.find_element(By.CLASS_NAME, "value")
                    spec_parts.append(
                        f"{name_cell.text.strip()}: {value_cell.text.strip()}"
                    )
                except Exception:
                    continue
            return "; ".join(spec_parts) if spec_parts else "N/A"
        except Exception:
            return "N/A"

    def extract_price_unit(self):
        """Extract price unit"""
        try:
            price_unit_element = self.driver.find_element(
                By.CSS_SELECTOR, ".after-prices .lbl-price-per"
            )
            return price_unit_element.text.strip()
        except Exception:
            try:
                after_prices = self.driver.find_element(By.CLASS_NAME, "after-prices")
                return after_prices.text.strip()
            except Exception:
                return "N/A"

    def extract_all_variants(
        self, url, product_name, item_no, description, specifications, price_unit
    ):
        """Extract all product variants with comprehensive width handling"""
        all_variants_data = []

        try:
            # Try to find width dropdown first
            width_options = []
            try:
                width_select_element = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.ID, "c0"))
                )
                width_options = [
                    option.get_attribute("value")
                    for option in Select(width_select_element).options
                    if option.get_attribute("value") not in ["", "N/A"]
                ]
                self.logger.info(f"Found width options: {width_options}")
            except Exception as e:
                self.logger.info(f"No width dropdown found: {e}")

            # If no width options, extract variants directly
            if not width_options:
                self.logger.info("No width options found, extracting variants directly")
                return self.extract_variants_direct(
                    url, product_name, item_no, description, specifications, price_unit
                )

            # Handle products with width options
            for width in width_options:
                try:
                    self.logger.info(f"Selecting width: {width}")

                    # Use JavaScript to change width selection
                    self.driver.execute_script(f"""
                        $('#c0').val('{width}').trigger('change');
                    """)
                    time.sleep(3)

                    # Extract variants for this width
                    width_variants = self.extract_variants_for_width(
                        url,
                        product_name,
                        item_no,
                        description,
                        specifications,
                        price_unit,
                        width,
                    )
                    all_variants_data.extend(width_variants)

                except Exception as e:
                    self.logger.error(f"Error processing width {width}: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"Unexpected error in extract_all_variants: {e}")
            return []

        return all_variants_data

    def extract_variants_direct(
        self, url, product_name, item_no, description, specifications, price_unit
    ):
        """Extract variants directly when no width options available"""
        try:
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.ID, "variantId"))
            )

            # Use JavaScript to get option data since select is hidden
            options_data = self.driver.execute_script("""
                var select = document.getElementById('variantId');
                var options = [];
                for (var i = 0; i < select.options.length; i++) {
                    var option = select.options[i];
                    if (option.value && option.value.toUpperCase() !== 'N/A') {
                        options.push({
                            value: option.value,
                            text: option.text.trim(),
                            price: option.getAttribute('data-price'),
                            inventory: option.getAttribute('data-inventory'),
                            imageTags: option.getAttribute('data-image-tags')
                        });
                    }
                }
                return options;
            """)

            self.logger.info(f"Found {len(options_data)} variants via JavaScript")

            variants_data = []
            for option_data in options_data:
                variant_id = option_data["value"]
                price_text = option_data["price"]
                inventory_text = option_data["inventory"]
                raw_text = option_data["text"]
                image_tags = option_data["imageTags"] or ""

                price = (
                    float(price_text.replace("$", "").replace(",", "").strip())
                    if price_text
                    else None
                )
                stock = (
                    int(inventory_text)
                    if inventory_text and inventory_text.isdigit()
                    else 0
                )

                # Parse length from option text
                variant_length = None
                cleaned_text = re.sub(r"\s+", " ", raw_text).strip() if raw_text else ""

                if cleaned_text:
                    length_match = re.search(r"(\d+(?:\.\d+)?)", cleaned_text)
                    if length_match:
                        variant_length = length_match.group(1)
                    else:
                        variant_length = cleaned_text

                # Try to extract width from image tags if available
                variant_width = None
                if image_tags:
                    width_match = re.search(r"v(\d+_\d+)", image_tags)
                    if width_match:
                        variant_width = width_match.group(1).replace("_", ".")

                variants_data.append(
                    {
                        "product_name": product_name,
                        "item_no": item_no,
                        "description": description,
                        "specifications": specifications,
                        "variant_id": variant_id,
                        "variant_width": variant_width,
                        "variant_length": variant_length,
                        "variant_price": price,
                        "price_unit": price_unit,
                        "variant_available_stock": stock,
                        "url": url,
                    }
                )

            self.logger.info(
                f"Successfully extracted {len(variants_data)} variants directly"
            )
            return variants_data

        except Exception as e:
            self.logger.error(f"Could not extract variants directly: {e}")
            return []

    def extract_variants_for_width(
        self, url, product_name, item_no, description, specifications, price_unit, width
    ):
        """Extract variants for a specific width"""
        try:
            # Get variants for this width
            variant_select_element = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.ID, "variantId"))
            )

            # Auto-select first variant to ensure page is updated
            variant_options = Select(variant_select_element).options
            if variant_options:
                first_variant_value = variant_options[0].get_attribute("value")
                if first_variant_value and first_variant_value.upper() != "N/A":
                    self.driver.execute_script(f"""
                        $('#variantId').val('{first_variant_value}').trigger('change');
                    """)
                    time.sleep(2)

            # Extract all variants for this width using JavaScript
            options_data = self.driver.execute_script("""
                var select = document.getElementById('variantId');
                var options = [];
                for (var i = 0; i < select.options.length; i++) {
                    var option = select.options[i];
                    if (option.value && option.value.toUpperCase() !== 'N/A') {
                        options.push({
                            value: option.value,
                            text: option.text.trim(),
                            price: option.getAttribute('data-price'),
                            inventory: option.getAttribute('data-inventory')
                        });
                    }
                }
                return options;
            """)

            self.logger.info(f"Found {len(options_data)} variants for width {width}")

            variants_data = []
            for option_data in options_data:
                variant_id = option_data["value"]
                price_text = option_data["price"]
                inventory_text = option_data["inventory"]
                raw_text = option_data["text"]

                price = (
                    float(price_text.replace("$", "").replace(",", "").strip())
                    if price_text
                    else None
                )
                stock = (
                    int(inventory_text)
                    if inventory_text and inventory_text.isdigit()
                    else 0
                )

                # Parse length from option text
                variant_length = None
                cleaned_text = re.sub(r"\s+", " ", raw_text).strip() if raw_text else ""

                if cleaned_text:
                    length_match = re.search(r"(\d+(?:\.\d+)?)", cleaned_text)
                    if length_match:
                        variant_length = length_match.group(1)
                    else:
                        variant_length = cleaned_text

                variants_data.append(
                    {
                        "product_name": product_name,
                        "item_no": item_no,
                        "description": description,
                        "specifications": specifications,
                        "variant_id": variant_id,
                        "variant_width": width,
                        "variant_length": variant_length,
                        "variant_price": price,
                        "price_unit": price_unit,
                        "variant_available_stock": stock,
                        "url": url,
                    }
                )

            self.logger.info(
                f"Extracted {len(options_data)} variants for width {width}"
            )
            return variants_data

        except Exception as e:
            self.logger.error(f"Could not extract variants for width {width}: {e}")
            return []
