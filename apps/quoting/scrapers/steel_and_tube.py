"""The Steel & Tube portal scraper, ported from v1 ``scrapers/steel_and_tube.py``.

The one concrete scraper. It logs in to ``portal.steelandtube.co.nz``, reads the
published sitemap for product pages, and turns each page's variant ``<select>``
into ``ScrapedProduct`` rows. Everything about the *run* — which URLs to visit,
the ``ScrapeJob``, batching, the discontinued diff — belongs to ``BaseScraper``;
everything about *Chrome* belongs to ``SeleniumScraper``. This module is only the
site's shape.

Deliberate deviations from v1, all of them the same lesson from the February 2026
outage (the portal password had changed, production was never updated, and the
weekly run kept "succeeding" while writing nothing):

- **v1 never raised.** ``login()`` returned ``False``, every extraction helper
  returned ``"N/A"`` on failure, and ``scrape_product`` wrapped the whole page in
  ``except Exception: return []``. A selector break was therefore indistinguishable
  from a supplier with no stock. Here a page that does not parse raises
  ``ScraperPageError``, which ``BaseScraper._visit`` counts on the job and
  persists as an ``AppError``; a login that does not take raises
  ``ScraperLoginError``, which aborts the run and fails the ``ScrapeJob``.
- **v1 stored the string ``"N/A"``** in ``description``, ``specifications`` and
  ``price_unit`` when a selector missed. v2 stores ``NULL`` (ADR 0040); the LLM
  parser already renders missing fields as "N/A" in its own prompt.
- **v1 read the width ``<select>`` through ``Select`` and the variant
  ``<select>`` through JavaScript** — two implementations of "list this select's
  options", and the JavaScript one exists precisely because the element can be
  hidden. v2 keeps the JavaScript one for both (ADR 0039).
- **v1's ``extract_variants_direct`` and ``extract_variants_for_width``** were
  ~90-line siblings differing only in where the width comes from. One function
  now, with the width passed in.

The selectors themselves are v1's, unchanged — they are a record of what the
live DOM looked like, and guessing at improvements without a run against the site
would be worse than useless.

WHAT LOOKS DATED, in the order it would hurt. Nothing here is changed without a
run against the live portal (``manage.py run_scrapers --supplier "Steel & Tube"
--limit 2``), which no test can substitute for:

1. ``sitemap_0.xml`` is *shard zero* of a sharded sitemap. If the catalogue has
   grown past one shard, everything in ``sitemap_1.xml`` is invisible to us —
   and, on a ``--refresh-old`` run, gets retired. Reading the ``sitemap.xml``
   index instead is the fix; only the live site can say whether it is needed.
2. Both option scripts call jQuery (``$``). If the portal has moved off jQuery,
   every product page raises ``JavascriptException``. That is now loud (the run
   fails on the failure ratio) rather than v1's silent zero rows, but it is the
   single biggest assumption in this file.
3. ``#c0`` is a *positional* id — "characteristic 0". v1 assumed characteristic
   zero is always width and stored it in ``variant_width``; on a product whose
   first characteristic is grade or finish, that column holds the wrong thing.
   Ported as-is, and worth checking against a few real products.
4. ``.fr-view`` is the Froala editor's wrapper class and ``table.gvi-name-value``
   is a vendor-prefixed class: both are CMS-version artefacts, not the portal's
   own markup, and change when Steel & Tube upgrade.
5. ``span[itemprop="productID sku"]`` matches that two-token attribute value
   exactly; reordering the tokens breaks it.
6. Session detection is ``"login" in url or "signin" in url``. A redirect to
   ``/account/sign-in`` (hyphenated) would not match, and the scrape would read
   login pages as products.
7. ``"The requested page cannot be found"`` is an exact English string, and the
   browser user-agent (in ``base.py``) is a truncated Safari/macOS string with no
   Chrome or Safari token — unusual enough for a bot filter to notice.
"""

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final
from xml.etree import ElementTree

import requests
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait

from apps.quoting.scrapers.base import (
    ScrapedProduct,
    ScraperLoginError,
    ScraperPageError,
    SeleniumScraper,
)

PORTAL_URL: Final = "https://portal.steelandtube.co.nz/"
SITEMAP_URL: Final = "https://portal.steelandtube.co.nz/sitemap_0.xml"
SITEMAP_TIMEOUT_SECONDS: Final = 15
# The sitemap is fetched with plain HTTP, outside the browser session, so it
# carries its own (v1) user-agent rather than the browser's.
SITEMAP_USER_AGENT: Final = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)

