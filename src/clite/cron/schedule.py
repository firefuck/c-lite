"""Schedules: parsing what the user wrote and computing the next run time.

Three kinds:

``once``      ``30m``, ``2h``, ``1d`` (that long from now) or an ISO timestamp
``interval``  ``every 30m``, ``every 2h``, ``every 1d``
``cron``      a five-field expression: minute hour day-of-month month day-of-week

The cron parser is deliberately small and standard: ``*``, lists (``1,15``), ranges
(``1-5``), steps (``*/15``, ``10-40/10``) and month/weekday names. When both day-of-month and
day-of-week are restricted, a day matching either one runs, as in classic cron.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

KIND_ONCE, KIND_INTERVAL, KIND_CRON = "once", "interval", "cron"
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_DURATION = re.compile(r"^(\d+)\s*(s|sec|secs|m|min|mins|h|hr|hrs|hour|hours|d|day|days|w|week|weeks)$", re.IGNORECASE)
_MONTHS = {name: index for index, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
_WEEKDAYS = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
MIN_INTERVAL_SECONDS = 60
_SEARCH_LIMIT_DAYS = 366 * 5


class ScheduleError(ValueError):
    """The schedule text could not be understood."""


@dataclass
class Schedule:
    kind: str
    display: str
    run_at: float | None = None  # once
    interval_seconds: int | None = None  # interval
    expr: str | None = None  # cron

    def to_dict(self) -> dict:
        return {"kind": self.kind, "display": self.display, "run_at": self.run_at,
                "interval_seconds": self.interval_seconds, "expr": self.expr}

    @classmethod
    def from_dict(cls, data: dict) -> Schedule:
        return cls(kind=data["kind"], display=data.get("display", ""), run_at=data.get("run_at"),
                   interval_seconds=data.get("interval_seconds"), expr=data.get("expr"))


def get_timezone(name: str = "") -> tzinfo:
    """The zone schedules are evaluated in: the configured IANA name, else the system's."""
    if name:
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:
            raise ScheduleError(f"unknown timezone {name!r}") from None
    return datetime.now().astimezone().tzinfo  # type: ignore[return-value]


def parse_duration(text: str) -> int:
    match = _DURATION.match(text.strip())
    if not match:
        raise ScheduleError(f"cannot read duration {text!r}; use forms like 30m, 2h, 1d")
    return int(match.group(1)) * _UNITS[match.group(2)[0].lower()]


# ── cron expressions ─────────────────────────────────────────────────────────────────────


def _parse_field(field: str, low: int, high: int, names: dict[str, int] | None = None) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip().lower()
        if not part:
            raise ScheduleError("empty value in cron field")
        base, _, step_text = part.partition("/")
        try:
            step = int(step_text) if step_text else 1
        except ValueError:
            raise ScheduleError(f"invalid step in cron field {part!r}") from None
        if step < 1:
            raise ScheduleError(f"invalid step in cron field {part!r}")

        def number(token: str) -> int:
            if names and token in names:
                return names[token]
            if not token.isdigit():
                raise ScheduleError(f"invalid value {token!r} in cron field")
            return int(token)

        if base == "*":
            start, end = low, high
        elif "-" in base:
            left, right = base.split("-", 1)
            start, end = number(left), number(right)
        else:
            start = number(base)
            end = high if step_text else start
        if start < low or end > high or start > end:
            raise ScheduleError(f"cron value out of range in {part!r} (allowed {low}-{high})")
        values.update(range(start, end + 1, step))
    return values


