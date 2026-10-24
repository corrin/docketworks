"""An entry's times are when he worked: lines whose times disagree with their hours are re-laid.

Until 2026-10-24 an entry's hours were the truth and its times the picture,
and the picture stepped over breaks: four hours from 07:00 were one entry,
07:00-11:15, with a break inside. Now an entry's start and finish are when he
worked, and work that meets a break is split around it (owner, 2026-10-24).
The old rule says which half of a disagreeing line to believe, so the hours
stand: each timed actual line whose span is not its hours is laid out again
from its start, around that day's breaks, one line per stretch. Break lines
go first, each as one stretch, since the others are laid around them; a day
nobody clocked steps around the company's standard breaks, as it showed
them. Hours that would run past midnight keep no times, as they always could.

The only place the old shape is known (ADR 0059). Not reversible: a split
line cannot be told from two entries made apart.
"""

import uuid
from datetime import date, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

TOLERANCE = Decimal("0.01")
LAST_MINUTE = 24 * 60 - 1


def _minutes(moment: time) -> int:
    return moment.hour * 60 + moment.minute


def _clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}:00"


def _times(meta: object) -> tuple[int, int] | None:
    if not isinstance(meta, dict):
        return None
    start, end = meta.get("start_time"), meta.get("end_time")
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    return _minutes(time.fromisoformat(start)), _minutes(time.fromisoformat(end))


def _merged(windows: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(windows):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _lay_out(
    start: int, minutes: int, breaks: list[tuple[int, int]]
) -> list[tuple[int, int]] | None:
    """The stretches ``minutes`` of work from ``start`` fill around the breaks; None past midnight."""
    cursor, remaining, stretches = start, minutes, []
    for break_start, break_end in _merged(breaks):
        if break_end <= cursor:
            continue
        if break_start <= cursor:
            cursor = break_end
            continue
        if cursor + remaining <= break_start:
            break
        stretches.append((cursor, break_start))
        remaining -= break_start - cursor
        cursor = break_end
    stretches.append((cursor, cursor + remaining))
    return None if stretches[-1][1] > LAST_MINUTE else stretches


def _standard_breaks(
    day: date, days: list[tuple[time, time]], breaks: list[tuple[time, int]]
) -> list[tuple[int, int]]:
    """The company's standard breaks inside its standard day, as a day nobody clocked showed them."""
    if day.weekday() >= len(days):
        return []
    first, last = (_minutes(each) for each in days[day.weekday()])
    return [
        (_minutes(start), _minutes(start) + minutes)
        for start, minutes in breaks
        if minutes and _minutes(start) >= first and _minutes(start) + minutes <= last
    ]


def _disagrees(meta: object, hours: Decimal) -> bool:
    times = _times(meta)
    if times is None:
        return False
    return abs(Decimal(times[1] - times[0]) / Decimal(60) - hours) > TOLERANCE


def _shares(stretches: list[tuple[int, int]], hours: Decimal) -> list[Decimal]:
    """Each stretch's own minutes, the last taking what rounding left, so they add up to ``hours``."""
    shares = [
        (Decimal(end - begins) / Decimal(60)).quantize(Decimal("0.01"))
        for begins, end in stretches[:-1]
    ]
    return [*shares, hours - sum(shares, Decimal(0))]


def lay_out_again(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    alias = schema_editor.connection.alias
    CostLine = apps.get_model("job", "CostLine")
    company = apps.get_model("core", "CompanyDefaults").objects.using(alias).first()
    if company is None:
        return
    days = [
        (company.mon_start, company.mon_end),
        (company.tue_start, company.tue_end),
        (company.wed_start, company.wed_end),
        (company.thu_start, company.thu_end),
        (company.fri_start, company.fri_end),
    ]
    standard = [
        (company.morning_break_start, company.morning_break_minutes),
        (company.lunch_start, company.lunch_minutes),
        (company.afternoon_break_start, company.afternoon_break_minutes),
    ]
    clocked = set(
        apps.get_model("timesheet", "AttendanceDay")
        .objects.using(alias)
        .values_list("staff_id", "date")
    )
    lines = CostLine.objects.using(alias)
    timed = lines.filter(kind="time", cost_set__kind="actual").select_related("cost_set")
    wrong = [line for line in timed if _disagrees(line.meta, line.quantity)]
    # Breaks first: they are what the other entries are laid around.
    wrong.sort(key=lambda line: line.cost_set.job_id != company.break_job_id)
    copied = [
        field.attname
        for field in CostLine._meta.concrete_fields
        if field.name not in {"id", "entry_seq", "quantity", "meta", "created_at", "updated_at"}
    ]
    for line in wrong:
        times = _times(line.meta)
        if times is None:
            raise ValueError(f"Line {line.id} lost its times while being re-laid")
        breaks: list[tuple[int, int]] = []
        if line.cost_set.job_id != company.break_job_id:
            day_breaks = lines.filter(
                kind="time",
                cost_set__kind="actual",
                cost_set__job_id=company.break_job_id,
                staff_id=line.staff_id,
                accounting_date=line.accounting_date,
            )
            breaks = [each for other in day_breaks if (each := _times(other.meta)) is not None]
            if (line.staff_id, line.accounting_date) not in clocked:
                breaks += _standard_breaks(line.accounting_date, days, standard)
        minutes = int((line.quantity * 60).to_integral_value(ROUND_HALF_UP))
        stretches = None if minutes <= 0 else _lay_out(times[0], minutes, breaks)
        meta = dict(line.meta)
        if stretches is None:
            meta["start_time"] = meta["end_time"] = None
            line.meta = meta
            line.save(update_fields=["meta"])
            continue
        shares = _shares(stretches, line.quantity)
        meta["start_time"], meta["end_time"] = _clock(stretches[0][0]), _clock(stretches[0][1])
        line.meta, line.quantity = meta, shares[0]
        line.save(update_fields=["meta", "quantity"])
        last_seq = max(
            lines.filter(
                staff_id=line.staff_id,
                accounting_date=line.accounting_date,
                entry_seq__isnull=False,
            ).values_list("entry_seq", flat=True)
        )
        for step, ((begins, end), hours) in enumerate(
            zip(stretches[1:], shares[1:], strict=True), start=1
        ):
            last_seq += 1
            piece = CostLine(
                id=uuid.uuid4(),
                quantity=hours,
                meta={**meta, "start_time": _clock(begins), "end_time": _clock(end)},
                entry_seq=last_seq,
                **{name: getattr(line, name) for name in copied},
            )
            piece.save(using=alias)
            # Just after the line it came from, so the day lists it next.
            lines.filter(pk=piece.pk).update(
                created_at=line.created_at + timedelta(microseconds=step)
            )


class Migration(migrations.Migration):
    dependencies = [
        ("timesheet", "0011_events_say_trusted"),
        ("job", "0019_trim_undo_fields"),
        ("core", "0017_remove_kpi_daily_gp_green"),
    ]

    operations = [
        migrations.RunPython(lay_out_again, migrations.RunPython.noop),
    ]
