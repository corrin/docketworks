"""The Steel & Tube scraper, driven against a fake WebDriver.

The selectors themselves cannot be tested without the live portal — that is the
nature of scraping someone else's DOM. Everything *around* them can be, and this
file is deliberately shaped by February 2026's outage: the portal password had
been changed, production was never updated, and the weekly run went on reporting
success while writing nothing for months. So the tests that matter here are the
ones that prove a scrape cannot fail quietly:

- a credential that cannot log in raises a *named* error before Selenium is
  touched, rather than posting ``None`` at the login form;
- a login the portal does not accept raises, fails the ``ScrapeJob``, and writes
  an ``AppError``;
- a session lost mid-run aborts the run instead of counting every remaining page
  as a failure and finishing "completed" with nothing scraped;
- a page whose selectors no longer match raises, and is counted.

Everything is mocked at the WebDriver boundary: ``FakeDriver`` below answers
``get``/``find_element``/``execute_script`` from canned pages, and the real
``WebDriverWait``, ``expected_conditions`` and page-parsing code run against it.
Nothing here reaches the network — the sitemap comes from a saved fixture.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from apps.company.models import Company
from apps.core.models import AppError
from apps.quoting.models import (
    ScrapeJob,
    SupplierCredential,
    SupplierProduct,
    SupplierScraperConfig,
)
from apps.quoting.scrapers import (
    ScraperBrowserError,
    ScraperCredentialError,
    ScraperLoginError,
    ScraperPageError,
)
from apps.quoting.scrapers import steel_and_tube as sat
from apps.quoting.scrapers.base import CHROME_FLAGS, USER_AGENT
from apps.quoting.scrapers.steel_and_tube import SteelAndTubeScraper
from apps.quoting.tests.conftest import LLM_BOUNDARY, llm_reply, make_price_list

pytestmark = [pytest.mark.django_db]

CHROME = "apps.quoting.scrapers.base.webdriver.Chrome"
REQUESTS_GET = "apps.quoting.scrapers.steel_and_tube.requests.get"
SITEMAP = Path(__file__).parent / "fixtures" / "steelandtube_sitemap.xml"

RHS = "https://portal.steelandtube.co.nz/steel/structural/rhs-50x25x2-0-mild-steel-p1234567"
PLATE = "https://portal.steelandtube.co.nz/steel/plate/plate-3mm-mild-steel-p2345678"
TUBE = "https://portal.steelandtube.co.nz/stainless/tube/tube-316-25-4x1-6-p42"
SITEMAP_PRODUCTS = [RHS, PLATE, TUBE]

CATEGORY = "https://portal.steelandtube.co.nz/steel/structural/rectangular-hollow-section"
ROOFING = "https://portal.steelandtube.co.nz/roofing/longrun/coloursteel-p3456789"
LOGIN_URL = "https://portal.steelandtube.co.nz/account/login"


# ── The WebDriver boundary ───────────────────────────────────────────────


class FakeElement:
    """One DOM element: the text, attributes and actions the scraper uses."""

    def __init__(
        self,
        text: str = "",
        *,
        children: dict[tuple[str, str], "FakeElement"] | None = None,
        on_click: Callable[[], None] | None = None,
    ) -> None:
        self.text = text
        self.children = children or {}
        self.on_click = on_click
        self.typed: list[str] = []
        self.cleared = False

    def find_element(self, by: str, value: str) -> "FakeElement":
        child = self.children.get((by, value))
        if child is None:
            raise NoSuchElementException(f"{by}={value}")
        return child

    def clear(self) -> None:
        self.cleared = True

    def send_keys(self, *keys: str) -> None:
        self.typed.extend(keys)

    def click(self) -> None:
        if self.on_click is not None:
            self.on_click()

    def is_displayed(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True


@dataclass
class FakePage:
    """One canned page: its markup, its elements, and its ``<select>`` options."""

    source: str = ""
    elements: dict[tuple[str, str], FakeElement] = field(default_factory=dict)
    element_lists: dict[tuple[str, str], list[FakeElement]] = field(default_factory=dict)
    options: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    # Width -> the variant options the portal repaints when that width is chosen.
    width_variants: dict[str, list[dict[str, object]]] = field(default_factory=dict)


class FakeDriver:
    """A WebDriver-shaped double: canned pages, a login form, and a session flag."""

    def __init__(  # noqa: PLR0913 -- each knob is one portal misbehaviour a test needs
        self,
        pages: dict[str, FakePage],
        *,
        login_succeeds: bool = True,
        logins_allowed: int | None = None,
        session_recovers: bool = True,
        session_valid: bool = True,
        expire_after: int | None = None,
    ) -> None:
        self.pages = pages
        self.login_succeeds = login_succeeds
        # How many logins the portal accepts before it starts refusing (None =
        # every one). Models a session that cannot be re-established mid-run.
        self.logins_allowed = logins_allowed
        # Whether a successful login actually restores the product session.
        self.session_recovers = session_recovers
        self.session_valid = session_valid
        # Number of page loads served before the portal drops the session.
        self.expire_after = expire_after
        self.logins = 0
        self.logged_in = False
        self.current_url = ""
        self.visited: list[str] = []
        self.chosen: list[tuple[str, str]] = []
        self.quit_calls = 0
        self.username_field = FakeElement()
        self.password_field = FakeElement()
        self.login_button = FakeElement(on_click=self._submit_login)

    def _submit_login(self) -> None:
        self.logins += 1
        refused = self.logins_allowed is not None and self.logins > self.logins_allowed
        if not self.login_succeeds or refused:
            return
        self.logged_in = True
        self.session_valid = self.session_recovers
        self.current_url = "https://portal.steelandtube.co.nz/dashboard"

    def _page(self) -> FakePage:
        return self.pages.get(self.current_url, FakePage())

    # WebDriver surface ---------------------------------------------------

    def get(self, url: str) -> None:
        self.visited.append(url)
        if url == sat.PORTAL_URL:
            self.logged_in = False
            self.current_url = url
            return
        if self.expire_after is not None and len(self.visited) > self.expire_after:
            self.session_valid = False
        if not self.session_valid:
            self.current_url = LOGIN_URL
            return
        self.current_url = url

    @property
    def page_source(self) -> str:
        return self._page().source

    def find_element(self, by: str, value: str) -> FakeElement:
        if (by, value) == (By.ID, sat.USERNAME_FIELD_ID):
            if self.logged_in:
                raise NoSuchElementException("the login form is gone")
            return self.username_field
        if (by, value) == (By.ID, sat.PASSWORD_FIELD_ID):
            return self.password_field
        if (by, value) == (By.CSS_SELECTOR, sat.LOGIN_BUTTON_SELECTOR):
            return self.login_button
        page = self._page()
        if by == By.ID and value in page.options:
            return FakeElement()
        element = page.elements.get((by, value))
        if element is None:
            raise NoSuchElementException(f"{by}={value}")
        return element

    def find_elements(self, by: str, value: str) -> list[FakeElement]:
        return self._page().element_lists.get((by, value), [])

    def execute_script(self, script: str, *args: object) -> object:
        page = self._page()
        if script == sat.SELECT_OPTIONS_SCRIPT:
            return page.options.get(str(args[0]))
        if script == sat.CHOOSE_OPTION_SCRIPT:
            select_id, value = str(args[0]), str(args[1])
            self.chosen.append((select_id, value))
            if select_id == sat.WIDTH_SELECT_ID:
                page.options[sat.VARIANT_SELECT_ID] = page.width_variants[value]
            return None
        raise AssertionError(f"The scraper ran an unexpected script: {script!r}")

    def quit(self) -> None:
        self.quit_calls += 1


# ── Page builders ────────────────────────────────────────────────────────


def option(
    value: str,
    text: str,
    *,
    price: str | None = None,
    inventory: str | None = None,
    image_tags: str | None = None,
) -> dict[str, object]:
    """One ``<option>`` as the option-reading script returns it."""
    return {
        "value": value,
        "text": text,
        "price": price,
        "inventory": inventory,
        "imageTags": image_tags,
    }


def product_page(  # noqa: PLR0913 -- a page factory: every field is an axis a test varies
    *,
    name: str | None = "50x25x2.0 RHS Mild Steel",
    item_no: str | None = "RHS502520",
    description: str | None = "Rectangular hollow section, mild steel.",
    specifications: dict[str, str] | None = None,
    price_unit: str | None = "per length",
    variants: list[dict[str, object]] | None = None,
    width_variants: dict[str, list[dict[str, object]]] | None = None,
) -> FakePage:
    """A product page carrying whichever of the portal's fields a test needs."""
    elements: dict[tuple[str, str], FakeElement] = {}
    if name is not None:
        elements[By.CSS_SELECTOR, sat.NAME_SELECTOR] = FakeElement(name)
    if item_no is not None:
        elements[By.CSS_SELECTOR, sat.ITEM_NO_SELECTOR] = FakeElement(item_no)
    if description is not None:
        elements[By.CSS_SELECTOR, sat.DESCRIPTION_SELECTOR] = FakeElement(
            "unwrapped fallback text",
            children={(By.CLASS_NAME, sat.DESCRIPTION_BODY_CLASS): FakeElement(description)},
        )
    if price_unit is not None:
        elements[By.CSS_SELECTOR, sat.PRICE_UNIT_SELECTOR] = FakeElement(price_unit)

    rows = [
        FakeElement(
            children={
                (By.CLASS_NAME, "name"): FakeElement(spec_name),
                (By.CLASS_NAME, "value"): FakeElement(spec_value),
            }
        )
        for spec_name, spec_value in (specifications or {}).items()
    ]

    options: dict[str, list[dict[str, object]]] = {}
    if variants is not None:
        options[sat.VARIANT_SELECT_ID] = variants
    if width_variants is not None:
        options[sat.WIDTH_SELECT_ID] = [option(width, f"{width} mm") for width in width_variants]
        first = next(iter(width_variants))
        options[sat.VARIANT_SELECT_ID] = width_variants[first]

    return FakePage(
        source=f"<html><h1>{name}</h1></html>",
        elements=elements,
        element_lists={(By.CSS_SELECTOR, sat.SPECIFICATION_ROW_SELECTOR): rows},
        options=options,
        width_variants=width_variants or {},
    )


