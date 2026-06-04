import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.workflow.services.error_persistence import persist_app_error
from apps.workflow.services.search_telemetry import (
    SearchTelemetryService,
    stable_event_hash,
)


class Command(BaseCommand):
    help = "Backfill legacy kanban_search.log entries into SearchTelemetryEvent."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default=str(Path(settings.BASE_DIR) / "logs" / "kanban_search.log"),
            help="Path to the kanban_search.log file.",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            self.stdout.write(self.style.WARNING(f"No log file found at {path}"))
            return

        imported = 0
        duplicates = 0
        skipped = 0
        failed = 0

        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    skipped += 1
                    continue

                try:
                    payload = self._parse_payload(line)
                    if payload.get("event") != "kanban_search_results":
                        skipped += 1
                        continue

                    results = (payload.get("results") or [])[:100]
                    created = SearchTelemetryService.log_search(
                        request=None,
                        domain="kanban",
                        source=payload.get("source") or "legacy_kanban_log",
                        query=payload.get("query") or "",
                        filters=payload.get("filters") or {},
                        result_count=payload.get("result_count") or len(results),
                        returned_result_ids=[
                            result["job_id"]
                            for result in results
                            if isinstance(result, dict) and result.get("job_id")
                        ],
                        metadata={
                            "legacy_log_path": str(path),
                            "legacy_line_number": line_number,
                            "column_id": payload.get("column_id"),
                            "path": payload.get("path"),
                            "query_string": payload.get("query_string"),
                            "user_id": payload.get("user_id"),
                            "user_email": payload.get("user_email"),
                            "results": results,
                        },
                        source_event_hash=stable_event_hash(
                            {
                                "source": "kanban_search.log",
                                "line": line,
                            }
                        ),
                    )
                    if created:
                        imported += 1
                    else:
                        duplicates += 1
                except Exception as exc:
                    failed += 1
                    persist_app_error(exc)

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {path}: imported={imported}, skipped={skipped}, "
                f"duplicates={duplicates}, failed={failed}"
            )
        )

    @staticmethod
    def _parse_payload(line: str) -> dict:
        json_start = line.find("{")
        if json_start == -1:
            raise ValueError("Log line does not contain a JSON object")
        return json.loads(line[json_start:])
