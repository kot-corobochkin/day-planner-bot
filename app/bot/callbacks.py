from telegram import Update
from telegram.ext import ContextTypes

from app.services.task_service import TaskService


def _task_service(context: ContextTypes.DEFAULT_TYPE) -> TaskService:
    return context.application.bot_data["task_service"]


async def handle_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return

    await query.answer()
    prefix, _, task_id_raw = query.data.partition(":")
    if prefix not in {"done", "cancel"} or not task_id_raw.isdigit():
        return

    task_service = _task_service(context)
    task = (
        task_service.mark_done(int(task_id_raw), update.effective_user.id)
        if prefix == "done"
        else task_service.cancel_task(int(task_id_raw), update.effective_user.id)
    )
    if task is None:
        await query.edit_message_text("Задача не найдена или уже была изменена.")
        return

    message = "Задача выполнена" if prefix == "done" else "Задача отменена"
    await query.edit_message_text(f"{message}: {task.text}")