def simple_page() -> FakePage:
    """A single-width product with two lengths in stock."""
    return product_page(
        specifications={"Grade": "300+", "Finish": "Black"},
        variants=[
            option("RHS502520-6", " 6.0 m ", price="$45.20", inventory="12", image_tags="v50_0"),
            option("RHS502520-8", "8.0 m", price="$1,260.75", inventory="0"),
        ],
    )


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Collapse the portal's settle-sleeps and element waits; keep the logic."""
    for name in (
        "PAGE_SETTLE_SECONDS",
        "LOGIN_SETTLE_SECONDS",
        "WIDTH_SETTLE_SECONDS",
        "VARIANT_SETTLE_SECONDS",
        "USERNAME_TIMEOUT_SECONDS",
        "LOGIN_FIELD_TIMEOUT_SECONDS",
        "LOGIN_COMPLETE_TIMEOUT_SECONDS",
        "WIDTH_SELECT_TIMEOUT_SECONDS",
        "VARIANT_SELECT_TIMEOUT_SECONDS",
    ):
        monkeypatch.setattr(sat, name, 0)


def configure(
    supplier: Company,
    *,
    credential_type: str = SupplierCredential.CredentialType.USERNAME_PASSWORD,
    username: str | None = "trade@example.test",
    password: str | None = "portal-pass",  # noqa: S107 -- a fixture value, not a secret
    api_key: str | None = None,
) -> SupplierScraperConfig:
    """Enable the Steel & Tube scraper for a supplier, with a stored credential."""
    credential = SupplierCredential.objects.create(
        supplier=supplier,
        label="Trade portal",
        credential_type=credential_type,
        username=username,
        password=password,
        api_key=api_key,
    )
    return SupplierScraperConfig.objects.create(
        supplier=supplier,
        scraper_class="apps.quoting.scrapers.steel_and_tube.SteelAndTubeScraper",
        portal_url=sat.PORTAL_URL,
        active_credential=credential,
    )


