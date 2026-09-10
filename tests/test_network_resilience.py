import asyncio
from types import SimpleNamespace

from telegram.error import NetworkError


def test_network_error_handler_does_not_reply(caplog) -> None:
    from app.bot.error_handler import handle_unexpected_error

    context = SimpleNamespace(error=NetworkError("DNS unavailable"))

    asyncio.run(handle_unexpected_error(object(), context))

    assert "Temporary Telegram network error: DNS unavailable" in caplog.text
    assert "Traceback" not in caplog.text


def test_scheduled_today_broadcast_survives_network_error(monkeypatch, caplog) -> None:
    from app.scheduler.jobs import _broadcast_today

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    class Database:
        def connection(self):
            return Connection()

    class UserRepository:
        def __init__(self, conn):
            pass

        def list_users(self):
            return [SimpleNamespace(telegram_id=42)]

    class Bot:
        async def send_message(self, **kwargs):
            raise NetworkError("connection lost")

    class PlanningService:
        def get_today_plan(self, telegram_id):
            return None

    monkeypatch.setattr("app.scheduler.jobs.UserRepository", UserRepository)
    application = SimpleNamespace(
        bot_data={
            "db": Database(),
            "planning_service": PlanningService(),
        },
        bot=Bot(),
    )

    asyncio.run(_broadcast_today(application))

    assert "Could not send scheduled message to Telegram chat 42" in caplog.text


def test_scheduled_job_sends_the_same_plan_as_today(monkeypatch) -> None:
    from datetime import UTC, date, datetime

    from app.bot.formatters import format_plan
    from app.models.daily_plan import DailyPlan
    from app.models.task import Task, TaskStatus
    from app.scheduler.jobs import _broadcast_today
    from app.services.planning_service import PlanWithTasks

    now = datetime(2026, 7, 26, 12, tzinfo=UTC)
    plan = PlanWithTasks(
        plan=DailyPlan(
            id=1,
            user_id=1,
            plan_date=date(2026, 7, 26),
            day_type="Смешанный",
            available_minutes=480,
            created_at=now,
        ),
        tasks=[
            Task(
                id=1,
                daily_plan_id=1,
                text="Проверить cron",
                status=TaskStatus.planned,
                first_planned_date=date(2026, 7, 26),
                created_at=now,
                updated_at=now,
            )
        ],
    )

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    class Database:
        def connection(self):
            return Connection()

    class UserRepository:
        def __init__(self, conn):
            pass

        def list_users(self):
            return [SimpleNamespace(telegram_id=42)]

    class PlanningService:
        def get_today_plan(self, telegram_id):
            assert telegram_id == 42
            return plan

    class Bot:
        def __init__(self):
            self.message = None

        async def send_message(self, **kwargs):
            self.message = kwargs

    monkeypatch.setattr("app.scheduler.jobs.UserRepository", UserRepository)
    bot = Bot()
    application = SimpleNamespace(
        bot_data={
            "db": Database(),
            "planning_service": PlanningService(),
        },
        bot=bot,
    )

    asyncio.run(_broadcast_today(application))

    assert bot.message == {"chat_id": 42, "text": format_plan(plan)}


def test_schedule_jobs_allows_late_run() -> None:
    from app.scheduler.jobs import schedule_jobs

    class Scheduler:
        def __init__(self):
            self.calls = []

        def add_job(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    scheduler = Scheduler()
    application = SimpleNamespace(job_queue=SimpleNamespace(scheduler=scheduler))
    settings = SimpleNamespace(
        morning_checkin_cron="0 9 * * *",
        midday_checkin_cron="0 13 * * *",
        evening_review_cron="0 20 * * *",
        weekly_stats_cron="0 21 * * 0",
        default_timezone="Europe/Moscow",
        scheduler_misfire_grace_seconds=7_200,
    )

    schedule_jobs(application, settings)

    assert len(scheduler.calls) == 4
    for _, kwargs in scheduler.calls:
        assert kwargs["coalesce"] is True
        assert kwargs["max_instances"] == 1
        assert kwargs["misfire_grace_time"] == 7_200
