"""Supplier portal scrapers.

``base.BaseScraper`` owns the run; ``base.SeleniumScraper`` adds the headless
Chrome; ``steel_and_tube.SteelAndTubeScraper`` is the one concrete site.

``resolve_scraper`` is how ``manage.py run_scrapers`` turns a stored
``SupplierScraperConfig.scraper_class`` into a class. v1 discovered scrapers by
listing the directory and reflecting over every module for classes whose name
ended in ``Scraper``, then matched the config's dotted path back against them —
two mechanisms for one lookup. v2 keeps the dotted path (it is stored data) and
imports it directly.
"""

from importlib import import_module

from apps.quoting.scrapers.base import (
    BaseScraper,
    PortalLogin,
    ScrapedProduct,
    ScraperBrowserError,
    ScraperCredentialError,
    ScraperLoginError,
    ScraperPageError,
    SeleniumScraper,
)

__all__ = [
    "BaseScraper",
    "PortalLogin",
    "ScrapedProduct",
    "ScraperBrowserError",
    "ScraperCredentialError",
    "ScraperLoginError",
    "ScraperPageError",
    "SeleniumScraper",
    "resolve_scraper",
]


def resolve_scraper(dotted_path: str) -> type[BaseScraper]:
    """Import ``SupplierScraperConfig.scraper_class`` and check it is a scraper."""
    module_path, _, class_name = dotted_path.rpartition(".")
    if not module_path:
        raise ValueError(
            f"scraper_class {dotted_path!r} is not a dotted path "
            f"(expected e.g. 'apps.quoting.scrapers.steel_and_tube.SteelAndTubeScraper')"
        )
    scraper = getattr(import_module(module_path), class_name)
    if not (isinstance(scraper, type) and issubclass(scraper, BaseScraper)):
        raise TypeError(f"scraper_class {dotted_path!r} is not a BaseScraper subclass")
    return scraper