def open_scraper(supplier: Company, driver: FakeDriver, **kwargs: Any) -> SteelAndTubeScraper:
    """A scraper whose browser seam is the fake driver, already opened."""
    scraper = SteelAndTubeScraper(supplier, **kwargs)
    with patch(CHROME, return_value=driver):
        scraper.open_browser()
    return scraper


def sitemap_response() -> Mock:
    """A ``requests`` response carrying the saved sitemap."""
    response = Mock()
    response.content = SITEMAP.read_bytes()
    return response


# ── The sitemap walk ─────────────────────────────────────────────────────


class TestSitemap:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            (RHS, True),
            (TUBE, True),
            (CATEGORY, False),
            ("https://portal.steelandtube.co.nz/", False),
            (ROOFING, False),  # right shape, branch we do not buy from
        ],
    )
    def test_only_coded_pages_under_a_bought_branch_are_products(
        self, url: str, expected: bool
    ) -> None:
        assert sat.is_product_url(url) is expected

    def test_the_saved_sitemap_yields_exactly_its_product_pages(self) -> None:
        assert sat.parse_sitemap_product_urls(SITEMAP.read_bytes()) == SITEMAP_PRODUCTS

    def test_a_sitemap_whose_namespace_changed_still_parses(self) -> None:
        """Matching the local name keeps a namespace change from emptying a run."""
        document = SITEMAP.read_bytes().replace(
            b'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"', b""
        )

        assert sat.parse_sitemap_product_urls(document) == SITEMAP_PRODUCTS

    def test_product_urls_reads_the_published_sitemap(self, supplier: Company) -> None:
        scraper = SteelAndTubeScraper(supplier)

        with patch(REQUESTS_GET, return_value=sitemap_response()) as fetch:
            assert scraper.product_urls() == SITEMAP_PRODUCTS

        assert fetch.call_args.args == (sat.SITEMAP_URL,)
        assert fetch.call_args.kwargs["timeout"] == sat.SITEMAP_TIMEOUT_SECONDS

    def test_a_sitemap_the_portal_refuses_is_raised_not_swallowed(self, supplier: Company) -> None:
        """v1 returned [] here, which the run then reported as 'no products found'."""
        response = Mock()
        response.raise_for_status.side_effect = RuntimeError("503 Service Unavailable")

        with (
            patch(REQUESTS_GET, return_value=response),
            pytest.raises(RuntimeError, match="503 Service Unavailable"),
        ):
            SteelAndTubeScraper(supplier).product_urls()