# Only these two catalogue branches carry products we buy.
PRODUCT_URL_PREFIXES: Final = (
    "https://portal.steelandtube.co.nz/stainless/",
    "https://portal.steelandtube.co.nz/steel/",
)
# A product URL ends in the portal's product code: seven digits after "p", or
# the shorter "-p<n>" form on older listings.
PRODUCT_CODE = re.compile(r"p\d{7}|-p\d+")

# Login form.
USERNAME_FIELD_ID: Final = "UserName"
PASSWORD_FIELD_ID: Final = "Password"  # noqa: S105 -- a DOM element id, not a secret
LOGIN_BUTTON_SELECTOR: Final = "button.btn-medium.btn-login"
USERNAME_TIMEOUT_SECONDS: Final = 10
LOGIN_FIELD_TIMEOUT_SECONDS: Final = 5
LOGIN_COMPLETE_TIMEOUT_SECONDS: Final = 15

# Product page.
NAME_SELECTOR: Final = 'h1[itemprop="name"]'
ITEM_NO_SELECTOR: Final = 'span[itemprop="productID sku"]'
DESCRIPTION_SELECTOR: Final = 'div[itemprop="description"]'
DESCRIPTION_BODY_CLASS: Final = "fr-view"
SPECIFICATION_ROW_SELECTOR: Final = "#specifications table.gvi-name-value tr"
PRICE_UNIT_SELECTOR: Final = ".after-prices .lbl-price-per"
PRICE_BLOCK_CLASS: Final = "after-prices"
PAGE_NOT_FOUND_TEXT: Final = "The requested page cannot be found"
NOT_A_PRODUCT_NAME: Final = "Page Not Found"

# Variant selection. "c0" is the width dropdown, present only on products sold in
# several widths; "variantId" is the length/size dropdown, always present.
WIDTH_SELECT_ID: Final = "c0"
VARIANT_SELECT_ID: Final = "variantId"
WIDTH_SELECT_TIMEOUT_SECONDS: Final = 5
VARIANT_SELECT_TIMEOUT_SECONDS: Final = 15

# The portal repaints prices and stock asynchronously after every selection, with
# no completion signal to wait on; v1's sleeps are the only handle there is.
PAGE_SETTLE_SECONDS: Final = 3
LOGIN_SETTLE_SECONDS: Final = 2
WIDTH_SETTLE_SECONDS: Final = 3
VARIANT_SETTLE_SECONDS: Final = 2

# The variant <select> is hidden, so its options are read out of the DOM rather
# than through Selenium's Select wrapper. Prices and stock live on data-
# attributes of each <option>; the width, when it is encoded at all, is in the
# image-tag attribute.
SELECT_OPTIONS_SCRIPT: Final = """
var select = document.getElementById(arguments[0]);
if (!select) { return null; }
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
"""
CHOOSE_OPTION_SCRIPT: Final = "$('#' + arguments[0]).val(arguments[1]).trigger('change');"

IMAGE_TAG_WIDTH = re.compile(r"v(\d+_\d+)")
LEADING_NUMBER = re.compile(r"(\d+(?:\.\d+)?)")
WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ProductPage:
    """The page-level fields every variant on one product page shares."""

    url: str
    product_name: str
    item_no: str
    description: str | None
    specifications: str | None
    price_unit: str | None


@dataclass(frozen=True, slots=True)
class VariantOption:
    """One ``<option>`` of a portal ``<select>``, as the page's DOM holds it."""

    value: str
    text: str
    price: str | None
    inventory: str | None
    image_tags: str | None


def is_product_url(url: str) -> bool:
    """Report whether a sitemap entry is a product page in a branch we buy from."""
    if not url.startswith(PRODUCT_URL_PREFIXES):
        return False
    return PRODUCT_CODE.search(url) is not None


def parse_sitemap_product_urls(document: bytes) -> list[str]:
    """Pull the product URLs out of a sitemap document.

    Split from the fetch so it can be tested against a saved sitemap: this is the
    only part of the walk that is ours rather than the supplier's.
    """
    # CPython's ElementTree has resolved neither external entities nor nested
    # entity expansions since 3.7.1 — the attacks the rule warns about.
    root = ElementTree.fromstring(document)  # noqa: S314
    urls: list[str] = []
    for element in root.iter():
        # Sitemaps are namespaced; match the local name so a missing or changed
        # xmlns cannot silently yield an empty run.
        if element.tag.rpartition("}")[2] != "loc" or element.text is None:
            continue
        location = element.text.strip()
        if is_product_url(location):
            urls.append(location)
    return urls


