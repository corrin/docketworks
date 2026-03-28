import logging

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.workflow.api.xero.sync import (
    ENTITY_CONFIGS,
    deep_sync_xero_data,
    one_way_sync_all_xero_data,
    synchronise_xero_data,
)

logger = logging.getLogger("xero")


class Command(BaseCommand):
    help = "Triggers a manual, one-off Xero synchronization with options for deep sync and entity selection."

    def add_arguments(self, parser):
        parser.add_argument(
            "--deep-sync",
            action="store_true",
            help="Force a deep sync going back many days instead of normal incremental sync",
        )
        parser.add_argument(
            "--days-back",
            type=int,
            default=90,
            help="Number of days to look back for deep sync (default: 90)",
        )
        parser.add_argument(
            "--entity",
            choices=list(ENTITY_CONFIGS.keys()),
            help="Sync only the specified entity type (default: sync all)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Override enable_xero_sync safety check (for setup before seeding)",
        )

    def handle(self, *args, **options):
        # Parse options
        deep_sync = options["deep_sync"]
        days_back = options["days_back"]
        entity = options["entity"]
        force = options["force"]

        # Convert single entity to list
        entities = [entity] if entity else None

        # Determine sync type and log the plan
        if entity:
            sync_type = f"single entity: {entity}"
        elif deep_sync:
            sync_type = f"deep sync (going back {days_back} days)"
        else:
            sync_type = "normal incremental sync"

        logger.info(f"Starting manual Xero synchronization: {sync_type}")

        try:
            # Choose the appropriate sync function
            if entity or deep_sync:
                if deep_sync:
                    logger.info(f"Starting deep sync looking back {days_back} days")
                    sync_generator = deep_sync_xero_data(
                        days_back=days_back, entities=entities
                    )
                else:
                    logger.info(f"Starting incremental sync for {entity}")
                    sync_generator = one_way_sync_all_xero_data(
                        entities=entities, force=force
                    )
            else:
                logger.info("Starting normal bidirectional sync")
                sync_generator = synchronise_xero_data()

            # Process the sync messages
            for message in sync_generator:
                # Log messages from the sync process
                severity = message.get("severity", "info")
                msg_text = message.get("message", "No message")
                msg_entity = message.get("entity", "N/A")
                progress = message.get("progress", "N/A")

                log_func = getattr(logger, severity, logger.info)
                progress_display = (
                    "N/A"
                    if not isinstance(progress, (int, float))
                    else f"{progress:.2f}"
                )
                log_func(
                    f"Sync Progress ({msg_entity}): {msg_text} (Progress: {progress_display})"
                )

            logger.info("Manual Xero synchronization completed successfully.")

        except Exception as e:
            logger.error(
                f"Error during manual Xero synchronization: {e}", exc_info=True
            )
            self.stderr.write(self.style.ERROR(f"Xero sync failed: {e}"))

        close_old_connections()
        logger.info("Manual Xero synchronization command finished.")
