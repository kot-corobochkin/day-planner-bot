from datetime import date

from app.bot.handlers import _is_week_end


def test_weekly_ai_report_is_allowed_only_on_sunday() -> None:
    assert _is_week_end(date(2026, 9, 13)) is True
    assert _is_week_end(date(2026, 9, 10)) is False