# ── Credentials and login ────────────────────────────────────────────────


class TestCredentials:
    def test_the_stored_username_and_password_are_typed_into_the_portal(
        self, supplier: Company
    ) -> None:
        configure(supplier)
        driver = FakeDriver({})
        scraper = open_scraper(supplier, driver)

        scraper.login()

        assert driver.username_field.typed == ["trade@example.test"]
        assert driver.password_field.typed == ["portal-pass"]
        assert driver.username_field.cleared is True

    def test_an_api_key_credential_cannot_log_in_and_says_so(self, supplier: Company) -> None:
        configure(
            supplier,
            credential_type=SupplierCredential.CredentialType.API_KEY,
            username=None,
            password=None,
            api_key="not-a-portal-login",
        )
        scraper = open_scraper(supplier, FakeDriver({}))

        with pytest.raises(ScraperCredentialError, match="username_password"):
            scraper.login()

    def test_a_credential_with_no_password_fails_before_the_browser_is_used(
        self, supplier: Company
    ) -> None:
        """February 2026's shape: the row is there, the material is not."""
        configure(supplier, password=None)
        driver = FakeDriver({})
        scraper = open_scraper(supplier, driver)

        with pytest.raises(ScraperCredentialError, match=supplier.name):
            scraper.login()

        assert driver.visited == []

    def test_a_supplier_with_no_enabled_config_is_a_loud_failure(self, supplier: Company) -> None:
        scraper = open_scraper(supplier, FakeDriver({}))

        with pytest.raises(SupplierScraperConfig.DoesNotExist):
            scraper.login()


