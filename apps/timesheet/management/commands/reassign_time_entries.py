"""
Reassign time entries from one staff member to another.

Common use case: timesheet entries accidentally logged under the wrong person.
Updates meta.staff_id, unit_cost (to match new staff's wage rate), and desc.

Usage:
    # Dry run — show what would change
    python manage.py reassign_time_entries --from-staff Aaron --to-staff Christian --date 2026-03-24 --dry-run

    # Apply
    python manage.py reassign_time_entries --from-staff Aaron --to-staff Christian --date 2026-03-24

    # Reassign specific entries by ID
    python manage.py reassign_time_entries --to-staff Christian --ids 7cca4c30,15956dac --dry-run
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Staff
from apps.job.models import CostLine


class Command(BaseCommand):
    help = "Reassign time entries from one staff member to another"

    def add_arguments(self, parser):
        parser.add_argument(
            "--from-staff",
            type=str,
            help="First name (or start of) of staff to reassign FROM",
        )
        parser.add_argument(
            "--to-staff",
            type=str,
            required=True,
            help="First name (or start of) of staff to reassign TO",
        )
        parser.add_argument(
            "--date",
            type=str,
            help="Date of entries to reassign (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--ids",
            type=str,
            help="Comma-separated CostLine IDs (or prefixes) to reassign",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing to DB",
        )

    def handle(self, *args, **options):
        if not options["ids"] and not (options["from_staff"] and options["date"]):
            raise CommandError("Specify either --ids or both --from-staff and --date")

        to_staff = self._resolve_staff(options["to_staff"])

        if options["ids"]:
            entries = self._find_by_ids(options["ids"])
        else:
            from_staff = self._resolve_staff(options["from_staff"])
            entry_date = self._parse_date(options["date"])
            entries = self._find_by_staff_date(from_staff, entry_date)

        if not entries:
            raise CommandError("No matching time entries found")

        self.stdout.write(
            f"Found {len(entries)} entries to reassign to {to_staff.get_display_name()}:"
        )
        self.stdout.write(f"  New unit_cost: ${to_staff.base_wage_rate}")
        self.stdout.write("")

        if not to_staff.base_wage_rate:
            raise CommandError(
                f"Staff '{to_staff.get_display_name()}' has no base_wage_rate set"
            )

        for entry in entries:
            entry.meta.get("staff_id", "?")
            old_cost = entry.unit_cost
            new_cost = to_staff.base_wage_rate
            cost_change = (new_cost - old_cost) * entry.quantity

            self.stdout.write(
                f"  {entry.id} | {entry.accounting_date} | "
                f"{entry.quantity}h | {entry.cost_set.job.name} | "
                f"desc={entry.desc}"
            )
            self.stdout.write(
                f"    unit_cost: ${old_cost} -> ${new_cost} "
                f"(total change: {'+' if cost_change >= 0 else ''}${cost_change:.2f})"
            )

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("\nDRY RUN — no changes made."))
            return

        with transaction.atomic():
            for entry in entries:
                entry.meta["staff_id"] = str(to_staff.id)
                entry.unit_cost = to_staff.base_wage_rate
                entry.save(update_fields=["meta", "unit_cost", "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Reassigned {len(entries)} entries to "
                f"{to_staff.get_display_name()}."
            )
        )

    def _resolve_staff(self, name: str) -> Staff:
        parts = name.strip().split()
        if len(parts) >= 2:
            # Try first + last name match
            matches = Staff.objects.filter(
                first_name__istartswith=parts[0],
                last_name__istartswith=parts[-1],
            )
        else:
            matches = Staff.objects.filter(first_name__istartswith=name)
        if matches.count() == 0:
            raise CommandError(f"No staff found matching '{name}'")
        if matches.count() > 1:
            names = [(s.first_name, s.last_name) for s in matches]
            raise CommandError(
                f"Multiple staff match '{name}': {names}. Be more specific."
            )
        return matches.get()

    def _find_by_ids(self, ids_str: str) -> list[CostLine]:
        entries = []
        for raw_id in ids_str.split(","):
            raw_id = raw_id.strip()
            if not raw_id:
                continue
            matches = CostLine.objects.filter(kind="time", id__startswith=raw_id)
            if matches.count() == 0:
                raise CommandError(f"No CostLine found with ID starting '{raw_id}'")
            if matches.count() > 1:
                raise CommandError(
                    f"Multiple CostLines match ID prefix '{raw_id}': "
                    f"{[str(m.id) for m in matches]}"
                )
            entries.append(matches.get())
        return entries

    def _find_by_staff_date(self, staff: Staff, entry_date: date) -> list[CostLine]:
        return list(
            CostLine.objects.filter(
                kind="time",
                cost_set__kind="actual",
                accounting_date=entry_date,
                meta__staff_id=str(staff.id),
            ).order_by("created_at")
        )

    @staticmethod
    def _parse_date(value: str) -> date:
        parts = value.strip().split("-")
        if len(parts) != 3:
            raise CommandError(f"Invalid date format: {value}. Use YYYY-MM-DD.")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