@dataclass
class CronExpression:
    minutes: set[int]
    hours: set[int]
    days: set[int]
    months: set[int]
    weekdays: set[int]  # 0 = Sunday
    day_restricted: bool
    weekday_restricted: bool

    @classmethod
    def parse(cls, expression: str) -> CronExpression:
        fields = expression.split()
        if len(fields) != 5:
            raise ScheduleError("a cron expression has five fields: minute hour day-of-month month day-of-week")
        return cls(
            minutes=_parse_field(fields[0], 0, 59),
            hours=_parse_field(fields[1], 0, 23),
            days=_parse_field(fields[2], 1, 31),
            months=_parse_field(fields[3], 1, 12, _MONTHS),
            # 7 is accepted as another spelling of Sunday.
            weekdays={0 if value == 7 else value for value in _parse_field(fields[4], 0, 7, _WEEKDAYS)},
            day_restricted=fields[2] != "*",
            weekday_restricted=fields[4] != "*",
        )

    def _day_matches(self, moment: datetime) -> bool:
        in_days = moment.day in self.days
        in_weekdays = (moment.weekday() + 1) % 7 in self.weekdays
        if self.day_restricted and self.weekday_restricted:
            return in_days or in_weekdays
        return in_days and in_weekdays

    def next_after(self, moment: datetime) -> datetime:
        """The first matching minute strictly after ``moment``."""
        candidate = moment.replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = candidate + timedelta(days=_SEARCH_LIMIT_DAYS)
        while candidate < limit:
            if candidate.month not in self.months:
                year, month = (candidate.year + 1, 1) if candidate.month == 12 else (candidate.year, candidate.month + 1)
                candidate = candidate.replace(year=year, month=month, day=1, hour=0, minute=0)
            elif not self._day_matches(candidate):
                candidate = (candidate + timedelta(days=1)).replace(hour=0, minute=0)
            elif candidate.hour not in self.hours:
                candidate = (candidate + timedelta(hours=1)).replace(minute=0)
            elif candidate.minute not in self.minutes:
                candidate += timedelta(minutes=1)
            else:
                return candidate
        raise ScheduleError("this cron expression never matches a real date")


# ── parsing and next-run ─────────────────────────────────────────────────────────────────


def parse_schedule(text: str, *, now: float | None = None, timezone: str = "") -> Schedule:
    """Turn the user's schedule text into a :class:`Schedule`."""
    import time

    raw = " ".join(str(text or "").split())
    if not raw:
        raise ScheduleError("a schedule is required, for example '30m', 'every 2h' or '0 9 * * 1-5'")
    current = time.time() if now is None else now
    lowered = raw.lower()

    if lowered.startswith("every "):
        seconds = parse_duration(lowered[6:])
        if seconds < MIN_INTERVAL_SECONDS:
            raise ScheduleError(f"the shortest interval is {MIN_INTERVAL_SECONDS} seconds")
        return Schedule(KIND_INTERVAL, f"every {lowered[6:].strip()}", interval_seconds=seconds)

    if _DURATION.match(lowered):
        seconds = parse_duration(lowered)
        return Schedule(KIND_ONCE, f"once in {lowered}", run_at=current + seconds)

    if len(raw.split()) == 5 and not re.match(r"^\d{4}-\d{2}-\d{2}", raw):
        CronExpression.parse(raw).next_after(datetime.fromtimestamp(current, get_timezone(timezone)))  # validates
        return Schedule(KIND_CRON, raw, expr=raw)

    try:
        moment = datetime.fromisoformat(raw.replace(" ", "T", 1))
    except ValueError:
        raise ScheduleError(
            f"cannot read schedule {raw!r}. Use a delay (30m), an interval (every 2h), a cron expression "
            "(0 9 * * *) or a timestamp (2026-01-31T09:00)."
        ) from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=get_timezone(timezone))
    if moment.timestamp() <= current:
        raise ScheduleError(f"{raw} is in the past")
    return Schedule(KIND_ONCE, f"once at {moment.strftime('%Y-%m-%d %H:%M')}", run_at=moment.timestamp())


def next_run(schedule: Schedule, after: float, *, timezone: str = "") -> float | None:
    """When ``schedule`` next fires after ``after``; ``None`` when it never will."""
    if schedule.kind == KIND_ONCE:
        return schedule.run_at if schedule.run_at is not None and schedule.run_at > after else None
    if schedule.kind == KIND_INTERVAL:
        return after + int(schedule.interval_seconds or 0)
    if schedule.kind == KIND_CRON:
        moment = datetime.fromtimestamp(after, get_timezone(timezone))
        return CronExpression.parse(schedule.expr or "").next_after(moment).timestamp()
    raise ScheduleError(f"unknown schedule kind {schedule.kind!r}")