class TestLogin:
    def test_a_portal_that_keeps_showing_the_login_form_raises(self, supplier: Company) -> None:
        """A changed password re-renders the same form; that must not read as success."""
        configure(supplier)
        scraper = open_scraper(supplier, FakeDriver({}, login_succeeds=False))

        with pytest.raises(ScraperLoginError, match="login failed") as failure:
            scraper.login()

        assert "trade@example.test" in str(failure.value)
        # The real cause is chained, not swallowed (ADR 0038).
        assert failure.value.__cause__ is not None


# ── One product page ─────────────────────────────────────────────────────


class TestScrapeProduct:
    def test_a_single_width_product_yields_one_row_per_length(self, supplier: Company) -> None:
        scraper = open_scraper(supplier, FakeDriver({RHS: simple_page()}))

        products = scraper.scrape_product(RHS)

        assert [product.variant_id for product in products] == ["RHS502520-6", "RHS502520-8"]
        first = products[0]
        assert first.item_no == "RHS502520"
        assert first.product_name == "50x25x2.0 RHS Mild Steel"
        assert first.variant_price == Decimal("45.20")
        assert first.variant_available_stock == 12
        assert first.variant_length == "6.0"
        # No width dropdown, so the width comes out of the option's image tags.
        assert first.variant_width == "50.0"
        assert first.specifications == "Grade: 300+; Finish: Black"
        assert first.price_unit == "per length"
        assert products[1].variant_price == Decimal("1260.75")
        assert products[1].variant_available_stock == 0
        assert products[1].variant_width is None

    def test_a_multi_width_product_is_read_once_per_width(self, supplier: Company) -> None:
        page = product_page(
            width_variants={
                "50": [option("FL50-6", "6.0 m", price="$30.00", inventory="4")],
                "75": [option("FL75-6", "6.0 m", price="$40.00", inventory="2")],
            }
        )
        driver = FakeDriver({RHS: page})
        scraper = open_scraper(supplier, driver)

        products = scraper.scrape_product(RHS)

        assert [(p.variant_id, p.variant_width) for p in products] == [
            ("FL50-6", "50"),
            ("FL75-6", "75"),
        ]
        # Each width is selected, then its first variant, to make the portal
        # repaint that width's prices onto the option attributes.
        assert driver.chosen == [
            (sat.WIDTH_SELECT_ID, "50"),
            (sat.VARIANT_SELECT_ID, "FL50-6"),
            (sat.WIDTH_SELECT_ID, "75"),
            (sat.VARIANT_SELECT_ID, "FL75-6"),
        ]

    def test_a_length_the_portal_words_rather_than_measures_is_kept_verbatim(
        self, supplier: Company
    ) -> None:
        page = product_page(variants=[option("CUT", "Cut to size", price="$9.99")])
        scraper = open_scraper(supplier, FakeDriver({RHS: page}))

        products = scraper.scrape_product(RHS)

        assert products[0].variant_length == "Cut to size"
        assert products[0].variant_available_stock == 0

    def test_a_missing_description_is_null_not_the_string_na(self, supplier: Company) -> None:
        """v1 wrote the literal "N/A" into the column the LLM parser then read."""
        page = product_page(description=None, price_unit=None, variants=[option("A", "6.0 m")])
        scraper = open_scraper(supplier, FakeDriver({RHS: page}))

        products = scraper.scrape_product(RHS)

        assert products[0].description is None
        assert products[0].specifications is None
        assert products[0].price_unit is None

    def test_a_page_the_portal_no_longer_serves_is_recorded_not_retired(
        self, supplier: Company
    ) -> None:
        """Retirement is run()'s decision, behind the health and --limit gates.

        Retiring from inside scrape_product meant a portal serving one error
        page for every URL (lost CDN, template change) retired every visited
        product BEFORE the run was declared unhealthy.
        """
        price_list = make_price_list(supplier)
        stale = SupplierProduct.objects.create(
            supplier=supplier,
            price_list=price_list,
            product_name="Withdrawn",
            item_no="OLD-1",
            variant_id="v1",
            url=RHS,
        )
        gone = FakePage(source=f"<html>{sat.PAGE_NOT_FOUND_TEXT}</html>")
        scraper = open_scraper(supplier, FakeDriver({RHS: gone}))

        assert scraper.scrape_product(RHS) == []

        assert scraper.not_found_urls == {RHS}
        stale.refresh_from_db()
        assert stale.is_discontinued is False

    def test_a_page_whose_name_selector_no_longer_matches_raises(self, supplier: Company) -> None:
        """The supplier-redesign case: loud, and it names the selector to fix."""
        page = product_page(name=None, variants=[option("A", "6.0 m")])
        scraper = open_scraper(supplier, FakeDriver({RHS: page}))

        with pytest.raises(ScraperPageError, match=r"No product name"):
            scraper.scrape_product(RHS)

    def test_a_page_with_no_variant_dropdown_raises(self, supplier: Company) -> None:
        scraper = open_scraper(supplier, FakeDriver({RHS: product_page(variants=None)}))

        with pytest.raises(ScraperPageError, match=sat.VARIANT_SELECT_ID):
            scraper.scrape_product(RHS)

    def test_an_inventory_that_is_not_a_number_raises_rather_than_reading_as_zero(
        self, supplier: Company
    ) -> None:
        page = product_page(variants=[option("A", "6.0 m", inventory="lots")])
        scraper = open_scraper(supplier, FakeDriver({RHS: page}))

        with pytest.raises(ScraperPageError, match="not a whole number"):
            scraper.scrape_product(RHS)

    def test_a_price_that_is_not_a_number_raises(self, supplier: Company) -> None:
        page = product_page(variants=[option("A", "6.0 m", price="POA")])
        scraper = open_scraper(supplier, FakeDriver({RHS: page}))

        with pytest.raises(ScraperPageError, match="not a number"):
            scraper.scrape_product(RHS)

    def test_an_expired_session_is_re_authenticated_and_the_page_re_read(
        self, supplier: Company
    ) -> None:
        configure(supplier)
        driver = FakeDriver({RHS: simple_page()}, session_valid=False)
        scraper = open_scraper(supplier, driver)

        products = scraper.scrape_product(RHS)

        assert len(products) == 2
        assert driver.visited == [RHS, sat.PORTAL_URL, RHS]

    def test_a_portal_that_refuses_the_re_login_raises(self, supplier: Company) -> None:
        configure(supplier)
        driver = FakeDriver({RHS: simple_page()}, login_succeeds=False, session_valid=False)
        scraper = open_scraper(supplier, driver)

        with pytest.raises(ScraperLoginError, match="login failed"):
            scraper.scrape_product(RHS)

    def test_a_login_that_takes_but_does_not_restore_the_session_raises(
        self, supplier: Company
    ) -> None:
        """The form accepts us and the product pages still bounce: stop, loudly."""
        configure(supplier)
        driver = FakeDriver({RHS: simple_page()}, session_valid=False, session_recovers=False)
        scraper = open_scraper(supplier, driver)

        with pytest.raises(ScraperLoginError, match="Still on the login page"):
            scraper.scrape_product(RHS)


