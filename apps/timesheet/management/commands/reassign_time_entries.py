"""Reassign time entries from one staff member to another.

Common use case: timesheet entries accidentally logged under the wrong person.
Updates staff, unit_cost (to match the new staff member's wage rate), and the
entry metadata.

Usage:
    # Dry run — show what would change
    python manage.py reassign_time_entries --from-staff Alex --to-staff Sam \
        --date 2026-03-24 --dry-run

    # Apply
    python manage.py reassign_time_entries --from-staff Alex --to-staff Sam \
        --date 2026-03-24

    # Reassign specific entries by ID
    python manage.py reassign_time_entries --to-staff Sam --ids 7cca4c30,15956dac --dry-run
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.accounts.models import Staff
from apps.job.models.costing import CostLine

from ._repair_shared import parse_date

# A two-word input is matched as "first last"; one word matches first name only.
FIRST_AND_LAST = 2


def _required_str_option(options: dict[str, object], key: str, flag: str) -> str:
    """Narrow a required argparse string option."""
    value = options.get(key)
    if not isinstance(value, str):
        raise TypeError(f"The {flag} option must be a string")
    return value


def _optional_str_option(options: dict[str, object], key: str, flag: str) -> str | None:
    """Narrow an optional argparse string option."""
    value = options.get(key)
    if value is not None and not isinstance(value, str):
        raise TypeError(f"The {flag} option must be a string")
    return value


class Command(BaseCommand):
    """Move time CostLines between staff members, repricing to the new wage rate."""

    help = "Reassign time entries from one staff member to another"

    def add_arguments(self, parser: CommandParser) -> None:
        """Register the selection options (staff+date, or explicit ids) and dry-run."""
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

    def handle(self, *_args: object, **options: object) -> None:
        """Select the entries, report the repricing, then reassign atomically."""
        to_staff_name = _required_str_option(options, "to_staff", "to-staff")
        from_staff_name = _optional_str_option(options, "from_staff", "from-staff")
        date_text = _optional_str_option(options, "date", "date")
        ids_text = _optional_str_option(options, "ids", "ids")
        dry_run = options.get("dry_run")
        if not isinstance(dry_run, bool):
            raise TypeError("The dry-run option must be a boolean")

        to_staff = self._resolve_staff(to_staff_name)
        if not to_staff.base_wage_rate:
            raise CommandError(f"Staff '{to_staff.get_display_name()}' has no base_wage_rate set")

        if ids_text:
            entries = self._find_by_ids(ids_text)
        elif from_staff_name and date_text:
            from_staff = self._resolve_staff(from_staff_name)
            entries = self._find_by_staff_date(from_staff, parse_date(date_text))
        else:
            raise CommandError("Specify either --ids or both --from-staff and --date")

        if not entries:
            raise CommandError("No matching time entries found")

        self._report_repricing(entries, to_staff)

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDRY RUN — no changes made."))
            return

        with transaction.atomic():
            for entry in entries:
                meta = dict(entry.meta or {})
                meta["staff_id"] = str(to_staff.id)
                entry.meta = meta
                entry.staff = to_staff
                entry.unit_cost = to_staff.base_wage_rate
                entry.save(update_fields=["meta", "staff", "unit_cost", "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Reassigned {len(entries)} entries to {to_staff.get_display_name()}."
            )
        )

    def _report_repricing(self, entries: list[CostLine], to_staff: Staff) -> None:
        """Show each entry with its old and new cost before anything is written."""
        self.stdout.write(
            f"Found {len(entries)} entries to reassign to {to_staff.get_display_name()}:"
        )
        self.stdout.write(f"  New unit_cost: ${to_staff.base_wage_rate}")
        self.stdout.write("")
        for entry in entries:
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

    @staticmethod
    def _resolve_staff(name: str) -> Staff:
        """Resolve a (possibly partial) name to exactly one staff member."""
        parts = name.strip().split()
        if len(parts) >= FIRST_AND_LAST:
            matches = Staff.objects.filter(
                first_name__istartswith=parts[0],
                last_name__istartswith=parts[-1],
            )
        else:
            matches = Staff.objects.filter(first_name__istartswith=name)
        found = list(matches)
        if len(found) == 0:
            raise CommandError(f"No staff found matching '{name}'")
        if len(found) > 1:
            names = [(s.first_name, s.last_name) for s in found]
            raise CommandError(f"Multiple staff match '{name}': {names}. Be more specific.")
        return found[0]

    @staticmethod
    def _find_by_ids(ids_str: str) -> list[CostLine]:
        """Resolve comma-separated id prefixes, each to exactly one time line."""
        entries: list[CostLine] = []
        for raw_id in ids_str.split(","):
            candidate = raw_id.strip()
            if not candidate:
                continue
            matches = list(
                CostLine.objects.filter(kind="time", id__startswith=candidate).select_related(
                    "cost_set__job"
                )
            )
            if len(matches) == 0:
                raise CommandError(f"No CostLine found with ID starting '{candidate}'")
            if len(matches) > 1:
                raise CommandError(
                    f"Multiple CostLines match ID prefix '{candidate}': "
                    f"{[str(m.id) for m in matches]}"
                )
            entries.append(matches[0])
        return entries

    @staticmethod
    def _find_by_staff_date(staff: Staff, entry_date: date) -> list[CostLine]:
        """Return the staff member's actual time lines on the given date."""
        return list(
            CostLine.objects.filter(
                kind="time",
                cost_set__kind="actual",
                accounting_date=entry_date,
                staff=staff,
            )
            .select_related("cost_set__job")
            .order_by("entry_seq")
        )
