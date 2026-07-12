"""Preview and apply reviewed duplicate-Person merges."""

import csv
from pathlib import Path
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime

from apps.accounts.models import Staff
from apps.company.models import Person
from apps.company.services.duplicate_person_report import (
    DuplicatePersonCandidate,
    DuplicatePersonReportService,
    DuplicatePersonSummary,
)
from apps.company.services.person_merge_service import merge_people

CSV_COLUMNS = [
    "action",
    "confidence",
    "match_kinds",
    "match_values",
    "source_person_id",
    "source_name",
    "source_email",
    "source_companies",
    "source_jobs",
    "source_calls",
    "source_updated_at",
    "destination_person_id",
    "destination_name",
    "destination_email",
    "destination_companies",
    "destination_jobs",
    "destination_calls",
    "destination_updated_at",
]


def _recommended_people(
    candidate: DuplicatePersonCandidate,
) -> tuple[DuplicatePersonSummary, DuplicatePersonSummary]:
    people = [candidate["first_person"], candidate["second_person"]]
    people.sort(
        key=lambda person: (
            not person["is_active"],
            -(person["job_count"] + person["phone_call_count"]),
            -(len(person["company_links"]) + len(person["contact_methods"])),
            person["created_at"],
            person["person_id"],
        )
    )
    destination = people[0]
    source = people[1]
    return source, destination


class Command(BaseCommand):
    help = "Preview duplicate Person candidates or apply a reviewed merge CSV"

    def add_arguments(self, parser: Any) -> None:
        modes = parser.add_mutually_exclusive_group(required=True)
        modes.add_argument("--preview", type=str, help="Write candidate CSV")
        modes.add_argument("--apply", type=str, help="Apply reviewed candidate CSV")

    def handle(self, *args: Any, **options: Any) -> None:
        preview_path = options["preview"]
        apply_path = options["apply"]
        if preview_path is not None:
            self._preview(Path(preview_path))
        elif apply_path is not None:
            self._apply(Path(apply_path))
        else:
            raise CommandError("Specify --preview or --apply")

    def _preview(self, path: Path) -> None:
        if not path.parent.exists():
            raise CommandError(f"Output directory does not exist: {path.parent}")
        report = DuplicatePersonReportService().get_report()
        candidates = report["duplicate_people"]
        candidate_degrees: dict[str, int] = {}
        for candidate in candidates:
            for person in (candidate["first_person"], candidate["second_person"]):
                person_id = person["person_id"]
                candidate_degrees[person_id] = candidate_degrees.get(person_id, 0) + 1

        with path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for candidate in candidates:
                source, destination = _recommended_people(candidate)
                isolated_high = (
                    candidate["confidence"] == "high"
                    and candidate_degrees[source["person_id"]] == 1
                    and candidate_degrees[destination["person_id"]] == 1
                )
                writer.writerow(
                    {
                        "action": "merge" if isolated_high else "",
                        "confidence": candidate["confidence"],
                        "match_kinds": ";".join(
                            sorted({match["kind"] for match in candidate["matches"]})
                        ),
                        "match_values": ";".join(
                            f"{match['kind']}={match['normalized_value']}"
                            for match in candidate["matches"]
                        ),
                        **self._person_columns("source", source),
                        **self._person_columns("destination", destination),
                    }
                )
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {len(candidates)} duplicate-Person candidates to {path}"
            )
        )

    @staticmethod
    def _person_columns(prefix: str, person: DuplicatePersonSummary) -> dict[str, Any]:
        return {
            f"{prefix}_person_id": person["person_id"],
            f"{prefix}_name": person["name"],
            f"{prefix}_email": person["email"] or "",
            f"{prefix}_companies": ";".join(
                link["company_name"] for link in person["company_links"]
            ),
            f"{prefix}_jobs": person["job_count"],
            f"{prefix}_calls": person["phone_call_count"],
            f"{prefix}_updated_at": person["updated_at"].isoformat(),
        }

    def _apply(self, path: Path) -> None:
        if not path.is_file():
            raise CommandError(f"CSV file not found: {path}")
        with path.open(newline="", encoding="utf-8") as input_file:
            reader = csv.DictReader(input_file)
            if reader.fieldnames != CSV_COLUMNS:
                raise CommandError("CSV columns do not match the preview contract")
            selected_rows = [row for row in reader if row["action"].strip() == "merge"]
        if not selected_rows:
            raise CommandError("CSV contains no rows with action=merge")

        report = DuplicatePersonReportService().get_report()
        current_pairs = {
            frozenset(
                [
                    candidate["first_person"]["person_id"],
                    candidate["second_person"]["person_id"],
                ]
            )
            for candidate in report["duplicate_people"]
        }
        merges: list[tuple[UUID, UUID]] = []
        source_ids: set[UUID] = set()
        destination_ids: set[UUID] = set()
        for row_number, row in enumerate(selected_rows, 2):
            source_id = self._uuid(row, "source_person_id", row_number)
            destination_id = self._uuid(row, "destination_person_id", row_number)
            if source_id == destination_id:
                raise CommandError(f"Row {row_number}: source equals destination")
            if source_id in source_ids:
                raise CommandError(f"Row {row_number}: source appears more than once")
            source_ids.add(source_id)
            destination_ids.add(destination_id)
            if frozenset([str(source_id), str(destination_id)]) not in current_pairs:
                raise CommandError(
                    f"Row {row_number}: pair is no longer a duplicate candidate"
                )
            self._validate_timestamp(
                source_id, row["source_updated_at"], "source", row_number
            )
            self._validate_timestamp(
                destination_id,
                row["destination_updated_at"],
                "destination",
                row_number,
            )
            merges.append((source_id, destination_id))
        chained_ids = source_ids & destination_ids
        if chained_ids:
            raise CommandError(
                "A Person cannot be both source and destination in one batch: "
                + ", ".join(
                    str(person_id) for person_id in sorted(chained_ids, key=str)
                )
            )

        staff = Staff.get_automation_user()
        with transaction.atomic():
            for source_id, destination_id in merges:
                counts = merge_people(source_id, destination_id, staff)
                self.stdout.write(f"Merged {source_id} -> {destination_id}: {counts}")
        self.stdout.write(self.style.SUCCESS(f"Applied {len(merges)} Person merges"))

    @staticmethod
    def _uuid(row: dict[str, str], column: str, row_number: int) -> UUID:
        try:
            return UUID(row[column])
        except (KeyError, ValueError) as exc:
            raise CommandError(f"Row {row_number}: invalid {column}") from exc

    @staticmethod
    def _validate_timestamp(
        person_id: UUID, raw_timestamp: str, role: str, row_number: int
    ) -> None:
        expected = parse_datetime(raw_timestamp)
        if expected is None:
            raise CommandError(f"Row {row_number}: invalid {role}_updated_at")
        actual = (
            Person.objects.filter(id=person_id)
            .values_list("updated_at", flat=True)
            .first()
        )
        if actual is None:
            raise CommandError(f"Row {row_number}: {role} Person does not exist")
        if actual != expected:
            raise CommandError(f"Row {row_number}: {role} Person changed after preview")