# ── The browser lifecycle ────────────────────────────────────────────────


class TestBrowserLifecycle:
    def test_the_chrome_options_carry_v1s_tuning_and_a_private_profile(
        self, supplier: Company
    ) -> None:
        scraper = SteelAndTubeScraper(supplier)

        arguments = scraper.chrome_options().arguments

        assert set(CHROME_FLAGS) <= set(arguments)
        assert any(argument.startswith("--user-data-dir=/") for argument in arguments)
        assert f"user-agent={USER_AGENT}" in arguments

    def test_each_run_gets_its_own_profile_directory(self, supplier: Company) -> None:
        """Chrome refuses to start twice against one profile; runs can overlap."""
        profiles = {
            profile(SteelAndTubeScraper(supplier).chrome_options().arguments) for _ in range(2)
        }

        assert len(profiles) == 2

    def test_the_profile_is_deleted_when_the_browser_closes(self, supplier: Company) -> None:
        """v1 left one profile directory behind per run, forever."""
        scraper = SteelAndTubeScraper(supplier)
        driver = FakeDriver({})
        with patch(CHROME, return_value=driver) as chrome:
            scraper.open_browser()
        directory = Path(profile(chrome.call_args.kwargs["options"].arguments))
        assert directory.exists()

        scraper.close_browser()

        assert driver.quit_calls == 1
        assert not directory.exists()

    def test_using_the_browser_before_opening_it_is_a_named_failure(
        self, supplier: Company
    ) -> None:
        with pytest.raises(ScraperBrowserError, match="before open_browser"):
            SteelAndTubeScraper(supplier).driver.get(sat.PORTAL_URL)

    def test_opening_a_second_browser_on_one_scraper_is_refused(self, supplier: Company) -> None:
        scraper = SteelAndTubeScraper(supplier)
        with patch(CHROME, return_value=FakeDriver({})):
            scraper.open_browser()

            with pytest.raises(ScraperBrowserError, match="already running"):
                scraper.open_browser()

        scraper.close_browser()


