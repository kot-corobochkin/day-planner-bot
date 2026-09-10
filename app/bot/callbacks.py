from telegram import Update
from telegram.ext import ContextTypes
from psycopg import Error as PsycopgError

from app.bot.task_card import format_task_card
from app.bot.statistics import format_awarded_goal_achievement
from app.services.task_service import TaskService
from app.services.weekly_achievements import WeeklyAchievementService


def _task_service(context: ContextTypes.DEFAULT_TYPE) -> TaskService:
    return context.application.bot_data["task_service"]


def _weekly_achievement_service(
    context: ContextTypes.DEFAULT_TYPE,
) -> WeeklyAchievementService | None:
    return context.application.bot_data.get("weekly_achievement_service")


async def handle_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return

    await query.answer()
    prefix, _, task_id_raw = query.data.partition(":")
    if prefix not in {"done", "cancel", "task"} or not task_id_raw.isdigit():
        return

    task_service = _task_service(context)
    if prefix == "task":
        details = task_service.get_task_details(int(task_id_raw), update.effective_user.id)
        if details is None:
            await query.edit_message_text("Задача не найдена или отменена.")
            return
        await query.edit_message_text(format_task_card(details))
        return

    task = (
        task_service.mark_done(int(task_id_raw), update.effective_user.id)
        if prefix == "done"
        else task_service.cancel_task(int(task_id_raw), update.effective_user.id)
    )
    if task is None:
        await query.edit_message_text("Задача не найдена или уже была изменена.")
        return

    message = "Задача выполнена" if prefix == "done" else "Задача отменена"
    text = f"{message}: {task.text}"
    if prefix == "done":
        achievement_service = _weekly_achievement_service(context)
        try:
            award = (
                achievement_service.award_for_completed_task(
                    telegram_id=update.effective_user.id, task_id=task.id
                )
                if achievement_service is not None
                else None
            )
        except PsycopgError:
            # Задача уже завершена; сбой необязательной награды не отменяет результат.
            award = None
        if award is not None:
            text += "\n\n" + format_awarded_goal_achievement(award)
    await query.edit_message_text(text)
