from datetime import date, datetime, time
from zoneinfo import ZoneInfo


DAY_CAPACITY_MINUTES = {
    "Рабочий день": 4 * 60,
    "Выходной": 14 * 60,
    "Больничный": 8 * 60,
    "Смешанный": 8 * 60,
    "Workday": 4 * 60,
    "Weekend": 14 * 60,
    "Sick day": 8 * 60,
    "Mixed": 8 * 60,
}


def default_available_minutes(day_type: str) -> int:
    return DAY_CAPACITY_MINUTES.get(day_type, 8 * 60)


def available_minutes_for_date(
    base_minutes: int,
    plan_date: date,
    timezone: str,
    *,
    now: datetime | None = None,
) -> int:
    """Cap today's capacity by the remaining 08:00-22:00 local time window."""
    zone = ZoneInfo(timezone)
    local_now = (now or datetime.now(zone)).astimezone(zone)
    if plan_date > local_now.date():
        return base_minutes
    if plan_date < local_now.date():
        return 0

    day_start = datetime.combine(plan_date, time(hour=8), tzinfo=zone)
    day_end = datetime.combine(plan_date, time(hour=22), tzinfo=zone)
    if local_now <= day_start:
        return base_minutes
    if local_now >= day_end:
        return 0
    minutes_until_end = int((day_end - local_now).total_seconds() // 60)
    return min(base_minutes, minutes_until_end)