def error_message(job: ScrapeJob) -> str:
    """The failure a job recorded — asserted present, so the test reads plainly."""
    assert job.error_message is not None
    return job.error_message


def profile(arguments: list[str]) -> str:
    """The profile directory out of a Chrome argument list."""
    for argument in arguments:
        if argument.startswith("--user-data-dir="):
            return argument.removeprefix("--user-data-dir=")
    raise AssertionError(f"No --user-data-dir in {arguments}")


# ── The whole run ────────────────────────────────────────────────────────


@pytest.fixture
def pages() -> dict[str, FakePage]:
    """A page for every product the saved sitemap publishes."""
    return {
        RHS: simple_page(),
        PLATE: product_page(
            name="3mm Plate Mild Steel",
            item_no="PLATE-3",
            variants=[option("PLATE-3-2400", "2400", price="$310.00", inventory="6")],
        ),
        TUBE: product_page(
            name="316 Tube 25.4x1.6",
            item_no="TUBE-316",
            variants=[option("TUBE-316-6", "6.0 m", price="$88.00", inventory="3")],
        ),
    }


def run_scrape(supplier: Company, driver: FakeDriver, **kwargs: Any) -> ScrapeJob:
    """Run a whole scrape against the fake browser and the saved sitemap."""
    scraper = SteelAndTubeScraper(supplier, **kwargs)
    with (
        patch(CHROME, return_value=driver),
        patch(REQUESTS_GET, return_value=sitemap_response()),
        patch(LLM_BOUNDARY, return_value=llm_reply({"item_code": "RHS502520"})),
    ):
        return scraper.run()


