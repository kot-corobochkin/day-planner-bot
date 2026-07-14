from datetime import date, timedelta

from telegram import ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes, ConversationHandler

from app.bot.keyboards import (
    DAY_TYPE_KEYBOARD,
    PLAN_DATE_KEYBOARD,
    cancellable_tasks_keyboard,
    unfinished_tasks_keyboard,
)
from app.models.task import TaskStatus
from app.services.planning_service import PlanningService, PlanWithTasks
from app.services.task_service import TaskService


(
    PLAN_DATE,
    DAY_TYPE,
    TASKS,
    DONE_DATE,
    CANCEL_DATE,
    MOVE_SOURCE_DATE,
    MOVE_TASKS,
    MOVE_TARGET_DATE,
) = range(8)


def _planning_service(context: ContextTypes.DEFAULT_TYPE) -> PlanningService:
    return context.application.bot_data["planning_service"]


def _task_service(context: ContextTypes.DEFAULT_TYPE) -> TaskService:
    return context.application.bot_data["task_service"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return

    _planning_service(context).register_user(update.effective_user.id)
    await update.message.reply_text(
        "Я помогу спланировать день.\n\n"
        "/plan - создать или дополнить план\n"
        "/today - показать план на сегодня\n"
        "/done - завершить задачу выбранной даты\n"
        "/cancel_task - отменить задачу выбранной даты\n"
        "/move_task - перенести задачи на другую дату\n"
        "/status - показать прогресс за сегодня"
    )


async def plan_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    await update.message.reply_text(
        "Выберите дату плана: «Сегодня», «Завтра» или введите YYYY-MM-DD.",
        reply_markup=PLAN_DATE_KEYBOARD,
    )
    return PLAN_DATE


def _parse_plan_date(value: str, *, allow_past: bool = False) -> date | None:
    normalized = value.strip().casefold()
    if normalized in {"today", "сегодня"}:
        return date.today()
    if normalized in {"tomorrow", "завтра"}:
        return date.today() + timedelta(days=1)
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if allow_past or parsed >= date.today() else None


async def receive_plan_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    plan_date = _parse_plan_date(update.message.text or "")
    if plan_date is None:
        await update.message.reply_text(
            "Введите «Сегодня», «Завтра» или будущую дату в формате YYYY-MM-DD."
        )
        return PLAN_DATE
    context.user_data["plan_date"] = plan_date.isoformat()
    await update.message.reply_text(
        "Какой это будет день?",
        reply_markup=DAY_TYPE_KEYBOARD,
    )
    return DAY_TYPE


async def receive_day_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END

    day_type = update.message.text or ""
    allowed = {"Рабочий день", "Выходной", "Смешанный", "Больничный"}
    if day_type not in allowed:
        await update.message.reply_text("Выберите один из предложенных типов дня.")
        return DAY_TYPE

    context.user_data["day_type"] = day_type
    await update.message.reply_text(
        "Введите задачи: по одной в строке. Можно добавить сколько угодно задач.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return TASKS


async def receive_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END

    task_lines = (update.message.text or "").splitlines()
    day_type = str(context.user_data.get("day_type", "Mixed"))
    plan_date = date.fromisoformat(
        str(context.user_data.get("plan_date", date.today().isoformat()))
    )

    try:
        plan = _planning_service(context).create_plan(
            telegram_id=update.effective_user.id,
            plan_date=plan_date,
            day_type=day_type,
            tasks=task_lines,
        )
    except ValueError:
        await update.message.reply_text("Введите хотя бы одну непустую задачу.")
        return TASKS

    await update.message.reply_text(_format_plan(plan))
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is not None:
        await update.message.reply_text("Планирование отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return

    plan = _planning_service(context).get_today_plan(update.effective_user.id)
    if plan is None:
        await update.message.reply_text("На сегодня плана ещё нет. Используйте /plan.")
        return

    await update.message.reply_text(_format_plan(plan))


async def _ask_task_action_date(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    action: str,
    state: int,
) -> int:
    if update.message is None:
        return ConversationHandler.END
    context.user_data["task_action"] = action
    await update.message.reply_text(
        "Выберите дату плана: «Сегодня», «Завтра» или введите YYYY-MM-DD.",
        reply_markup=PLAN_DATE_KEYBOARD,
    )
    return state


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _ask_task_action_date(
        update,
        context,
        action="complete",
        state=DONE_DATE,
    )


async def cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _ask_task_action_date(
        update,
        context,
        action="cancel",
        state=CANCEL_DATE,
    )


async def receive_task_action_date(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    plan_date = _parse_plan_date(update.message.text or "")
    if plan_date is None:
        await update.message.reply_text(
            "Введите «Сегодня», «Завтра» или будущую дату в формате YYYY-MM-DD."
        )
        return (
            DONE_DATE
            if context.user_data.get("task_action") == "complete"
            else CANCEL_DATE
        )
    action = str(context.user_data.get("task_action") or "")
    tasks = _task_service(context).get_unfinished_tasks_for_date(
        update.effective_user.id,
        plan_date,
    )
    if not tasks:
        await update.message.reply_text(f"На {plan_date} нет запланированных задач.")
        return ConversationHandler.END
    if action == "complete":
        await update.message.reply_text(
            f"Выберите задачу, которую нужно завершить ({plan_date}):",
            reply_markup=unfinished_tasks_keyboard(tasks),
        )
    else:
        await update.message.reply_text(
            f"Выберите задачу, которую нужно отменить ({plan_date}):",
            reply_markup=cancellable_tasks_keyboard(tasks),
        )
    return ConversationHandler.END


async def move_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    await update.message.reply_text(
        "Выберите дату, с которой нужно перенести задачи: «Сегодня», «Завтра» "
        "или YYYY-MM-DD.",
        reply_markup=PLAN_DATE_KEYBOARD,
    )
    return MOVE_SOURCE_DATE


def _format_numbered_tasks(tasks) -> str:
    return "\n".join(f"{index}. {task.text}" for index, task in enumerate(tasks, start=1))


async def receive_move_source_date(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    source_date = _parse_plan_date(update.message.text or "", allow_past=True)
    if source_date is None:
        await update.message.reply_text(
            "Введите «Сегодня», «Завтра» или дату в формате YYYY-MM-DD."
        )
        return MOVE_SOURCE_DATE
    tasks = _task_service(context).get_unfinished_tasks_for_date(
        update.effective_user.id,
        source_date,
    )
    if not tasks:
        await update.message.reply_text(f"На {source_date} нет задач для переноса.")
        return ConversationHandler.END
    context.user_data["move_source_date"] = source_date.isoformat()
    context.user_data["move_task_ids"] = [task.id for task in tasks]
    await update.message.reply_text(
        f"Задачи на {source_date}:\n{_format_numbered_tasks(tasks)}\n\n"
        "Введите номера задач через запятую, например: 1, 2, 3, 6."
    )
    return MOVE_TASKS


def _parse_task_indexes(value: str, *, maximum: int) -> list[int] | None:
    try:
        indexes = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError:
        return None
    if not indexes or any(index < 1 or index > maximum for index in indexes):
        return None
    return list(dict.fromkeys(indexes))


async def receive_move_tasks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if update.message is None:
        return ConversationHandler.END
    task_ids = list(context.user_data.get("move_task_ids") or [])
    indexes = _parse_task_indexes(update.message.text or "", maximum=len(task_ids))
    if indexes is None:
        await update.message.reply_text("Введите номера через запятую, например: 1, 2, 3.")
        return MOVE_TASKS
    context.user_data["selected_move_task_ids"] = [task_ids[index - 1] for index in indexes]
    await update.message.reply_text(
        "На какую дату перенести выбранные задачи? Выберите «Сегодня», «Завтра» "
        "или введите YYYY-MM-DD.",
        reply_markup=PLAN_DATE_KEYBOARD,
    )
    return MOVE_TARGET_DATE


async def receive_move_target_date(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    target_date = _parse_plan_date(update.message.text or "")
    source_date = date.fromisoformat(str(context.user_data.get("move_source_date")))
    if target_date is None:
        await update.message.reply_text(
            "Введите «Сегодня», «Завтра» или будущую дату в формате YYYY-MM-DD."
        )
        return MOVE_TARGET_DATE
    if target_date == source_date:
        await update.message.reply_text("Выберите дату, отличающуюся от исходной.")
        return MOVE_TARGET_DATE
    task_ids = list(context.user_data.get("selected_move_task_ids") or [])
    moved = _task_service(context).move_tasks(
        task_ids,
        telegram_id=update.effective_user.id,
        target_date=target_date,
    )
    await update.message.reply_text(
        f"Перенесено задач: {len(moved)}. Новая дата: {target_date}.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return

    stats = _task_service(context).get_stats_for_today(update.effective_user.id)
    if stats is None:
        await update.message.reply_text("На сегодня плана ещё нет. Используйте /plan.")
        return

    await update.message.reply_text(
        "Прогресс за сегодня:\n"
        f"Всего задач: {stats.total}\n"
        f"Выполнено: {stats.completed}\n"
        f"Отложено: {stats.postponed}\n"
        f"Отменено: {stats.cancelled}\n"
        f"Выполнение: {stats.completion_percentage}%"
    )


def _format_plan(plan_with_tasks: PlanWithTasks) -> str:
    lines = [
        f"План на {plan_with_tasks.plan.plan_date} ({plan_with_tasks.plan.day_type}):",
        "",
    ]
    for index, task in enumerate(plan_with_tasks.tasks, start=1):
        marker = "x" if task.status == TaskStatus.done else " "
        lines.append(f"{index}. [{marker}] {task.text} - {task.status.value}")
    return "\n".join(lines)
