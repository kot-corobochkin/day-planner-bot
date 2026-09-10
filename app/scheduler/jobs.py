import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from telegram.error import Forbidden, NetworkError
from telegram.ext import Application
from psycopg import Error as PsycopgError

from app.bot.formatters import format_plan
from app.bot.statistics import format_period_stats, format_weekly_achievements
from app.config import Settings
from app.database import Database
from app.repositories.user_repository import UserRepository
from app.services.planning_service import PlanningService
from app.services.statistics_service import StatisticsService
from app.services.weekly_achievements import WeeklyAchievementService
from app.services.llm_provider import LLMProviderError

logger = logging.getLogger(__name__)


async def send_morning_checkin(application: Application) -> None:
    await _broadcast_today(application)


async def send_midday_checkin(application: Application) -> None:
    await _broadcast_today(application)


async def send_evening_review(application: Application) -> None:
    await _broadcast_today(application)


async def send_weekly_stats(application: Application) -> None:
    db: Database = application.bot_data["db"]
    statistics_service: StatisticsService = application.bot_data["statistics_service"]
    achievement_service: WeeklyAchievementService = application.bot_data[
        "weekly_achievement_service"
    ]
    with db.connection() as conn:
        users = UserRepository(conn).list_users()

    for user in users:
        try:
            today = datetime.now(ZoneInfo(user.timezone)).date()
            start_date = today - timedelta(days=today.weekday())
            stats = statistics_service.get_period_stats(
                user.telegram_id,
                start_date,
                today,
            )
            if stats is not None:
                text = format_period_stats(stats, "текущую неделю")
                try:
                    report = achievement_service.get_or_create_report(
                        telegram_id=user.telegram_id,
                        week_start=start_date,
                        week_end=today,
                        stats=stats,
                    )
                    if report is not None:
                        text += "\n\n" + format_weekly_achievements(report)
                except (LLMProviderError, PsycopgError, ValueError) as error:
                    logger.exception(
                        "Could not generate weekly achievements for Telegram chat %s",
                        user.telegram_id,
                    )
                await application.bot.send_message(
                    chat_id=user.telegram_id,
                    text=text,
                )
        except Forbidden:
            logger.info("Skipping blocked Telegram chat %s", user.telegram_id)
        except NetworkError as error:
            logger.warning(
                "Could not send weekly stats to Telegram chat %s: %s",
                user.telegram_id,
                error,
            )


def schedule_jobs(application: Application, settings: Settings) -> None:
    scheduler = application.job_queue.scheduler
    scheduler.add_job(
        send_morning_checkin,
        CronTrigger.from_crontab(settings.morning_checkin_cron, timezone=settings.default_timezone),
        args=[application],
        id="morning_checkin",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=settings.scheduler_misfire_grace_seconds,
    )
    scheduler.add_job(
        send_midday_checkin,
        CronTrigger.from_crontab(settings.midday_checkin_cron, timezone=settings.default_timezone),
        args=[application],
        id="midday_checkin",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=settings.scheduler_misfire_grace_seconds,
    )
    scheduler.add_job(
        send_evening_review,
        CronTrigger.from_crontab(settings.evening_review_cron, timezone=settings.default_timezone),
        args=[application],
        id="evening_review",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=settings.scheduler_misfire_grace_seconds,
    )
    scheduler.add_job(
        send_weekly_stats,
        CronTrigger.from_crontab(
            getattr(settings, "weekly_stats_cron", "0 21 * * 0"),
            timezone=settings.default_timezone,
        ),
        args=[application],
        id="weekly_stats",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=settings.scheduler_misfire_grace_seconds,
    )


async def _broadcast_today(application: Application) -> None:
    db: Database = application.bot_data["db"]
    planning_service: PlanningService = application.bot_data["planning_service"]
    with db.connection() as conn:
        users = UserRepository(conn).list_users()

    for user in users:
        try:
            plan = planning_service.get_today_plan(user.telegram_id)
            text = (
                format_plan(plan)
                if plan is not None
                else "На сегодня плана ещё нет. Используйте /plan."
            )
            await application.bot.send_message(chat_id=user.telegram_id, text=text)
        except Forbidden:
            # Пользователь удалил или заблокировал бота. Это не должно
            # прерывать рассылку напоминаний остальным пользователям.
            logger.info("Skipping blocked Telegram chat %s", user.telegram_id)
        except NetworkError as error:
            # Telegram/DNS outages are transient. The next scheduled run and
            # polling loop must remain alive even if one reminder cannot be sent.
            logger.warning(
                "Could not send scheduled message to Telegram chat %s: %s",
                user.telegram_id,
                error,
            )
