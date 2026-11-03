"""Reassign time entries from one staff member to another.

Common use case: timesheet entries accidentally logged under the wrong person.
Each entry is deleted from the one and entered for the other through the entry
writer, which prices it at the new person's wage; an approved entry is
approved again. A dry run makes the moves and rolls them back, so the costs it
shows are the ones a real run writes.

Usage:
    # Dry run — show what would change
    python manage.py reassign_time_entries --from-staff Alex --to-staff Sam \
        --date 2026-03-24 --actor office@example.com --dry-run

    # Apply
    python manage.py reassign_time_entries --from-staff Alex --to-staff Sam \
        --date 2026-03-24 --actor office@example.com

    # Reassign specific entries by ID
    python manage.py reassign_time_entries --to-staff Sam --ids 7cca4c30,15956dac \
        --actor office@example.com --dry-run
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.accounts.models import Staff
from apps.job.models.costing import CostLine
from apps.job.services.time_entry_rates import rate_from_meta
from apps.timesheet.services.workshop_timesheet_service import (
    WorkshopEntryCreateData,
    create_entry,
    delete_entry,
    is_general_work_fill,
    timed_span,
)

from ._repair_shared import (
    add_actor_argument,
    approve_written,
    day_line_ids,
    parse_date,
    resolve_actor,
    written_entries,
)

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
    """Move time entries between staff members, priced at the new person's wage."""

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
        add_actor_argument(parser)

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

        actor = resolve_actor(options)
        self.stdout.write(
            f"Found {len(entries)} entries to reassign to {to_staff.get_display_name()}:"
        )
        with transaction.atomic():
            for entry in entries:
                self._reassign(actor, entry, to_staff)
            if dry_run:
                transaction.set_rollback(True)

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDRY RUN — no changes made."))
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Reassigned {len(entries)} entries to {to_staff.get_display_name()}."
            )
        )

    def _reassign(self, actor: Staff, entry: CostLine, to_staff: Staff) -> None:
        """Delete the entry from its owner and enter it for ``to_staff``, then report it."""
        if entry.staff is None:
            raise CommandError(f"Time line {entry.id} has no staff member")
        if is_general_work_fill(entry):
            raise CommandError(
                f"{entry.id} is General work filling {entry.staff.get_display_name()}'s day, "
                "not an entry: reassign the entries around it"
            )
        from_staff, day = entry.staff, entry.accounting_date
        old_cost = entry.total_cost
        data = _carried(entry)
        untouched_from = day_line_ids(from_staff, day) - {entry.id}
        untouched_to = day_line_ids(to_staff, day)

        delete_entry(actor, entry.id)
        create_entry(actor, to_staff, data)
        written = written_entries(to_staff, day, untouched_to)
        if entry.approved:
            approve_written(actor, from_staff, day, untouched_from)
            approve_written(actor, to_staff, day, untouched_to)

        new_cost = sum(line.total_cost for line in written)
        cost_change = new_cost - old_cost
        self.stdout.write(
            f"  {entry.id} | {day} | {entry.quantity}h | {entry.cost_set.job.name} | "
            f"desc={entry.desc}"
        )
        self.stdout.write(
            f"    cost: ${old_cost} -> ${new_cost} "
            f"(total change: {'+' if cost_change >= 0 else ''}${cost_change:.2f}) | "
            f"new ID: {', '.join(str(line.id) for line in written)}"
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


def _carried(entry: CostLine) -> WorkshopEntryCreateData:
    """Return the entry as the writer takes it: everything but whose it is."""
    wage = rate_from_meta(entry.meta, "wage_rate_multiplier")
    if wage is None:
        raise CommandError(f"Time line {entry.id} has no wage rate multiplier")
    is_billable = entry.meta["is_billable"]
    if not isinstance(is_billable, bool):
        raise CommandError(f"Time line {entry.id} has no billable flag")
    data: WorkshopEntryCreateData = {
        "job_id": entry.cost_set.job_id,
        "accounting_date": entry.accounting_date,
        "hours": entry.quantity,
        "description": entry.desc,
        "is_billable": is_billable,
        "wage_rate_multiplier": wage,
    }
    bill = rate_from_meta(entry.meta, "bill_rate_multiplier")
    if bill is not None:
        data["bill_rate_multiplier"] = bill
    span = timed_span(entry)
    if span is not None:
        data["start_time"], data["end_time"] = span
    if entry.labour_subtype_id is not None:
        data["labour_subtype_id"] = entry.labour_subtype_id
    return data