def parse_price(text: str | None) -> Decimal | None:
    """Read an option's ``data-price`` (``$1,234.50``) as a number."""
    if text is None or not text.strip():
        return None
    cleaned = text.replace("$", "").replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ScraperPageError(f"Variant price {text!r} is not a number") from exc


def parse_stock(text: str | None) -> int:
    """Read an option's ``data-inventory``; an absent attribute means no stock."""
    if text is None or not text.strip():
        return 0
    quantity = text.strip()
    if not quantity.isdigit():
        raise ScraperPageError(f"Variant inventory {text!r} is not a whole number")
    return int(quantity)


def parse_length(option_text: str) -> str | None:
    """Read the length out of an option label such as ``6.0 m`` or ``Cut to size``."""
    cleaned = WHITESPACE.sub(" ", option_text).strip()
    if not cleaned:
        return None
    number = LEADING_NUMBER.search(cleaned)
    if number is None:
        # Not every length is numeric ("Random", "Cut to size"); keep the label.
        return cleaned
    return number.group(1)


def parse_width_from_image_tags(image_tags: str | None) -> str | None:
    """Read the width the portal encodes in an option's image tags (``v12_5``)."""
    if image_tags is None:
        return None
    width = IMAGE_TAG_WIDTH.search(image_tags)
    if width is None:
        return None
    return width.group(1).replace("_", ".")


def _field(entry: dict[str, object], key: str, select_id: str) -> object:
    if key not in entry:
        raise ScraperPageError(f"An option of #{select_id} has no {key!r} field: {entry!r}")
    return entry[key]


def _required_text(entry: dict[str, object], key: str, select_id: str) -> str:
    value = _field(entry, key, select_id)
    if not isinstance(value, str):
        raise ScraperPageError(f"Option field {key!r} of #{select_id} is {value!r}, not text")
    return value


def _optional_text(entry: dict[str, object], key: str, select_id: str) -> str | None:
    if _field(entry, key, select_id) is None:
        return None
    return _required_text(entry, key, select_id)


def _variant_option(entry: object, select_id: str) -> VariantOption:
    """Validate one row of the option script's result into a typed option."""
    if not isinstance(entry, dict):
        raise ScraperPageError(f"#{select_id} returned {entry!r}, not an option object")
    return VariantOption(
        value=_required_text(entry, "value", select_id),
        text=_required_text(entry, "text", select_id),
        price=_optional_text(entry, "price", select_id),
        inventory=_optional_text(entry, "inventory", select_id),
        image_tags=_optional_text(entry, "imageTags", select_id),
    )


