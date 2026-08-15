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
from apps.xero.client import XeroSyncDisabled
from apps.xero.operator_guards import assert_xero_writes_enabled
from apps.xero.sync import (
    ENTITY_CONFIGS,
    XeroSyncEvent,
    deep_sync_xero_data,
    one_way_sync_all_xero_data,
    synchronise_xero_data,
)
from apps.xero.sync_constants import (
    LOCK_TIMEOUT,
    SYNC_STATUS_KEY,
    release_sync_lock,
    require_sync_lock,
)

logger = logging.getLogger(__name__)

_sync_cache = caches["shared"]

DEFAULT_DAYS_BACK = 90

# Explicit map, not getattr(logger, severity): the severity came off an event
# dict, and getattr would happily resolve "exception", "critical" or any other
# logger attribute a typo produced, then silently fall back to info for the
# rest. An unrecognised severity is a producer defect and says so.
EVENT_LOG_LEVELS = {
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


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
            help="With --entity: override the enable_xero_sync gate for that one entity",
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

        # --force only reaches the sync engine on the single-entity path
        # (one_way_sync_all_xero_data takes it; the deep and full generators
        # do not). v1 accepted it everywhere and then drained a generator
        # that had already returned, reporting success having synced nothing.
        if force and not entity:
            raise CommandError(
                "--force is only honoured with --entity: it overrides the "
                "enable_xero_sync gate for one entity, and the deep and full sync "
                "paths have no such override. For a full sync, set "
                "CompanyDefaults.enable_xero_sync (seed_xero_from_database sets it "
                "at the end of a successful seed)."
            )

        # No enable_xero_sync check here: the sync engine owns that decision
        # and raises XeroSyncDisabled, which _run translates. Reading the gate
        # here as well is how this command ended up reporting it three ways.

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
            self._run(
                deep_sync=deep_sync,
                days_back=days_back,
                entity=entity,
                force=force,
                run_id=run_id,
            )
        finally:
            release_sync_lock(run_id)

    def _run(
        self, *, deep_sync: bool, days_back: int, entity: str | None, force: bool, run_id: str
    ) -> None:
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
            self._drain(generator, run_id=run_id)
        # A refusal the operator can act on, not a failure to investigate:
        # reported on its own so it keeps its own wording instead of arriving
        # wrapped in "Xero sync failed", and without the traceback log below.
        except XeroSyncDisabled as exc:
            raise CommandError(
                f"{exc} To sync one entity while it is disabled, run --entity <name> --force."
            ) from exc
        # Reshaped, not swallowed: v1 wrote the error to stderr and exited 0,
        # so a failed sync in a provisioning script looked like a success.
        except Exception as exc:
            logger.exception("Error during manual Xero synchronisation")
            raise CommandError(f"Xero sync failed: {exc}") from exc

        logger.info("Manual Xero synchronisation completed successfully")
        self.stdout.write(self.style.SUCCESS("Manual Xero synchronisation complete."))

    def _drain(self, generator: Iterator[XeroSyncEvent], *, run_id: str) -> None:
        """Log every sync event as it is produced."""
        for event in generator:
            severity = event["severity"]
            if severity not in EVENT_LOG_LEVELS:
                raise ValueError(
                    f"Sync event from {event['entity']} carries unknown severity "
                    f"{severity!r}; expected one of {sorted(EVENT_LOG_LEVELS)}."
                )
            progress = event.get("progress")
            logger.log(
                EVENT_LOG_LEVELS[severity],
                "Sync progress (%s): %s (progress: %s)",
                event["entity"],
                event["message"],
                f"{progress:.2f}" if progress is not None else "N/A",
            )
            # Renew the lease on the lock acquired above, on the same terms as
            # the Celery worker: an inline deep sync (5000 days back during
            # onboarding) is the run most likely to outlive a fixed lease.
            # Owner-checked: an unguarded touch would let a run that already
            # lost its lease extend the SUCCESSOR's lock.
            require_sync_lock(run_id)
