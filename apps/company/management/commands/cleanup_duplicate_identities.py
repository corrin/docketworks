"""Preview and apply grouped Company and Person duplicate decisions."""

import csv
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Staff
from apps.company.services.company_merge_service import merge_companies
from apps.company.services.duplicate_identity_report import (
    DuplicateCompanyGroup,
    DuplicateIdentityReportService,
    DuplicatePersonGroup,
)
from apps.company.services.person_merge_service import merge_people

EntityKind = Literal["company", "person"]
CSV_COLUMNS = [
    "entity_kind",
    "action",
    "group_id",
    "fingerprint",
    "recommendation",
    "canonical_id",
    "members",
    "reason_codes",
    "evidence",
]


class Command(BaseCommand):
    help = "Preview duplicate identity groups or apply a reviewed merge CSV"

    def add_arguments(self, parser: Any) -> None:
        modes = parser.add_mutually_exclusive_group(required=True)
        modes.add_argument("--preview", type=str, help="Write grouped candidate CSV")
        modes.add_argument("--apply", type=str, help="Apply reviewed grouped CSV")

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
        report = DuplicateIdentityReportService().get_report()
        rows = [self._company_row(group) for group in report["company_groups"]] + [
            self._person_row(group) for group in report["person_groups"]
        ]
        with path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        self.stdout.write(
            self.style.SUCCESS(f"Wrote {len(rows)} duplicate identity groups to {path}")
        )

    @staticmethod
    def _company_row(group: DuplicateCompanyGroup) -> dict[str, str]:
        return {
            "entity_kind": "company",
            "action": "merge" if group["recommendation"] == "merge" else "",
            "group_id": group["group_id"],
            "fingerprint": group["fingerprint"],
            "recommendation": group["recommendation"],
            "canonical_id": group["canonical_id"] or "",
            "members": "; ".join(
                f"{member['company_id']}={member['name']}"
                for member in group["members"]
            ),
            "reason_codes": ";".join(group["reason_codes"]),
            "evidence": "; ".join(
                f"{item['kind']}={item['normalized_value']}"
                for item in group["evidence"]
            ),
        }

    @staticmethod
    def _person_row(group: DuplicatePersonGroup) -> dict[str, str]:
        return {
            "entity_kind": "person",
            "action": "merge" if group["recommendation"] == "merge" else "",
            "group_id": group["group_id"],
            "fingerprint": group["fingerprint"],
            "recommendation": group["recommendation"],
            "canonical_id": group["canonical_id"] or "",
            "members": "; ".join(
                f"{member['person_id']}={member['name']}" for member in group["members"]
            ),
            "reason_codes": ";".join(group["reason_codes"]),
            "evidence": "; ".join(
                f"{item['kind']}={item['normalized_value']}"
                for item in group["evidence"]
            ),
        }

    def _apply(self, path: Path) -> None:
        if not path.is_file():
            raise CommandError(f"CSV file not found: {path}")
        with path.open(newline="", encoding="utf-8") as input_file:
            reader = csv.DictReader(input_file)
            if reader.fieldnames != CSV_COLUMNS:
                raise CommandError("CSV columns do not match the preview contract")
            selected = [row for row in reader if row["action"].strip() == "merge"]
        if not selected:
            raise CommandError("CSV contains no rows with action=merge")

        report = DuplicateIdentityReportService().get_report()
        current_companies = {
            ("company", group["group_id"]): group for group in report["company_groups"]
        }
        current_people = {
            ("person", group["group_id"]): group for group in report["person_groups"]
        }
        decisions: list[tuple[EntityKind, UUID, list[UUID]]] = []
        for row_number, row in enumerate(selected, 2):
            entity_kind = row["entity_kind"]
            canonical_id = self._uuid(row["canonical_id"], row_number)
            if entity_kind == "company":
                company_group = current_companies.get(("company", row["group_id"]))
                if (
                    company_group is None
                    or company_group["fingerprint"] != row["fingerprint"]
                ):
                    raise CommandError(
                        f"Row {row_number}: group is stale or no longer exists"
                    )
                member_ids = [
                    UUID(member["company_id"]) for member in company_group["members"]
                ]
                decision_kind: EntityKind = "company"
            elif entity_kind == "person":
                person_group = current_people.get(("person", row["group_id"]))
                if (
                    person_group is None
                    or person_group["fingerprint"] != row["fingerprint"]
                ):
                    raise CommandError(
                        f"Row {row_number}: group is stale or no longer exists"
                    )
                member_ids = [
                    UUID(member["person_id"]) for member in person_group["members"]
                ]
                decision_kind = "person"
            else:
                raise CommandError(f"Row {row_number}: invalid entity_kind")
            if canonical_id not in member_ids:
                raise CommandError(f"Row {row_number}: canonical_id is not a member")
            decisions.append((decision_kind, canonical_id, member_ids))

        staff = Staff.get_automation_user()
        merge_count = 0
        with transaction.atomic():
            for entity_kind, canonical_id, member_ids in decisions:
                for source_id in member_ids:
                    if source_id == canonical_id:
                        continue
                    if entity_kind == "company":
                        merge_companies(source_id, canonical_id, staff)
                    else:
                        merge_people(source_id, canonical_id, staff)
                    merge_count += 1
        self.stdout.write(self.style.SUCCESS(f"Applied {merge_count} identity merges"))

    @staticmethod
    def _uuid(raw_value: str, row_number: int) -> UUID:
        try:
            return UUID(raw_value)
        except ValueError as exc:
            raise CommandError(f"Row {row_number}: invalid canonical_id") from exc
