from apscheduler.triggers.cron import CronTrigger
from telegram.ext import Application

from app.config import Settings
from app.database import Database
from app.repositories.user_repository import UserRepository


async def send_morning_checkin(application: Application) -> None:
    await _broadcast(application, "Доброе утро. Используйте /plan, чтобы составить план на день.")


async def send_midday_checkin(application: Application) -> None:
    await _broadcast(application, "Проверьте прогресс: /today покажет план, /done отметит выполненное.")


async def send_evening_review(application: Application) -> None:
    await _broadcast(application, "Вечерний итог: используйте /status, чтобы посмотреть прогресс за день.")


def schedule_jobs(application: Application, settings: Settings) -> None:
    scheduler = application.job_queue.scheduler
    scheduler.add_job(
        send_morning_checkin,
        CronTrigger.from_crontab(settings.morning_checkin_cron, timezone=settings.default_timezone),
        args=[application],
        id="morning_checkin",
        replace_existing=True,
    )
    scheduler.add_job(
        send_midday_checkin,
        CronTrigger.from_crontab(settings.midday_checkin_cron, timezone=settings.default_timezone),
        args=[application],
        id="midday_checkin",
        replace_existing=True,
    )
    scheduler.add_job(
        send_evening_review,
        CronTrigger.from_crontab(settings.evening_review_cron, timezone=settings.default_timezone),
        args=[application],
        id="evening_review",
        replace_existing=True,
    )


async def _broadcast(application: Application, text: str) -> None:
    db: Database = application.bot_data["db"]
    with db.connection() as conn:
        users = UserRepository(conn).list_users()

    for user in users:
        await application.bot.send_message(chat_id=user.telegram_id, text=text)