class TestRun:
    def test_a_clean_run_records_the_job_and_writes_every_variant(
        self, supplier: Company, pages: dict[str, FakePage]
    ) -> None:
        configure(supplier)

        driver = FakeDriver(pages)

        job = run_scrape(supplier, driver)

        assert job.status == "completed"
        assert job.products_scraped == 3
        assert job.products_failed == 0
        assert SupplierProduct.objects.count() == 4
        assert driver.quit_calls == 1

    def test_a_login_the_portal_refuses_fails_the_job_and_scrapes_nothing(
        self, supplier: Company, pages: dict[str, FakePage]
    ) -> None:
        """February 2026, exactly: the password changed and nobody was told."""
        configure(supplier)

        with pytest.raises(ScraperLoginError):
            run_scrape(supplier, FakeDriver(pages, login_succeeds=False))

        job = ScrapeJob.objects.get()
        assert job.status == "failed"
        assert "login failed" in error_message(job)
        assert job.completed_at is not None
        assert SupplierProduct.objects.count() == 0
        assert AppError.objects.filter(message__contains="login failed").exists()

    def test_a_credential_that_cannot_log_in_fails_the_job_by_name(
        self, supplier: Company, pages: dict[str, FakePage]
    ) -> None:
        configure(supplier, username=None)

        with pytest.raises(ScraperCredentialError):
            run_scrape(supplier, FakeDriver(pages))

        job = ScrapeJob.objects.get()
        assert job.status == "failed"
        assert "SupplierCredential" in error_message(job)

    def test_a_session_lost_part_way_aborts_the_run_instead_of_finishing_empty(
        self, supplier: Company, pages: dict[str, FakePage]
    ) -> None:
        """Counting every remaining page as a failure would still report success."""
        configure(supplier)
        # One login accepted (the run's own), then the portal drops the session
        # after the second page load and refuses to give it back.
        driver = FakeDriver(pages, logins_allowed=1, expire_after=2)

        with pytest.raises(ScraperLoginError):
            run_scrape(supplier, driver)

        job = ScrapeJob.objects.get()
        assert job.status == "failed"
        assert "login failed" in error_message(job)
        # Not "completed, 2 pages failed": the third URL was never even tried.
        assert RHS not in driver.visited

    def test_refresh_old_retires_what_left_the_sitemap_and_restores_what_came_back(
        self, supplier: Company, pages: dict[str, FakePage]
    ) -> None:
        configure(supplier)
        price_list = make_price_list(supplier)
        withdrawn = SupplierProduct.objects.create(
            supplier=supplier,
            price_list=price_list,
            product_name="Withdrawn",
            item_no="OLD-1",
            variant_id="v1",
            url="https://portal.steelandtube.co.nz/steel/gone/withdrawn-p9999999",
        )
        returned = SupplierProduct.objects.create(
            supplier=supplier,
            price_list=price_list,
            product_name="Back in the catalogue",
            item_no="TUBE-316",
            variant_id="TUBE-316-6",
            url=TUBE,
            is_discontinued=True,
        )

        job = run_scrape(supplier, FakeDriver(pages), refresh_old=True)

        assert job.status == "completed"
        withdrawn.refresh_from_db()
        returned.refresh_from_db()
        assert withdrawn.is_discontinued is True
        assert returned.is_discontinued is False

    def test_one_broken_page_is_counted_and_the_run_carries_on(
        self, supplier: Company, pages: dict[str, FakePage]
    ) -> None:
        configure(supplier)
        pages[PLATE] = product_page(name=None, variants=[option("A", "6.0 m")])

        job = run_scrape(supplier, FakeDriver(pages))

        assert job.status == "completed"
        assert job.products_scraped == 2
        assert job.products_failed == 1
        assert AppError.objects.filter(message__contains="No product name").exists()

    def test_the_limit_throttles_a_run_to_a_handful_of_pages(
        self, supplier: Company, pages: dict[str, FakePage]
    ) -> None:
        configure(supplier)

        job = run_scrape(supplier, FakeDriver(pages), limit=1)

        assert job.products_scraped == 1