class SteelAndTubeScraper(SeleniumScraper):
    """Scrapes Steel & Tube's trade portal: login, sitemap, per-product variants."""

    # ── The portal ───────────────────────────────────────────────────────

    def login(self) -> None:
        """Sign in to the portal, or raise ``ScraperLoginError`` saying why.

        The success test is the username field disappearing: a rejected password
        re-renders the same form, so the wait times out and this raises rather
        than scraping every page as an anonymous visitor.
        """
        login = self.portal_login()
        self.logger.info("Logging in to %s as %s", PORTAL_URL, login.username)
        try:
            self.driver.get(PORTAL_URL)

            username_field = self._await_clickable(
                (By.ID, USERNAME_FIELD_ID), USERNAME_TIMEOUT_SECONDS
            )
            username_field.clear()
            username_field.send_keys(login.username)

            password_field = self._await_clickable(
                (By.ID, PASSWORD_FIELD_ID), LOGIN_FIELD_TIMEOUT_SECONDS
            )
            password_field.clear()
            password_field.send_keys(login.password)

            self._await_clickable(
                (By.CSS_SELECTOR, LOGIN_BUTTON_SELECTOR), LOGIN_FIELD_TIMEOUT_SECONDS
            ).click()

            # The form posts and redirects; give it a beat before deciding the
            # username field's absence means success rather than a page swap.
            time.sleep(LOGIN_SETTLE_SECONDS)
            WebDriverWait(self.driver, LOGIN_COMPLETE_TIMEOUT_SECONDS).until(
                expected_conditions.invisibility_of_element_located((By.ID, USERNAME_FIELD_ID))
            )
        except WebDriverException as exc:
            raise ScraperLoginError(
                f"Steel & Tube portal login failed for {login.username!r} at {PORTAL_URL}: "
                f"{exc.__class__.__name__}. Check the SupplierCredential row and the portal."
            ) from exc
        self.logger.info("Logged in to the Steel & Tube portal as %s", login.username)

    def product_urls(self) -> list[str]:
        """Every product URL Steel & Tube currently publishes in its sitemap."""
        self.logger.info("Requesting the sitemap from %s", SITEMAP_URL)
        response = requests.get(
            SITEMAP_URL,
            headers={"User-Agent": SITEMAP_USER_AGENT},
            timeout=SITEMAP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        urls = parse_sitemap_product_urls(response.content)
        self.logger.info("Sitemap lists %s product URLs", len(urls))
        return urls

    def scrape_product(self, url: str) -> Sequence[ScrapedProduct]:
        """Read one product page into its variant rows."""
        self.driver.get(url)
        time.sleep(PAGE_SETTLE_SECONDS)
        self._ensure_session(url)

        if PAGE_NOT_FOUND_TEXT in self.driver.page_source:
            # The sitemap still lists it but the portal no longer serves it.
            # Recorded, not acted on: run() retires these only after the health
            # check passes — a portal error page on EVERY url must fail the run,
            # not retire the catalogue one visited page at a time.
            self.not_found_urls.add(url)
            self.logger.warning("Page not found: %s", url)
            return []

        page = self._read_page(url)
        variants = self._read_variants(page)
        if not variants:
            raise ScraperPageError(
                f"No variants on {url} (item {page.item_no}): #{VARIANT_SELECT_ID} "
                f"offered no usable options"
            )
        return variants

    def _ensure_session(self, url: str) -> None:
        """Re-authenticate if the portal bounced us to the login page."""
        if not self._on_login_page():
            return
        self.logger.info("Portal session expired at %s; logging in again", url)
        self.login()
        self.driver.get(url)
        time.sleep(LOGIN_SETTLE_SECONDS)
        if self._on_login_page():
            raise ScraperLoginError(
                f"Still on the login page after re-authenticating (at {url}); "
                f"the portal is not accepting this session"
            )

    def _on_login_page(self) -> bool:
        current = self.driver.current_url.lower()
        return "login" in current or "signin" in current

    # ── One product page ─────────────────────────────────────────────────

    def _read_page(self, url: str) -> ProductPage:
        """Read the fields every variant on the page shares."""
        product_name = self._text(NAME_SELECTOR)
        if product_name is None or product_name == NOT_A_PRODUCT_NAME:
            raise ScraperPageError(
                f"No product name on {url}: {NAME_SELECTOR} gave {product_name!r}"
            )
        item_no = self._text(ITEM_NO_SELECTOR)
        if item_no is None:
            raise ScraperPageError(
                f"No item number on {url} ({product_name}): {ITEM_NO_SELECTOR} matched nothing"
            )
        return ProductPage(
            url=url,
            product_name=product_name,
            item_no=item_no,
            description=self._description(),
            specifications=self._specifications(),
            price_unit=self._price_unit(),
        )

    def _description(self) -> str | None:
        container = self._element(DESCRIPTION_SELECTOR)
        if container is None:
            return None
        try:
            # Rich-text descriptions are wrapped; plain ones are not.
            body = container.find_element(By.CLASS_NAME, DESCRIPTION_BODY_CLASS)
        except NoSuchElementException:
            return _clean(container.text)
        return _clean(body.text)

    def _specifications(self) -> str | None:
        rows = self.driver.find_elements(By.CSS_SELECTOR, SPECIFICATION_ROW_SELECTOR)
        pairs: list[str] = []
        for row in rows:
            try:
                name = row.find_element(By.CLASS_NAME, "name")
                value = row.find_element(By.CLASS_NAME, "value")
            except NoSuchElementException:
                # Spacer and heading rows carry neither cell.
                continue
            pairs.append(f"{name.text.strip()}: {value.text.strip()}")
        if not pairs:
            return None
        return "; ".join(pairs)

    def _price_unit(self) -> str | None:
        unit = self._text(PRICE_UNIT_SELECTOR)
        if unit is not None:
            return unit
        # Older layouts put the unit straight into the price block.
        return self._text(f".{PRICE_BLOCK_CLASS}")

    # ── Variants ─────────────────────────────────────────────────────────

    def _read_variants(self, page: ProductPage) -> list[ScrapedProduct]:
        """Every variant of this product, across every width it is sold in."""
        widths = self._select_options(WIDTH_SELECT_ID, WIDTH_SELECT_TIMEOUT_SECONDS)
        if not widths:
            # Single-width product: no width dropdown at all, or one carrying no
            # real options (v1 treated both the same). The variant dropdown is
            # the whole answer, and the width — if the portal records one — is
            # encoded in the option's image tags.
            options = self._variant_options()
            return [self._to_product(page, option, width=None) for option in options]

        self.logger.info("Product %s is sold in %s widths", page.item_no, len(widths))
        products: list[ScrapedProduct] = []
        for width in widths:
            self._choose(WIDTH_SELECT_ID, width.value, WIDTH_SETTLE_SECONDS)
            options = self._variant_options()
            # Selecting the first variant makes the portal repaint this width's
            # prices and stock levels onto the option attributes.
            self._choose(VARIANT_SELECT_ID, options[0].value, VARIANT_SETTLE_SECONDS)
            products.extend(
                self._to_product(page, option, width=width.value)
                for option in self._variant_options()
            )
        return products

    def _variant_options(self) -> list[VariantOption]:
        options = self._select_options(VARIANT_SELECT_ID, VARIANT_SELECT_TIMEOUT_SECONDS)
        if options is None:
            raise ScraperPageError(
                f"#{VARIANT_SELECT_ID} is missing: the page has no variant dropdown"
            )
        if not options:
            raise ScraperPageError(f"#{VARIANT_SELECT_ID} offered no usable options")
        return options

    def _to_product(
        self, page: ProductPage, option: VariantOption, *, width: str | None
    ) -> ScrapedProduct:
        # A width dropdown states the width outright; without one, the only
        # place the portal records it is the option's image-tag attribute.
        variant_width = (
            width if width is not None else parse_width_from_image_tags(option.image_tags)
        )
        return ScrapedProduct(
            item_no=page.item_no,
            variant_id=option.value,
            product_name=page.product_name,
            url=page.url,
            description=page.description,
            specifications=page.specifications,
            variant_width=variant_width,
            variant_length=parse_length(option.text),
            variant_price=parse_price(option.price),
            price_unit=page.price_unit,
            variant_available_stock=parse_stock(option.inventory),
        )

    # ── The browser, narrowed ────────────────────────────────────────────

    def _select_options(self, select_id: str, timeout: float) -> list[VariantOption] | None:
        """Return this ``<select>``'s usable options, or ``None`` if it is absent.

        Absence is an answer, not an error: the width dropdown only exists on
        multi-width products. The caller decides whether it can live without one.
        """
        try:
            WebDriverWait(self.driver, timeout).until(
                expected_conditions.presence_of_element_located((By.ID, select_id))
            )
        except TimeoutException:
            self.logger.info("No #%s on this page", select_id)
            return None
        raw = self.driver.execute_script(SELECT_OPTIONS_SCRIPT, select_id)
        if raw is None:
            return None
        if not isinstance(raw, list):
            raise ScraperPageError(f"Reading #{select_id} returned {raw!r}, not a list of options")
        return [_variant_option(entry, select_id) for entry in raw]

    def _choose(self, select_id: str, value: str, settle_seconds: float) -> None:
        """Pick an option and let the portal repaint the prices it drives."""
        self.driver.execute_script(CHOOSE_OPTION_SCRIPT, select_id, value)
        time.sleep(settle_seconds)

    def _element(self, selector: str) -> WebElement | None:
        try:
            return self.driver.find_element(By.CSS_SELECTOR, selector)
        except NoSuchElementException:
            return None

    def _text(self, selector: str) -> str | None:
        element = self._element(selector)
        if element is None:
            return None
        return _clean(element.text)

    def _await_clickable(self, locator: tuple[str, str], timeout: float) -> WebElement:
        clickable = expected_conditions.element_to_be_clickable(locator)
        return WebDriverWait(self.driver, timeout).until(clickable)


def _clean(text: str) -> str | None:
    """Trim page text; blank means the field is unset, which is NULL (ADR 0040)."""
    stripped = text.strip()
    if not stripped:
        return None
    return stripped
