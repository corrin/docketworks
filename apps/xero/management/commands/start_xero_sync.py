"""Run one Xero synchronisation inline, without Celery.

The operator-facing counterpart to the beat-dispatched sync: the generator
runs in this process and every event is logged as it arrives, so a failing
sync fails the command rather than disappearing into a worker log.
"""

import logging
import uuid
from collections.abc import Iterator

from django.core.cache import caches
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import close_old_connections

from apps.core.errors import persist_app_error
from apps.xero.operator_guards import assert_xero_writes_enabled
from apps.xero.sync import (
    ENTITY_CONFIGS,
    XeroSyncEvent,
    deep_sync_xero_data,
    one_way_sync_all_xero_data,
    synchronise_xero_data,
)
from apps.xero.sync_constants import LOCK_TIMEOUT, SYNC_STATUS_KEY

logger = logging.getLogger(__name__)

_sync_cache = caches["shared"]

DEFAULT_DAYS_BACK = 90


class Command(BaseCommand):
    """Trigger a one-off Xero synchronisation in the foreground."""

    help = "Run a manual Xero synchronisation, optionally deep or limited to one entity."

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the sync-shape options."""
        parser.add_argument(
            "--deep-sync",
            action="store_true",
            help="Force a deep sync going back --days-back days instead of incremental",
        )
        parser.add_argument(
            "--days-back",
            type=int,
            default=DEFAULT_DAYS_BACK,
            help=f"Days to look back for a deep sync (default: {DEFAULT_DAYS_BACK})",
        )
        parser.add_argument(
            "--entity",
            choices=list(ENTITY_CONFIGS.keys()),
            help="Sync only this entity type (default: sync all)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Override the enable_xero_sync safety check (for setup before seeding)",
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Run the sync, persisting any failure with its context."""
        try:
            self._handle(**options)
        except Exception as exc:
            persist_app_error(exc)
            raise
        finally:
            # After error persistence, never before: an inline sync can
            # outlive Django's connection max age, and closing first would
            # leave the AppError write without a connection.
            close_old_connections()

    def _handle(self, **options: object) -> None:
        deep_sync = bool(options["deep_sync"])
        force = bool(options["force"])
        entity = options["entity"]
        if entity is not None and not isinstance(entity, str):
            raise TypeError("The --entity option must be a string")
        days_back = options["days_back"]
        if not isinstance(days_back, int):
            raise TypeError("The --days-back option must be an integer")

        # A sync pushes local stock into Xero as well as pulling, so a
        # readonly process must not start one.
        assert_xero_writes_enabled("manage.py start_xero_sync")

        # v1 held no lock here, so a manual run could interleave with a
        # beat-dispatched Celery sync and have both write the same entities.
        # The lock value is a run id rather than a Celery task id: there is no
        # message buffer for an inline run, so the progress readers find none.
        run_id = f"manage-py-start-xero-sync:{uuid.uuid4()}"
        if not _sync_cache.add(SYNC_STATUS_KEY, run_id, timeout=LOCK_TIMEOUT):
            raise CommandError(
                f"A Xero sync is already running ({_sync_cache.get(SYNC_STATUS_KEY)}). "
                "Wait for it to finish before starting a manual sync."
            )

        try:
            self._run(deep_sync=deep_sync, days_back=days_back, entity=entity, force=force)
        finally:
            _sync_cache.delete(SYNC_STATUS_KEY)

    def _run(self, *, deep_sync: bool, days_back: int, entity: str | None, force: bool) -> None:
        entities = [entity] if entity else None
        if entity:
            description = f"single entity: {entity}"
        elif deep_sync:
            description = f"deep sync (going back {days_back} days)"
        else:
            description = "normal incremental sync"
        logger.info("Starting manual Xero synchronisation: %s", description)
        self.stdout.write(f"Starting manual Xero synchronisation: {description}")

        try:
            # deep_sync wins when both are given: v1's precedence, and the
            # entity list is passed through to the deep run either way.
            if deep_sync:
                generator = deep_sync_xero_data(days_back=days_back, entities=entities)
            elif entity:
                generator = one_way_sync_all_xero_data(entities=entities, force=force)
            else:
                generator = synchronise_xero_data()
            self._drain(generator)
        # Reshaped, not swallowed: v1 wrote the error to stderr and exited 0,
        # so a failed sync in a provisioning script looked like a success.
        except Exception as exc:
            logger.exception("Error during manual Xero synchronisation")
            raise CommandError(f"Xero sync failed: {exc}") from exc

        logger.info("Manual Xero synchronisation completed successfully")
        self.stdout.write(self.style.SUCCESS("Manual Xero synchronisation complete."))

    def _drain(self, generator: Iterator[XeroSyncEvent]) -> None:
        """Log every sync event as it is produced."""
        for message in generator:
            severity = str(message.get("severity", "info"))
            entity = message.get("entity", "N/A")
            progress = message.get("progress")
            progress_display = f"{progress:.2f}" if isinstance(progress, int | float) else "N/A"
            log = getattr(logger, severity, logger.info)
            log(
                "Sync progress (%s): %s (progress: %s)",
                entity,
                message.get("message", "No message"),
                progress_display,
            )
