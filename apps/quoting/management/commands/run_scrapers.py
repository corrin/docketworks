"""Run the configured supplier-price scrapers (v1 ``run_scrapers`` command).

Operator entry point, also driven by ``apps.quoting.tasks.run_all_scrapers_task``.

v1 discovered scrapers by listing ``apps/quoting/scrapers/``, reflecting over
every module for classes whose name ended in ``Scraper``, and then matching each
one back against ``SupplierScraperConfig.scraper_class`` — two lookup mechanisms
for one question, and a filesystem walk that silently swallowed import errors.
v2 iterates the enabled configs (the rows that decide what runs anyway) and
imports each one's stored dotted path through ``scrapers.resolve_scraper``. The
``--scraper``/``--supplier``/``--limit``/``--force``/``--refresh-old`` flags are
v1's, unchanged.
"""

import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.core.errors import persist_app_error
from apps.quoting.models import SupplierScraperConfig
from apps.quoting.scrapers import resolve_scraper

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Run every enabled supplier scraper, or the subset named by the flags."""

    help = "Run product scrapers for suppliers"

    def add_arguments(self, parser: CommandParser) -> None:
        """Register v1's scraper/supplier selectors and run modifiers."""
        parser.add_argument(
            "--scraper",
            type=str,
            help='Only run this scraper class (e.g. "SteelAndTubeScraper")',
        )
        parser.add_argument(
            "--supplier",
            type=str,
            help='Only run scrapers for suppliers matching this name (e.g. "Steel & Tube")',
        )
        parser.add_argument(
            "--limit", type=int, default=None, help="Limit URLs processed (for testing)"
        )
        parser.add_argument("--force", action="store_true", help="Re-scrape existing products too")
        parser.add_argument(
            "--refresh-old",
            action="store_true",
            help="Refresh already-known products and reconcile discontinued ones",
        )

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ARG002 -- BaseCommand signature
        """Resolve the matching configs and run each scraper in turn."""
        configs = SupplierScraperConfig.objects.select_related(
            "supplier", "active_credential"
        ).filter(is_enabled=True)
        if options["scraper"]:
            configs = configs.filter(scraper_class__endswith=f".{options['scraper']}")
        if options["supplier"]:
            configs = configs.filter(supplier__name__icontains=options["supplier"])

        selected = list(configs)
        if not selected:
            raise SupplierScraperConfig.DoesNotExist(
                "No enabled SupplierScraperConfig matches "
                f"scraper={options['scraper']!r} supplier={options['supplier']!r}"
            )

        logger.info("Running %s scrapers", len(selected))
        for config in selected:
            logger.info("Starting %s for supplier %s", config.scraper_class, config.supplier.name)
            try:
                job = resolve_scraper(config.scraper_class)(
                    config.supplier,
                    limit=options["limit"],
                    force=options["force"],
                    refresh_old=options["refresh_old"],
                ).run()
            except Exception as exc:
                # v1 behaviour: one broken supplier must not cancel the others
                # on the weekly run. The failure is on the ScrapeJob row and,
                # per ADR 0019, on an AppError too.
                persist_app_error(exc)
                logger.exception("Scraper %s failed", config.scraper_class)
                continue
            logger.info(
                "Completed %s for %s: %s (%s scraped, %s failed)",
                config.scraper_class,
                config.supplier.name,
                job.status,
                job.products_scraped,
                job.products_failed,
            )
