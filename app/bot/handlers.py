import asyncio
import logging
import re
from datetime import date, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes, ConversationHandler
from psycopg import Error as PsycopgError

from app.bot.formatters import format_plan
from app.bot.keyboards import (
    DAY_TYPE_KEYBOARD,
    ai_estimate_draft_keyboard,
    ai_estimate_actions_keyboard,
    ai_estimate_task_keyboard,
    ai_plan_actions_keyboard,
    ai_plan_retry_keyboard,
    save_fixed_time_keyboard,
    FEASIBILITY_TIME_KEYBOARD,
    PLAN_DATE_KEYBOARD,
    SURVEY_MODE_KEYBOARD,
    DAY_MODE_KEYBOARD,
    strategy_selection_keyboard,
    cancellable_tasks_keyboard,
    task_details_keyboard,
    task_edit_keyboard,
    feasibility_move_keyboard,
    repeated_move_keyboard,
    schedule_source_keyboard,
    unfinished_tasks_keyboard,
)
from app.bot.task_card import format_task_card
from app.bot.statistics import (
    format_awarded_goal_achievement,
    format_period_stats,
    format_weekly_achievements,
)
from app.models.task import TaskStatus
from app.services.planning_service import PlanningService
from app.services.task_input_parser import (
    TaskInputError,
    TaskDraft,
    parse_task_lines,
    parse_task_update,
)
from app.services.task_prioritization import (
    order_tasks_by_priority,
)
from app.services.feasibility import recommend_moves
from app.services.priority_reporting import (
    format_feasibility_report,
    format_priority_details,
)
from app.services.task_service import TaskService
from app.services.capture_service import CaptureService
from app.services.ai_estimation import AIEstimationService
from app.services.ai_planning import AIPlanningService, AIPlanProposal, calculate_schedule
from app.services.ai_reflection import AIReflectionService
from app.services.planning_agent import PlanningAgentService
from app.services.agent_memory import AgentMemory
from app.services.evening_reflection import EveningReflectionService
from app.services.llm_provider import LLMProviderError
from app.services.day_strategy import STRATEGIES, recommend_strategies
from app.services.statistics_service import StatisticsService
from app.services.weekly_achievements import WeeklyAchievementService


logger = logging.getLogger(__name__)


(
    PLAN_DATE,
    DAY_TYPE,
    TASKS,
    DONE_DATE,
    CANCEL_DATE,
    MOVE_SOURCE_DATE,
    MOVE_TASKS,
    MOVE_TARGET_DATE,
    TASK_DATE,
    TASK_EDIT_DATE,
    TASK_EDIT_SELECT,
    TASK_EDIT_FIELDS,
    FEASIBILITY_DATE,
    FEASIBILITY_TIME,
    FEASIBILITY_MOVE_DECISION,
    FEASIBILITY_MOVE_SELECT,
    IDEA_TEXT,
    INBOX_TEXT,
    SCHEDULE_SELECT,
    SCHEDULE_DATE,
    AI_DATE,
    AI_ACTION,
    AI_TASK,
    AI_PLAN_DATE,
    AI_PLAN_ACTION,
    AI_PLAN_SELECT,
    AI_PLAN_SURVEY_MODE,
    AI_PLAN_SHORT_ENERGY,
    AI_PLAN_SHORT_CONCENTRATION,
    AI_PLAN_SHORT_MENTAL_FATIGUE,
    AI_PLAN_SHORT_PHYSICAL_ENERGY,
    AI_PLAN_DAY_MODE,
    AI_PLAN_LONG_QUESTION,
    AI_PLAN_STRATEGY,
    AI_PLAN_STRATEGY_REASON,
    EVENING_REFLECTION_ANSWER,
    MOVE_REPEAT_CONFIRM,
    AI_PLAN_AGENT_QUESTION,
    AI_PLAN_FIXED_TIME_SAVE,
    AI_PLAN_FEEDBACK,
    AI_PLAN_GOAL_SUGGESTIONS,
) = range(41)


def _planning_service(context: ContextTypes.DEFAULT_TYPE) -> PlanningService:
    return context.application.bot_data["planning_service"]


def _task_service(context: ContextTypes.DEFAULT_TYPE) -> TaskService:
    return context.application.bot_data["task_service"]


def _capture_service(context: ContextTypes.DEFAULT_TYPE) -> CaptureService:
    return context.application.bot_data["capture_service"]


def _ai_estimation_service(context: ContextTypes.DEFAULT_TYPE) -> AIEstimationService:
    return AIEstimationService(context.application.bot_data["llm_provider"])


def _ai_planning_service(context: ContextTypes.DEFAULT_TYPE) -> AIPlanningService:
    return AIPlanningService(context.application.bot_data["llm_provider"])


def _ai_reflection_service(context: ContextTypes.DEFAULT_TYPE) -> AIReflectionService:
    return AIReflectionService(context.application.bot_data["llm_provider"])


def _planning_agent_service(context: ContextTypes.DEFAULT_TYPE) -> PlanningAgentService:
    return PlanningAgentService(context.application.bot_data["llm_provider"])


def _evening_reflection_service(context: ContextTypes.DEFAULT_TYPE) -> EveningReflectionService:
    return EveningReflectionService(context.application.bot_data["llm_provider"])


def _statistics_service(context: ContextTypes.DEFAULT_TYPE) -> StatisticsService:
    service = context.application.bot_data.get("statistics_service")
    if service is None:
        service = StatisticsService(context.application.bot_data["db"])
        context.application.bot_data["statistics_service"] = service
    return service


def _weekly_achievement_service(
    context: ContextTypes.DEFAULT_TYPE,
) -> WeeklyAchievementService | None:
    application = getattr(context, "application", None)
    if application is None:
        return None
    return application.bot_data.get("weekly_achievement_service")


def _award_for_completed_task(context, *, telegram_id: int, task_id: int):
    service = _weekly_achievement_service(context)
    if service is None:
        return None
    try:
        return service.award_for_completed_task(
            telegram_id=telegram_id,
            task_id=task_id,
        )
    except PsycopgError:
        # Выполнение задачи уже сохранено и не должно выглядеть неуспешным,
        # даже если подсистема наград временно недоступна.
        return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return

    _planning_service(context).register_user(update.effective_user.id)
    await update.message.reply_text(_help_text())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(_help_text())


def _help_text() -> str:
    return (
        "Я помогу спланировать день.\n\n"
        "/plan - создать или дополнить план; быстро: /plan Название задачи (сегодня) или /plan 2026-10-01 Название задачи\n"
        "/plan_view YYYY-MM-DD - показать нумерованный план выбранной даты\n"
        "/today - показать план на сегодня\n"
        "/done - завершить задачи выбранной даты; быстро: /done 6 или /done 1,2,3\n"
        "/cancel_task - отменить задачу выбранной даты\n"
        "/move_task - перенести задачи на другую дату; быстро: /move_task 1,5 tomorrow\n"
        "/unschedule_task - убрать задачи в список без даты; быстро: /unschedule_task 1,2,3\n"
        "/task - выбрать дату и открыть карточку; быстро: /task today 6 или /task 6\n"
        "/task_edit - изменить параметры и название неотменённой задачи. "
        "Пример: /task_edit 6 -название:Новое название -важность:2\n"
        "/feasibility - проверить, помещаются ли задачи в доступное время. "
        "Можно взять норму типа дня или указать своё время\n"
        "/plan_analysis_details [дата] - подробный расчёт приоритетов\n"
        "/ai_estimate - получить AI-предложения параметров задач\n"
        "/ai_plan - предложить порядок выполнения задач; /ai_plan_view [дата] - показать расписание\n"
        "/evening_reflection - ответить на 10 вечерних вопросов по плану текущего дня\n"
        "/agent_memory - показать память, которую читает агент\n"
        "/category <категория> - показать запланированные задачи категории на ближайшие три дня\n"
        "/idea - записать идеи по одной в строке; /ideas - посмотреть идеи\n"
        "/inbox - записать задачу без даты; /backlog - посмотреть такие задачи\n"
        "/upcoming - показать будущие задачи; /schedule_task - назначить дату идее или задаче без даты\n"
        "/status - показать прогресс за сегодня\n"
        "/stat [week|month] - статистика за неделю или текущий месяц, включая категории\n"
        "/help - показать эту справку"
        "\n\nБыстрые вызовы:\n"
        "/done 1,2,3\n"
        "/task_edit 6 -важность:2\n"
        "/move_task 1,5,6 tomorrow\n"
        "/unschedule_task 1,2,3\n"
        "Для другой даты передайте её первым аргументом: /done 2026-07-16 6"
    )


async def plan_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None or update.effective_user is None:
        return ConversationHandler.END
    if getattr(context, "args", ()):
        return await _create_short_plan(update, context)
    await update.message.reply_text(
        "Выберите дату плана: «Сегодня», «Завтра» или введите YYYY-MM-DD.",
        reply_markup=PLAN_DATE_KEYBOARD,
    )
    return PLAN_DATE


async def _create_short_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None or update.effective_user is None:
        return ConversationHandler.END
    arguments = list(context.args)
    explicit_date = _parse_plan_date(arguments[0]) if arguments else None
    plan_date = explicit_date or date.today()
    task_parts = arguments[1:] if explicit_date is not None else arguments
    if not task_parts:
        await update.message.reply_text(
            "Формат: /plan Название задачи\n"
            "Или с датой: /plan YYYY-MM-DD Название задачи\n"
            "Например: /plan Скачать новый подкаст"
        )
        return ConversationHandler.END

    try:
        tasks = parse_task_lines([" ".join(task_parts)])
        existing_plan = _planning_service(context).get_plan_for_date(
            update.effective_user.id,
            plan_date,
        )
        plan = _planning_service(context).create_plan(
            telegram_id=update.effective_user.id,
            plan_date=plan_date,
            day_type=existing_plan.day_type if existing_plan else "Смешанный",
            tasks=tasks,
        )
    except TaskInputError as error:
        await update.message.reply_text(str(error))
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Укажите название задачи после даты.")
        return ConversationHandler.END
    except PsycopgError:
        await update.message.reply_text(
            "Не удалось сохранить задачу. Проверьте параметры и повторите ввод; "
            "изменения не сохранены."
        )
        return ConversationHandler.END

    await update.message.reply_text(format_plan(plan))
    return ConversationHandler.END


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
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    plan_date = _parse_plan_date(update.message.text or "")
    if plan_date is None:
        await update.message.reply_text(
            "Введите «Сегодня», «Завтра» или будущую дату в формате YYYY-MM-DD."
        )
        return PLAN_DATE
    context.user_data["plan_date"] = plan_date.isoformat()
    existing_plan = _planning_service(context).get_plan_for_date(
        update.effective_user.id,
        plan_date,
    )
    if existing_plan is not None:
        context.user_data["day_type"] = existing_plan.day_type
        await update.message.reply_text(
            f"План на {plan_date} уже имеет тип «{existing_plan.day_type}».\n"
            + _task_input_prompt(),
            reply_markup=ReplyKeyboardRemove(),
        )
        return TASKS
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
        _task_input_prompt(),
        reply_markup=ReplyKeyboardRemove(),
    )
    return TASKS


def _task_input_prompt() -> str:
    return (
        "Введите задачи по одной в строке. Параметры можно писать в той же строке:\n"
        "Подготовить отчёт -длительность:2 ч -время начала:10:00 "
        "-дедлайн:19:00 -важность:5 -сложность:8 -контекст:компьютер\n\n"
        "Параметры необязательны. Длительность по умолчанию: 1 час. "
        "Важность и сложность: от 1 до 10."
    )


async def receive_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END

    task_lines = (update.message.text or "").splitlines()
    day_type = str(context.user_data.get("day_type", "Mixed"))
    plan_date = date.fromisoformat(
        str(context.user_data.get("plan_date", date.today().isoformat()))
    )

    try:
        tasks = parse_task_lines(task_lines)
        plan = _planning_service(context).create_plan(
            telegram_id=update.effective_user.id,
            plan_date=plan_date,
            day_type=day_type,
            tasks=tasks,
        )
    except TaskInputError as error:
        await update.message.reply_text(str(error))
        return TASKS
    except ValueError:
        await update.message.reply_text("Введите хотя бы одну непустую задачу.")
        return TASKS
    except PsycopgError:
        await update.message.reply_text(
            "Не удалось сохранить задачи. Проверьте параметры и повторите ввод; "
            "изменения не сохранены."
        )
        return TASKS

    await update.message.reply_text(format_plan(plan))
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

    await update.message.reply_text(format_plan(plan))


async def plan_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Формат: /plan_view 2026-07-16")
        return
    plan_date = _parse_plan_date(context.args[0], allow_past=True)
    if plan_date is None:
        await update.message.reply_text("Укажите дату: today, tomorrow или YYYY-MM-DD.")
        return
    plan = _planning_service(context).get_plan_with_tasks_for_date(
        update.effective_user.id,
        plan_date,
    )
    if plan is None:
        await update.message.reply_text(f"На {plan_date} плана ещё нет.")
        return
    await update.message.reply_text(format_plan(plan))


async def plan_analysis_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    if len(context.args) > 1:
        await update.message.reply_text("Формат: /plan_analysis_details [today|YYYY-MM-DD]")
        return
    plan_date = (
        _parse_plan_date(context.args[0], allow_past=True)
        if context.args
        else date.today()
    )
    if plan_date is None:
        await update.message.reply_text("Укажите дату: today, tomorrow или YYYY-MM-DD.")
        return
    tasks = [
        task
        for task in _task_service(context).get_visible_tasks_for_date(
            update.effective_user.id,
            plan_date,
        )
        if task.status == TaskStatus.planned
    ]
    if not tasks:
        await update.message.reply_text(f"На {plan_date} нет запланированных задач.")
        return
    await _reply_text_in_chunks(
        update.message,
        format_priority_details(plan_date, tasks),
    )


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
    if context.args:
        return await _quick_done(update, context)
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


async def task_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.args:
        return await _quick_task_card(update, context)
    if update.message is None:
        return ConversationHandler.END
    await update.message.reply_text(
        "Выберите дату плана: «Сегодня», «Завтра» или введите YYYY-MM-DD.",
        reply_markup=PLAN_DATE_KEYBOARD,
    )
    return TASK_DATE


async def _quick_task_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    if len(context.args) == 1 and context.args[0].isdigit():
        plan_date = date.today()
        index = int(context.args[0])
    elif len(context.args) == 2 and context.args[1].isdigit():
        plan_date = _parse_plan_date(context.args[0], allow_past=True)
        index = int(context.args[1])
    else:
        await update.message.reply_text("Формат: /task today 6 или /task 6")
        return ConversationHandler.END
    if plan_date is None:
        await update.message.reply_text("Укажите дату: today, tomorrow или YYYY-MM-DD.")
        return ConversationHandler.END
    tasks = _tasks_in_display_order(
        _task_service(context).get_visible_tasks_for_date(
            update.effective_user.id,
            plan_date,
        )
    )
    if index < 1 or index > len(tasks):
        await update.message.reply_text(f"На {plan_date} нет задачи с номером {index}.")
        return ConversationHandler.END
    details = _task_service(context).get_task_details(
        tasks[index - 1].id,
        update.effective_user.id,
    )
    await update.message.reply_text(
        format_task_card(details) if details else "Задача не найдена или отменена."
    )
    return ConversationHandler.END


async def receive_task_date(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    plan_date = _parse_plan_date(update.message.text or "", allow_past=True)
    if plan_date is None:
        await update.message.reply_text(
            "Введите «Сегодня», «Завтра» или дату в формате YYYY-MM-DD."
        )
        return TASK_DATE
    tasks = _task_service(context).get_visible_tasks_for_date(
        update.effective_user.id,
        plan_date,
    )
    if not tasks:
        await update.message.reply_text(f"На {plan_date} нет доступных задач.")
        return ConversationHandler.END
    await update.message.reply_text(
        f"Выберите задачу ({plan_date}):",
        reply_markup=task_details_keyboard(tasks),
    )
    return ConversationHandler.END


async def task_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.args:
        return await _quick_task_edit(update, context)
    if update.message is None:
        return ConversationHandler.END
    await update.message.reply_text(
        "Выберите дату плана: «Сегодня», «Завтра» или введите YYYY-MM-DD.",
        reply_markup=PLAN_DATE_KEYBOARD,
    )
    return TASK_EDIT_DATE


async def receive_task_edit_date(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    plan_date = _parse_plan_date(update.message.text or "", allow_past=True)
    if plan_date is None:
        await update.message.reply_text(
            "Введите «Сегодня», «Завтра» или дату в формате YYYY-MM-DD."
        )
        return TASK_EDIT_DATE
    tasks = _task_service(context).get_visible_tasks_for_date(
        update.effective_user.id,
        plan_date,
    )
    if not tasks:
        await update.message.reply_text(f"На {plan_date} нет доступных задач.")
        return ConversationHandler.END
    await update.message.reply_text(
        f"Выберите задачу для изменения ({plan_date}):",
        reply_markup=task_edit_keyboard(tasks),
    )
    return TASK_EDIT_SELECT


async def receive_task_edit_selection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return ConversationHandler.END
    _, _, task_id_raw = query.data.partition(":")
    if not task_id_raw.isdigit():
        return ConversationHandler.END
    details = _task_service(context).get_task_details(
        int(task_id_raw),
        update.effective_user.id,
    )
    await query.answer()
    if details is None:
        await query.edit_message_text("Задача не найдена или отменена.")
        return ConversationHandler.END
    context.user_data["task_edit_id"] = details.task.id
    await query.edit_message_text(
        "Введите параметры для изменения. Например:\n"
        "-название:Исправить обработку YouTube -важность:2 -сложность:8 "
        "-длительность:1:30 -контекст:звонок\n\n"
        "Можно изменить: название, длительность, время начала, дедлайн, важность, "
        "сложность, контекст и статус. Чтобы очистить длительность, время, "
        "дедлайн или контекст, укажите значение «нет».\n"
        "Статус: запланирована, выполнена или отложена.",
    )
    return TASK_EDIT_FIELDS


async def receive_task_edit_fields(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    task_id = context.user_data.get("task_edit_id")
    if not isinstance(task_id, int):
        await update.message.reply_text("Выберите задачу заново через /task_edit.")
        return ConversationHandler.END
    try:
        update_values = parse_task_update(update.message.text or "")
        details = _task_service(context).update_task(
            task_id,
            telegram_id=update.effective_user.id,
            update=update_values,
        )
    except (TaskInputError, ValueError) as error:
        await update.message.reply_text(str(error))
        return TASK_EDIT_FIELDS
    if details is None:
        await update.message.reply_text("Задача не найдена или отменена.")
        return ConversationHandler.END
    context.user_data.pop("task_edit_id", None)
    await update.message.reply_text(f"Задача обновлена: {details.task.text}")
    return ConversationHandler.END


async def feasibility(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    await update.message.reply_text(
        "Выберите дату плана: «Сегодня», «Завтра» или введите YYYY-MM-DD.",
        reply_markup=PLAN_DATE_KEYBOARD,
    )
    return FEASIBILITY_DATE


async def receive_feasibility_date(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    plan_date = _parse_plan_date(update.message.text or "", allow_past=True)
    if plan_date is None:
        await update.message.reply_text(
            "Введите «Сегодня», «Завтра» или дату в формате YYYY-MM-DD."
        )
        return FEASIBILITY_DATE
    available_minutes = _task_service(context).get_available_minutes(
        update.effective_user.id,
        plan_date,
    )
    if available_minutes is None:
        await update.message.reply_text(f"На {plan_date} плана ещё нет. Используйте /plan.")
        return ConversationHandler.END
    context.user_data["feasibility_date"] = plan_date.isoformat()
    context.user_data["feasibility_default_minutes"] = available_minutes
    await update.message.reply_text(
        f"Доступное время по умолчанию: {_format_minutes(available_minutes)}.\n"
        "Нажмите «По умолчанию» или введите своё время: 6 ч, 6:30 или 360 м.",
        reply_markup=FEASIBILITY_TIME_KEYBOARD,
    )
    return FEASIBILITY_TIME


async def receive_feasibility_time(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    response = (update.message.text or "").strip().casefold()
    if response in {"по умолчанию", "default"}:
        available_minutes = None
    else:
        try:
            from app.services.task_input_parser import parse_available_minutes

            available_minutes = parse_available_minutes(update.message.text or "")
        except TaskInputError as error:
            await update.message.reply_text(str(error))
            return FEASIBILITY_TIME
    plan_date_raw = context.user_data.get("feasibility_date")
    if not isinstance(plan_date_raw, str):
        await update.message.reply_text("Выберите дату заново через /feasibility.")
        return ConversationHandler.END
    plan_date = date.fromisoformat(plan_date_raw)
    result = _task_service(context).analyze_feasibility(
        update.effective_user.id,
        plan_date,
        available_minutes,
    )
    if result is None:
        await update.message.reply_text(f"На {plan_date} плана ещё нет. Используйте /plan.")
        return ConversationHandler.END
    context.user_data.pop("feasibility_date", None)
    context.user_data.pop("feasibility_default_minutes", None)
    if result.is_overloaded and result.move_candidates:
        recommendation = recommend_moves(result)
        candidates = recommendation.tasks
        context.user_data["feasibility_default_task_ids"] = [
            candidate.task.id for candidate in candidates
        ]
        context.user_data["feasibility_selectable_task_ids"] = [
            task.id for task in result.planned_tasks
        ]
        context.user_data["feasibility_source_date"] = plan_date.isoformat()
        await _reply_text_in_chunks(
            update.message,
            format_feasibility_report(plan_date, result, recommendation)
            + "\n\nПеренос выполняется на завтра.",
            reply_markup=feasibility_move_keyboard(),
        )
        return FEASIBILITY_MOVE_DECISION
    await _reply_text_in_chunks(
        update.message,
        format_feasibility_report(plan_date, result),
    )
    return ConversationHandler.END


async def receive_feasibility_move_decision(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    if query is None or query.data is None:
        return ConversationHandler.END
    await query.answer()
    decision = query.data.removeprefix("feasmove:")
    if decision == "skip":
        _clear_feasibility_move_data(context)
        await query.edit_message_text("План оставлен без изменений.")
        return ConversationHandler.END
    if decision == "default":
        task_ids = list(context.user_data.get("feasibility_default_task_ids") or [])
        return await _move_feasibility_tasks_to_tomorrow(update, context, task_ids)
    if decision == "select":
        task_ids = list(context.user_data.get("feasibility_selectable_task_ids") or [])
        if not task_ids:
            await query.edit_message_text("Нет задач для переноса.")
            return ConversationHandler.END
        tasks = _task_service(context).get_visible_tasks_for_date(
            update.effective_user.id,
            date.fromisoformat(str(context.user_data["feasibility_source_date"])),
        ) if update.effective_user else []
        tasks = [task for task in tasks if task.status == TaskStatus.planned]
        context.user_data["feasibility_selectable_task_ids"] = [task.id for task in tasks]
        await query.edit_message_text(
            "Введите номера задач для переноса на завтра через запятую:\n\n"
            f"{_format_numbered_tasks(tasks)}"
        )
        return FEASIBILITY_MOVE_SELECT
    return ConversationHandler.END


async def receive_feasibility_move_selection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if update.message is None:
        return ConversationHandler.END
    task_ids = list(context.user_data.get("feasibility_selectable_task_ids") or [])
    indexes = _parse_task_indexes(update.message.text or "", maximum=len(task_ids))
    if indexes is None:
        await update.message.reply_text("Введите номера через запятую, например: 1, 5, 6.")
        return FEASIBILITY_MOVE_SELECT
    selected_task_ids = [task_ids[index - 1] for index in indexes]
    return await _move_feasibility_tasks_to_tomorrow(
        update,
        context,
        selected_task_ids,
    )


async def ai_estimate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    if context.args:
        if len(context.args) != 1:
            await update.message.reply_text("Формат: /ai_estimate [today|YYYY-MM-DD]")
            return ConversationHandler.END
        plan_date = _parse_plan_date(context.args[0], allow_past=True)
        if plan_date is None:
            await update.message.reply_text("Укажите дату: today, tomorrow или YYYY-MM-DD.")
            return ConversationHandler.END
        return await _run_ai_estimate(update, context, plan_date)
    await update.message.reply_text(
        "Выберите дату задач для AI-оценки: «Сегодня», «Завтра» или YYYY-MM-DD.",
        reply_markup=PLAN_DATE_KEYBOARD,
    )
    return AI_DATE


async def receive_ai_estimate_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    plan_date = _parse_plan_date(update.message.text or "", allow_past=True)
    if plan_date is None:
        await update.message.reply_text("Введите дату: today, tomorrow или YYYY-MM-DD.")
        return AI_DATE
    return await _run_ai_estimate(update, context, plan_date)


async def ai_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    if len(context.args) > 1:
        await update.message.reply_text("Формат: /ai_plan [today|YYYY-MM-DD]")
        return ConversationHandler.END
    if context.args:
        plan_date = _parse_plan_date(context.args[0])
        if plan_date is None:
            await update.message.reply_text("Укажите дату: today, tomorrow или YYYY-MM-DD.")
            return ConversationHandler.END
        return await _start_day_state_survey(update, context, plan_date)
    await update.message.reply_text(
        "Выберите дату для AI-порядка: «Сегодня», «Завтра» или YYYY-MM-DD.",
        reply_markup=PLAN_DATE_KEYBOARD,
    )
    return AI_PLAN_DATE


async def receive_ai_plan_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    plan_date = _parse_plan_date(update.message.text or "")
    if plan_date is None:
        await update.message.reply_text("Введите дату: today, tomorrow или YYYY-MM-DD.")
        return AI_PLAN_DATE
    return await _start_day_state_survey(update, context, plan_date)


async def _start_day_state_survey(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_date: date) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    schedule_context = _task_service(context).get_schedule_context(update.effective_user.id, plan_date)
    if schedule_context is None:
        await update.message.reply_text(f"На {plan_date} плана ещё нет.")
        return ConversationHandler.END
    if not schedule_context.tasks:
        await update.message.reply_text(f"На {plan_date} нет запланированных задач.")
        return ConversationHandler.END
    context.user_data["day_state_date"] = plan_date.isoformat()
    context.user_data["day_state_answers"] = {}
    context.user_data.pop("ai_plan_agent_answers", None)
    await update.message.reply_text(
        "Перед рекомендациями выберите формат оценки состояния.", reply_markup=SURVEY_MODE_KEYBOARD
    )
    return AI_PLAN_SURVEY_MODE


async def receive_day_state_survey_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    value = update.message.text or ""
    if value == "Короткий опрос":
        context.user_data["day_state_mode"] = "short"
        await update.message.reply_text("Энергия от 1 до 10?\n1 — буквально засыпаю, 10 — высокий запас энергии.")
        return AI_PLAN_SHORT_ENERGY
    if value == "Длинный опрос":
        context.user_data["day_state_mode"] = "long"
        context.user_data["day_state_long_index"] = 0
        await update.message.reply_text("1. Энергия мозга\nПо шкале от 1 до 10 насколько ты сейчас ощущаешь себя бодрым?\n1 — буквально засыпаю. 10 — чувствую высокий запас энергии.")
        return AI_PLAN_LONG_QUESTION
    await update.message.reply_text("Выберите «Короткий опрос» или «Длинный опрос».", reply_markup=SURVEY_MODE_KEYBOARD)
    return AI_PLAN_SURVEY_MODE


def _state_answers(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault("day_state_answers", {})


def _parse_scale(value: str) -> int | None:
    try:
        number = int(value.strip())
    except ValueError:
        return None
    return number if 1 <= number <= 10 else None


async def receive_day_state_short_energy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    value = _parse_scale(update.message.text or "")
    if value is None:
        await update.message.reply_text("Введите целое число от 1 до 10.")
        return AI_PLAN_SHORT_ENERGY
    _state_answers(context)["brain_energy"] = value
    await update.message.reply_text("Концентрация от 1 до 10?")
    return AI_PLAN_SHORT_CONCENTRATION


async def receive_day_state_short_concentration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    value = _parse_scale(update.message.text or "")
    if value is None:
        await update.message.reply_text("Введите целое число от 1 до 10.")
        return AI_PLAN_SHORT_CONCENTRATION
    _state_answers(context)["concentration"] = value
    await update.message.reply_text("Ментальная усталость от 1 до 10?\n1 — голова свежая, 10 — совсем не соображаю.")
    return AI_PLAN_SHORT_MENTAL_FATIGUE


async def receive_day_state_short_mental_fatigue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    value = _parse_scale(update.message.text or "")
    if value is None:
        await update.message.reply_text("Введите целое число от 1 до 10.")
        return AI_PLAN_SHORT_MENTAL_FATIGUE
    _state_answers(context)["mental_fatigue"] = value
    await update.message.reply_text("Физическая энергия от 1 до 10?")
    return AI_PLAN_SHORT_PHYSICAL_ENERGY


async def receive_day_state_short_physical_energy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    value = _parse_scale(update.message.text or "")
    if value is None:
        await update.message.reply_text("Введите целое число от 1 до 10.")
        return AI_PLAN_SHORT_PHYSICAL_ENERGY
    _state_answers(context)["physical_energy"] = value
    await update.message.reply_text("Какой режим дня тебе нужен?", reply_markup=DAY_MODE_KEYBOARD)
    return AI_PLAN_DAY_MODE


LONG_QUESTIONS = (
    "2. Ментальная усталость\nЧто сейчас сильнее?\nа) тело устало;\nб) голова «не соображает»;\nв) устали оба;\nг) почти не устал.",
    "3. Последние два часа\nЧем ты занимался большую часть времени?\nглубокая интеллектуальная работа; рутинные задачи; чтение; соцсети/YouTube; общение; прогулка/спорт; другое.",
    "4. Система вознаграждения\nЕсть ли сейчас ощущение, что сегодня уже удалось сделать что-то значимое?\nда; скорее да; скорее нет; нет совсем.",
    "5. Переключение внимания\nЕсли прямо сейчас открыть сложную задачу по программированию, насколько легко сможешь включиться? От 1 до 10.",
    "6. Уровень стресса\nЧто ближе?\nрасслаблен; немного напряжён; заметно тревожен; сильно перегружен мыслями.",
    "7. Физиология\nКогда ты последний раз: ел; пил воду; выходил на улицу; активно двигался хотя бы 10 минут?\nМожно ответить примерно.",
    "8. Любопытство\nЧто сейчас вызывает больше интереса?\nпрограммирование; политика/исследования; иностранные языки; книги; отдых; вообще ничего не хочется.",
    "9. Внешние обязательства\nЕсть ли сегодня задачи, которые обязательно нужно закончить до сна? Какие?",
    "10. Какое состояние хотелось бы получить?\nВыбери максимум два варианта: почувствовать прогресс; хорошо отдохнуть; получить ощущение контроля; чему-то научиться; завершить «висяки»; подготовиться к продуктивному завтра; просто расслабиться.",
    "11. Чередовать категории задач?\nда — чтобы не застревать в одном типе нагрузки; нет — чтобы дольше удерживать фокус.",
)


async def receive_day_state_long_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    answers = _state_answers(context)
    index = context.user_data.get("day_state_long_index", 0)
    text = (update.message.text or "").strip()
    if index == 0:
        value = _parse_scale(text)
        if value is None:
            await update.message.reply_text("Введите целое число от 1 до 10.")
            return AI_PLAN_LONG_QUESTION
        answers["brain_energy"] = value
    else:
        answer_key = f"q{index + 1}"
        answers[answer_key] = text
        if index == 1:
            normalized = text.lower()
            mapping = {"а": (3, 2), "б": (8, 7), "в": (8, 2), "г": (2, 8)}
            fatigue, physical = mapping.get(normalized[:1], (5, 5))
            answers["mental_fatigue"] = fatigue
            answers["physical_energy"] = physical
        elif index == 4:
            value = _parse_scale(text)
            answers["concentration"] = value if value is not None else 5
        elif index == 10:
            answers["alternate_categories"] = text.lower().startswith("д")
    index += 1
    context.user_data["day_state_long_index"] = index
    if index < len(LONG_QUESTIONS) + 1:
        await update.message.reply_text(LONG_QUESTIONS[index - 1])
        return AI_PLAN_LONG_QUESTION
    answers.setdefault("mental_fatigue", 5)
    answers.setdefault("physical_energy", 5)
    answers.setdefault("concentration", 5)
    await update.message.reply_text("Какой режим дня тебе нужен?", reply_markup=DAY_MODE_KEYBOARD)
    return AI_PLAN_DAY_MODE


async def receive_day_state_day_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    desired_mode = update.message.text or ""
    if desired_mode not in {"🛋 Восстановительный", "🌿 Спокойный", "⚖️ Сбалансированный", "🎯 Сфокусированный", "🚀 Проектный"}:
        await update.message.reply_text("Выберите один из предложенных режимов.", reply_markup=DAY_MODE_KEYBOARD)
        return AI_PLAN_DAY_MODE
    answers = _state_answers(context)
    answers["desired_day_mode"] = desired_mode
    recommendation = recommend_strategies(
        brain_energy=answers["brain_energy"], concentration=answers["concentration"],
        mental_fatigue=answers["mental_fatigue"], physical_energy=answers["physical_energy"],
        desired_day_mode=desired_mode, alternate_categories=answers.get("alternate_categories"),
    )
    context.user_data["day_state_recommendation"] = recommendation
    await update.message.reply_text(
        "Рекомендую две стратегии:\n"
        + "\n".join(f"• {item}" for item in recommendation.strategies)
        + f"\n\n{recommendation.explanation}\n\nМожно выбрать любую стратегию.",
        reply_markup=strategy_selection_keyboard(recommendation.strategies),
    )
    return AI_PLAN_STRATEGY


async def receive_day_state_strategy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.data is None:
        return ConversationHandler.END
    await query.answer()
    raw = query.data.removeprefix("daystrategy:")
    recommendation = context.user_data.get("day_state_recommendation")
    if raw in {"0", "1"} and recommendation is not None:
        strategy = recommendation.strategies[int(raw)]
    elif raw.isdigit() and 10 <= int(raw) < 10 + len(STRATEGIES):
        strategy = STRATEGIES[int(raw) - 10]
    else:
        await query.edit_message_text("Стратегия не найдена. Запустите /ai_plan заново.")
        return ConversationHandler.END
    _state_answers(context)["selected_strategy"] = strategy
    await query.edit_message_text(f"Выбрана стратегия: {strategy}\n\nПочему она сейчас подходит? Можно написать коротко или «—».")
    return AI_PLAN_STRATEGY_REASON


async def receive_day_state_strategy_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None or update.effective_user is None:
        return ConversationHandler.END
    raw_date = context.user_data.get("day_state_date")
    if not isinstance(raw_date, str):
        return ConversationHandler.END
    answers = _state_answers(context)
    recommendation = context.user_data.get("day_state_recommendation")
    plan_date = date.fromisoformat(raw_date)
    reason = (update.message.text or "").strip()
    profile = _task_service(context).save_day_state(
        update.effective_user.id, plan_date,
        survey_mode=context.user_data.get("day_state_mode", "short"),
        brain_energy=answers["brain_energy"], concentration=answers["concentration"],
        mental_fatigue=answers["mental_fatigue"], physical_energy=answers["physical_energy"],
        desired_day_mode=answers["desired_day_mode"], alternate_categories=answers.get("alternate_categories"),
        long_answers={key: value for key, value in answers.items() if key.startswith("q")},
        recommended_strategies=list(recommendation.strategies), selected_strategy=answers["selected_strategy"],
        strategy_reason=None if reason in {"", "—", "-"} else reason,
    )
    _clear_day_state(context)
    if profile is None:
        await update.message.reply_text("Не удалось сохранить состояние: план больше не существует.")
        return ConversationHandler.END
    context.user_data["ai_plan_agent_question_field"] = "day_goals"
    context.user_data["ai_plan_agent_question_date"] = plan_date.isoformat()
    await update.message.reply_text(
        "Какие главные цели дня? Выберите или напишите максимум две: прогресс, отдых, контроль, обучение, висяки, подготовка к завтра, расслабление.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return AI_PLAN_AGENT_QUESTION


async def _run_ai_plan(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_date: date) -> int:
    message = update.message or (update.callback_query.message if update.callback_query else None)
    if update.effective_user is None or message is None:
        return ConversationHandler.END
    schedule_context = _task_service(context).get_schedule_context(
        update.effective_user.id, plan_date
    )
    if schedule_context is None:
        await message.reply_text(f"На {plan_date} плана ещё нет.")
        return ConversationHandler.END
    if not schedule_context.tasks:
        await message.reply_text(f"На {plan_date} нет запланированных задач.")
        return ConversationHandler.END
    day_state = _task_service(context).get_day_state(update.effective_user.id, plan_date)
    try:
        agent_result = await asyncio.to_thread(
            _planning_agent_service(context).run,
            tasks=schedule_context.tasks,
            plan_date=plan_date,
            timezone=schedule_context.user.timezone,
            available_minutes=schedule_context.available_minutes,
            day_state=day_state,
            follow_up_answers=context.user_data.get("ai_plan_agent_answers") or {},
            history=_task_service(context).get_recent_plan_history(update.effective_user.id, plan_date),
            resume_from=context.user_data.get("ai_plan_resume_step"),
            memory=AgentMemory().read(),
        )
    except LLMProviderError as error:
        checkpoint_id = _task_service(context).save_planning_agent_checkpoint(
            update.effective_user.id, plan_date, failed_step="create_order",
            context={"follow_up_answers": context.user_data.get("ai_plan_agent_answers") or {}}, error=str(error)
        )
        await message.reply_text(
            "Не удалось получить AI-порядок: "
            f"{_format_ai_provider_error(error)} Ничего не изменено.",
            reply_markup=ai_plan_retry_keyboard(checkpoint_id) if checkpoint_id else None,
        )
        return ConversationHandler.END
    except ValueError as error:
        await message.reply_text(f"AI-порядок отклонён: {error}")
        return ConversationHandler.END
    if agent_result.question is not None:
        question = agent_result.question
        context.user_data["ai_plan_agent_question_field"] = question.field
        context.user_data["ai_plan_agent_question_date"] = plan_date.isoformat()
        _task_service(context).record_planning_agent_run(
            update.effective_user.id, plan_date, agent_result.trace
        )
        reply_markup = (
            ReplyKeyboardMarkup([question.options], one_time_keyboard=True, resize_keyboard=True)
            if question.options
            else ReplyKeyboardRemove()
        )
        await message.reply_text(question.question, reply_markup=reply_markup)
        return AI_PLAN_AGENT_QUESTION
    if agent_result.suggested_goal_tasks:
        context.user_data["ai_plan_goal_suggestions"] = agent_result.suggested_goal_tasks
        context.user_data["ai_plan_goal_suggestions_date"] = plan_date.isoformat()
        lines = ["Цель пока не покрыта задачами. Можно добавить:", ""]
        lines.extend(
            f"{index}. {item.title} — {item.estimated_minutes} мин"
            for index, item in enumerate(agent_result.suggested_goal_tasks, 1)
        )
        lines.append("\nВведите номера задач, которые добавить, например: 1, 3. Или «нет».")
        await message.reply_text("\n".join(lines))
        return AI_PLAN_GOAL_SUGGESTIONS
    proposal = agent_result.proposal
    if proposal is None:
        await message.reply_text("Агент не смог сформировать порядок задач. Запустите /ai_plan заново.")
        return ConversationHandler.END
    preview = calculate_schedule(
        proposal,
        plan_date=plan_date,
        timezone=schedule_context.user.timezone,
        available_minutes=schedule_context.available_minutes,
    )
    if not preview.slots:
        await _reply_text_in_chunks(
            message,
            _format_ai_plan_proposal(
                AIPlanProposal(ordered_tasks=[], deferred_tasks=preview.deferred_tasks),
                schedule_context.available_minutes,
            ),
        )
        return ConversationHandler.END
    original_proposal = agent_result.original_proposal
    reflection = agent_result.reflection
    if reflection is not None:
        context.user_data["ai_plan_reflection_id"] = _task_service(context).record_ai_reflection(
            update.effective_user.id,
            plan_date,
            original_task_ids=[task.id for task in original_proposal.ordered_tasks],
            reflected_task_ids=[task.id for task in proposal.ordered_tasks],
            is_acceptable=reflection.is_acceptable,
            observations=reflection.observations,
            user_message=reflection.user_message,
        )
        context.user_data["ai_plan_original_proposal"] = original_proposal
        context.user_data["ai_plan_reflection_choice"] = "reflected_applied"
    context.user_data["ai_plan_agent_trace"] = agent_result.trace
    context.user_data.pop("ai_plan_resume_step", None)
    _task_service(context).record_planning_agent_run(
        update.effective_user.id, plan_date, agent_result.trace
    )
    context.user_data["ai_plan_date"] = plan_date.isoformat()
    context.user_data["ai_plan_proposal"] = proposal
    # Let the user choose from every planned task, including those that do not
    # fit the first automatic preview. Capacity is checked after selection.
    context.user_data["ai_plan_selectable_ids"] = [task.id for task in proposal.ordered_tasks]
    reflection_text = _format_ai_reflection(reflection) if reflection is not None else ""
    insights_text = _format_agent_insights(agent_result.insights or [])
    await _reply_text_in_chunks(
        message,
        insights_text + reflection_text + _format_ai_plan_proposal(
            AIPlanProposal(
                ordered_tasks=[slot.task for slot in preview.slots],
                deferred_tasks=preview.deferred_tasks,
            ),
            schedule_context.available_minutes,
        ),
        reply_markup=ai_plan_actions_keyboard(has_reflection=reflection is not None),
    )
    return AI_PLAN_ACTION


async def receive_ai_plan_agent_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    answer = (update.message.text or "").strip()
    field = context.user_data.get("ai_plan_agent_question_field")
    raw_date = context.user_data.get("ai_plan_agent_question_date")
    if not answer or not isinstance(field, str) or not isinstance(raw_date, str):
        await update.message.reply_text("Ответьте на вопрос или отмените планирование через /cancel.")
        return AI_PLAN_AGENT_QUESTION
    answers = dict(context.user_data.get("ai_plan_agent_answers") or {})
    answers[field] = answer
    context.user_data["ai_plan_agent_answers"] = answers
    context.user_data.pop("ai_plan_agent_question_field", None)
    context.user_data.pop("ai_plan_agent_question_date", None)
    if field == "day_goals":
        context.user_data["ai_plan_agent_question_field"] = "unlisted_obligations"
        context.user_data["ai_plan_agent_question_date"] = raw_date
        await update.message.reply_text(
            "Есть ли сегодня обязательные задачи или события, которых нет в списке? Если нет — напишите «нет»."
        )
        return AI_PLAN_AGENT_QUESTION
    if field.startswith("fixed_constraint_"):
        parsed = _parse_fixed_time_answer(answer)
        if parsed is not None:
            task_id = int(field.removeprefix("fixed_constraint_"))
            context.user_data["ai_plan_fixed_time"] = (task_id, parsed[0].isoformat(), parsed[1], raw_date)
            await update.message.reply_text(
                f"Учесть {parsed[0].strftime('%H:%M')} на {parsed[1]} мин. Сохранить это время в задачу?",
                reply_markup=save_fixed_time_keyboard(),
            )
            return AI_PLAN_FIXED_TIME_SAVE
    return await _run_ai_plan(update, context, date.fromisoformat(raw_date))


async def receive_ai_plan_goal_suggestions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None or update.effective_user is None:
        return ConversationHandler.END
    suggestions = context.user_data.get("ai_plan_goal_suggestions") or []
    raw_date = context.user_data.get("ai_plan_goal_suggestions_date")
    if not isinstance(raw_date, str) or not suggestions:
        return ConversationHandler.END
    if (update.message.text or "").strip().casefold() in {"нет", "no"}:
        context.user_data.pop("ai_plan_goal_suggestions", None)
        answers = dict(context.user_data.get("ai_plan_agent_answers") or {})
        answers["goal_task_choice_made"] = "no"
        context.user_data["ai_plan_agent_answers"] = answers
        return await _run_ai_plan(update, context, date.fromisoformat(raw_date))
    indexes = _parse_task_indexes(update.message.text or "", maximum=len(suggestions))
    if indexes is None:
        await update.message.reply_text("Введите номера через запятую, например: 1, 3. Или «нет».")
        return AI_PLAN_GOAL_SUGGESTIONS
    plan = _planning_service(context).get_plan_for_date(update.effective_user.id, date.fromisoformat(raw_date))
    if plan is None:
        return ConversationHandler.END
    drafts = [TaskDraft(text=suggestions[index - 1].title, estimated_minutes=suggestions[index - 1].estimated_minutes) for index in indexes]
    _planning_service(context).create_plan(update.effective_user.id, date.fromisoformat(raw_date), plan.day_type, drafts)
    answers = dict(context.user_data.get("ai_plan_agent_answers") or {})
    answers["goal_task_choice_made"] = "yes"
    context.user_data["ai_plan_agent_answers"] = answers
    context.user_data.pop("ai_plan_goal_suggestions", None)
    context.user_data.pop("ai_plan_goal_suggestions_date", None)
    return await _run_ai_plan(update, context, date.fromisoformat(raw_date))


def _parse_fixed_time_answer(answer: str):
    from datetime import time

    match = re.search(r"\b(\d{1,2}):(\d{2})\b", answer)
    if match is None:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    duration_match = re.search(r"\b(\d+)\s*(?:мин|м\b)", answer.casefold())
    hours_match = re.search(r"\b(\d+)\s*ч", answer.casefold())
    duration = int(duration_match.group(1)) if duration_match else (int(hours_match.group(1)) * 60 if hours_match else 60)
    return time(hour, minute), duration


async def receive_fixed_time_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    stored = context.user_data.pop("ai_plan_fixed_time", None)
    if query is None or query.data is None or update.effective_user is None or not stored:
        return ConversationHandler.END
    await query.answer()
    task_id, time_raw, duration, raw_date = stored
    if query.data == "fixedtime:save":
        from app.services.task_input_parser import TaskUpdate
        from datetime import time

        parsed_time = time.fromisoformat(time_raw)
        _task_service(context).update_task(
            task_id, telegram_id=update.effective_user.id,
            update=TaskUpdate(frozenset({"время начала", "длительность"}), start_time=parsed_time, estimated_minutes=duration),
        )
    await query.edit_message_text("Продолжаю составление плана.")
    return await _run_ai_plan(update, context, date.fromisoformat(raw_date))


async def retry_ai_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return
    await query.answer()
    raw_id = query.data.removeprefix("aiplanretry:")
    if not raw_id.isdigit():
        return
    checkpoint = _task_service(context).consume_planning_agent_checkpoint(
        update.effective_user.id, int(raw_id)
    )
    if checkpoint is None:
        await query.edit_message_text("Этот повтор уже использован или больше недоступен.")
        return
    context.user_data["ai_plan_agent_answers"] = checkpoint["context"].get("follow_up_answers", {})
    context.user_data["ai_plan_resume_step"] = checkpoint["failed_step"]
    await query.edit_message_text("Повторяю шаг построения AI-плана…")
    await _run_ai_plan(update, context, checkpoint["plan_date"])


async def plan_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text(
            "Формат: /plan_feedback Что в плане не учтено или что нужно изменить."
        )
        return
    plan_date = date.today()
    if not _task_service(context).save_plan_feedback(update.effective_user.id, plan_date, text):
        await update.message.reply_text("На сегодня нет плана, к которому можно добавить обратную связь.")
        return
    AgentMemory().append_feedback(plan_date=plan_date, text=text)
    await update.message.reply_text(
        "Обратная связь сохранена. Текущее расписание помечено устаревшим. "
        "Запустите /ai_plan, чтобы агент пересобрал план с учётом комментария."
    )


async def agent_memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    memory = AgentMemory().read()
    if not memory:
        await update.message.reply_text("Память агента пока пуста.")
        return
    await _reply_text_in_chunks(update.message, "🧠 Память агента\n\n" + memory)


async def receive_ai_plan_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return ConversationHandler.END
    await query.answer()
    proposal = context.user_data.get("ai_plan_proposal")
    if not isinstance(proposal, AIPlanProposal):
        await query.edit_message_text("Предложение устарело. Запустите /ai_plan заново.")
        return ConversationHandler.END
    action = query.data.removeprefix("aiplan:")
    if action == "cancel":
        raw_date = context.user_data.get("ai_plan_date")
        if isinstance(raw_date, str):
            _task_service(context).decide_ai_reflection(
                update.effective_user.id, date.fromisoformat(raw_date),
                context.user_data.get("ai_plan_reflection_id"), "dismissed"
            )
        _clear_ai_plan(context)
        await query.edit_message_text("Текущий порядок оставлен без изменений.")
        return ConversationHandler.END
    if action == "feedback":
        await query.edit_message_text("Что в этом плане не учтено? Напишите одним сообщением.")
        return AI_PLAN_FEEDBACK
    if action == "apply_original":
        original = context.user_data.get("ai_plan_original_proposal")
        if not isinstance(original, AIPlanProposal):
            await query.edit_message_text("Исходный вариант больше недоступен. Запустите /ai_plan заново.")
            return ConversationHandler.END
        proposal = original
        context.user_data["ai_plan_proposal"] = proposal
        context.user_data["ai_plan_reflection_choice"] = "original_applied"
        context.user_data["ai_plan_selectable_ids"] = [task.id for task in proposal.ordered_tasks]
    elif action == "apply_reflected":
        context.user_data["ai_plan_reflection_choice"] = "reflected_applied"
    if action == "select":
        selectable_tasks = [
            task
            for task in proposal.ordered_tasks
            if task.id in set(context.user_data.get("ai_plan_selectable_ids") or [])
        ]
        if not selectable_tasks:
            await query.edit_message_text("В предложении нет задач для расписания.")
            return ConversationHandler.END
        await query.edit_message_text(
            "Выберите номера задач, которые нужно включить в расписание. "
            "Порядок сохранится:\n\n"
            + "\n".join(
                f"{index}. {task.text}" for index, task in enumerate(selectable_tasks, 1)
            )
            + "\n\nВведите номера через запятую, например: 1, 3, 4."
        )
        return AI_PLAN_SELECT
    selected_tasks = [
        task
        for task in proposal.ordered_tasks
        if task.id in set(context.user_data.get("ai_plan_selectable_ids") or [])
    ]
    return await _apply_ai_plan(update, context, selected_tasks, query=query)


async def receive_ai_plan_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None or update.effective_user is None:
        return ConversationHandler.END
    proposal = context.user_data.get("ai_plan_proposal")
    if not isinstance(proposal, AIPlanProposal):
        await update.message.reply_text("Предложение устарело. Запустите /ai_plan заново.")
        return ConversationHandler.END
    selectable_tasks = [
        task
        for task in proposal.ordered_tasks
        if task.id in set(context.user_data.get("ai_plan_selectable_ids") or [])
    ]
    indexes = _parse_task_indexes(update.message.text or "", maximum=len(selectable_tasks))
    if indexes is None:
        await update.message.reply_text("Введите номера задач через запятую, например: 1, 3, 4.")
        return AI_PLAN_SELECT
    selected = [selectable_tasks[index - 1] for index in indexes]
    return await _apply_ai_plan(update, context, selected)


async def receive_ai_plan_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None or update.effective_user is None:
        return ConversationHandler.END
    text = (update.message.text or "").strip()
    raw_date = context.user_data.get("ai_plan_date")
    if not text or not isinstance(raw_date, str):
        await update.message.reply_text("Напишите, что нужно изменить в плане.")
        return AI_PLAN_FEEDBACK
    plan_date = date.fromisoformat(raw_date)
    _task_service(context).save_plan_feedback(update.effective_user.id, plan_date, text)
    AgentMemory().append_feedback(plan_date=plan_date, text=text)
    _clear_ai_plan(context)
    await update.message.reply_text(
        "Обратная связь сохранена. Запустите /ai_plan: агент учтёт её при новой сборке."
    )
    return ConversationHandler.END


async def _apply_ai_plan(update: Update, context: ContextTypes.DEFAULT_TYPE, selected_tasks, *, query=None) -> int:
    user = update.effective_user
    if user is None:
        return ConversationHandler.END
    proposal = context.user_data.get("ai_plan_proposal")
    plan_date_raw = context.user_data.get("ai_plan_date")
    if not isinstance(proposal, AIPlanProposal) or not isinstance(plan_date_raw, str):
        return ConversationHandler.END
    plan_date = date.fromisoformat(plan_date_raw)
    schedule_context = _task_service(context).get_schedule_context(user.id, plan_date)
    if schedule_context is None:
        return await _reply_ai_plan_result(update, query, "План больше не существует.")
    expected_ids = {task.id for task in proposal.ordered_tasks} | {
        task.id for task, _ in proposal.deferred_tasks
    }
    if expected_ids != {task.id for task in schedule_context.tasks}:
        _clear_ai_plan(context)
        return await _reply_ai_plan_result(
            update, query, "Список задач изменился. Запустите /ai_plan заново."
        )
    selected_ids = {task.id for task in selected_tasks}
    reduced_proposal = AIPlanProposal(
        ordered_tasks=list(selected_tasks),
        deferred_tasks=[
            *proposal.deferred_tasks,
            *[
                (task, "Не выбрана пользователем для этого расписания.")
                for task in proposal.ordered_tasks
                if task.id not in selected_ids
            ],
        ],
    )
    schedule = calculate_schedule(
        reduced_proposal,
        plan_date=plan_date,
        timezone=schedule_context.user.timezone,
        available_minutes=schedule_context.available_minutes,
    )
    if not schedule.slots:
        return await _reply_ai_plan_result(
            update, query, "Не удалось разместить ни одной задачи в доступное время."
        )
    try:
        active = _task_service(context).apply_ai_schedule(user.id, plan_date, schedule.slots)
    except ValueError as error:
        _clear_ai_plan(context)
        return await _reply_ai_plan_result(update, query, str(error))
    _task_service(context).decide_ai_reflection(
        user.id, plan_date, context.user_data.get("ai_plan_reflection_id"),
        context.user_data.get("ai_plan_reflection_choice", "reflected_applied"),
    )
    _clear_ai_plan(context)
    assert active is not None
    return await _reply_ai_plan_result(
        update,
        query,
        _format_active_schedule(plan_date, active.slots, schedule.deferred_tasks),
    )


async def _reply_ai_plan_result(update: Update, query, text: str) -> int:
    if query is not None:
        await query.edit_message_text(text)
    elif update.message is not None:
        await update.message.reply_text(text)
    return ConversationHandler.END


async def ai_plan_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    if len(context.args) > 1:
        await update.message.reply_text("Формат: /ai_plan_view [today|YYYY-MM-DD]")
        return
    plan_date = (
        _parse_plan_date(context.args[0], allow_past=True) if context.args else date.today()
    )
    if plan_date is None:
        await update.message.reply_text("Укажите дату: today, tomorrow или YYYY-MM-DD.")
        return
    active = _task_service(context).get_active_schedule(update.effective_user.id, plan_date)
    if active is None:
        await update.message.reply_text(f"На {plan_date} нет активного AI-расписания.")
        return
    await _reply_text_in_chunks(
        update.message, _format_active_schedule(plan_date, active.slots, [])
    )


async def evening_reflection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None or update.effective_user is None:
        return ConversationHandler.END
    plan_date = date.today()
    task_service = _task_service(context)
    schedule_context = task_service.get_schedule_context(update.effective_user.id, plan_date)
    if schedule_context is None:
        await update.message.reply_text("На сегодня ещё нет плана, поэтому разбирать пока нечего.")
        return ConversationHandler.END
    draft = task_service.get_pending_evening_reflection(update.effective_user.id, plan_date)
    if draft is None:
        await update.message.reply_text(
            "Готовлю десять вопросов для вечерней рефлексии. Это займёт около 20 секунд."
        )
        generated = await asyncio.to_thread(
            _evening_reflection_service(context).create_questions,
            task_service.get_visible_tasks_for_date(update.effective_user.id, plan_date),
            task_service.get_day_state(update.effective_user.id, plan_date),
        )
        draft = task_service.create_evening_reflection(
            update.effective_user.id, plan_date, questions=generated.questions, source=generated.source
        )
    if draft is None:
        await update.message.reply_text("Не удалось сохранить вечернюю рефлексию. Попробуйте ещё раз.")
        return ConversationHandler.END
    context.user_data["evening_reflection_id"] = draft.id
    context.user_data["evening_reflection_questions"] = draft.questions
    index = len(draft.answers)
    if index >= len(draft.questions):
        await update.message.reply_text("Вечерняя рефлексия на сегодня уже завершена.")
        _clear_evening_reflection(context)
        return ConversationHandler.END
    await update.message.reply_text(
        f"🌙 Вечерняя рефлексия ({index + 1}/10)\n\n{draft.questions[index]}\n\nОтветьте в свободной форме."
    )
    return EVENING_REFLECTION_ANSWER


async def category_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    args = list(context.args)
    if not args:
        await update.message.reply_text(
            "Формат: /category <категория>.\nПример: /category Бот"
        )
        return
    category = " ".join(args).strip()
    if not category:
        await update.message.reply_text("Укажите категорию, например: /category Бот.")
        return
    today = date.today()
    start_date = today
    end_date = today + timedelta(days=2)
    results = _task_service(context).get_planned_tasks_by_category(
        update.effective_user.id, category, start_date, end_date
    )
    if not results:
        await update.message.reply_text(
            f"Нет запланированных задач категории «{category}» с {start_date} по {end_date}."
        )
        return
    lines = [f"🏷 Категория: {category}", ""]
    current_date = None
    for task, plan_date in results:
        if plan_date != current_date:
            current_date = plan_date
            lines.extend([f"{plan_date}:"])
        time_label = f" — {task.starts_at.strftime('%H:%M')}" if task.starts_at else ""
        lines.append(f"• {task.text}{time_label}")
    await _reply_text_in_chunks(update.message, "\n".join(lines))


async def receive_evening_reflection_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    answer = (update.message.text or "").strip()
    reflection_id = context.user_data.get("evening_reflection_id")
    questions = context.user_data.get("evening_reflection_questions")
    if not isinstance(reflection_id, int) or not isinstance(questions, list):
        await update.message.reply_text("Рефлексия устарела. Запустите /evening_reflection заново.")
        return ConversationHandler.END
    if not answer:
        await update.message.reply_text("Напишите ответ или используйте /cancel, чтобы продолжить позже.")
        return EVENING_REFLECTION_ANSWER
    stored = _task_service(context).answer_evening_reflection(reflection_id, answer)
    if stored is None:
        _clear_evening_reflection(context)
        await update.message.reply_text("Рефлексия больше недоступна. Запустите /evening_reflection заново.")
        return ConversationHandler.END
    index = len(stored.answers)
    if stored.status == "completed":
        _clear_evening_reflection(context)
        await update.message.reply_text(
            "🌙 Рефлексия сохранена. Спасибо — эти ответы можно использовать для будущей персонализации."
        )
        return ConversationHandler.END
    await update.message.reply_text(
        f"{index + 1}/10\n\n{questions[index]}\n\nОтветьте в свободной форме."
    )
    return EVENING_REFLECTION_ANSWER


def _clear_ai_plan(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("ai_plan_date", None)
    context.user_data.pop("ai_plan_proposal", None)
    context.user_data.pop("ai_plan_selectable_ids", None)
    context.user_data.pop("ai_plan_original_proposal", None)
    context.user_data.pop("ai_plan_reflection_id", None)
    context.user_data.pop("ai_plan_reflection_choice", None)
    context.user_data.pop("ai_plan_agent_answers", None)
    context.user_data.pop("ai_plan_agent_question_field", None)
    context.user_data.pop("ai_plan_agent_question_date", None)


def _clear_day_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (
        "day_state_date", "day_state_answers", "day_state_mode",
        "day_state_long_index", "day_state_recommendation",
    ):
        context.user_data.pop(key, None)


def _clear_evening_reflection(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("evening_reflection_id", None)
    context.user_data.pop("evening_reflection_questions", None)


def _format_ai_plan_proposal(proposal: AIPlanProposal, available_minutes: int) -> str:
    lines = ["🤖 Предлагаемый порядок", f"Доступно: {_format_minutes(available_minutes)}", ""]
    if proposal.ordered_tasks:
        lines.extend(
            f"{index}. {task.text} — {_format_minutes(task.estimated_minutes)}"
            for index, task in enumerate(proposal.ordered_tasks, 1)
        )
    if proposal.deferred_tasks:
        lines.extend(["", "Перенести:"])
        lines.extend(f"• {task.text} — {reason}" for task, reason in proposal.deferred_tasks)
    return "\n".join(lines)


def _format_ai_reflection(reflection) -> str:
    lines = ["🔎 Проверка плана", reflection.user_message]
    if reflection.observations:
        lines.extend(["", "Замечания:", *[f"• {item}" for item in reflection.observations]])
    if not reflection.is_acceptable:
        lines.extend(["", "Можно применить улучшенный вариант или оставить исходный."])
    return "\n".join(lines) + "\n\n"


def _format_agent_insights(insights: list[str]) -> str:
    if not insights:
        return ""
    return "🤖 Наблюдения агента\n" + "\n".join(f"• {item}" for item in insights) + "\n\n"


def _format_active_schedule(plan_date: date, slots, deferred_tasks) -> str:
    lines = [f"🗓 Расписание на {plan_date}", ""]
    for slot, task in slots:
        lines.append(
            f"{slot.position}. {slot.starts_at:%H:%M}–{slot.ends_at:%H:%M} {task.text}"
            + (f" · перерыв {slot.buffer_after_minutes} мин" if slot.buffer_after_minutes else "")
        )
    if deferred_tasks:
        lines.extend(["", "Не включены:"])
        lines.extend(f"• {task.text} — {reason}" for task, reason in deferred_tasks)
    return "\n".join(lines)


async def _run_ai_estimate(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_date: date) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    tasks = [
        task
        for task in _task_service(context).get_visible_tasks_for_date(
            update.effective_user.id, plan_date
        )
        if task.status == TaskStatus.planned
    ]
    if not tasks:
        await update.message.reply_text(f"На {plan_date} нет активных задач.")
        return ConversationHandler.END
    saved = _task_service(context).get_ai_estimate_draft(update.effective_user.id, plan_date)
    if saved is not None:
        draft_id, estimates = saved
        _store_ai_estimate(context, plan_date, estimates, draft_id)
        await update.message.reply_text(
            "Для этой даты есть сохранённые AI-предложения. "
            "Откройте их или создайте новую оценку.",
            reply_markup=ai_estimate_draft_keyboard(),
        )
        return AI_ACTION
    try:
        estimates = await asyncio.to_thread(_ai_estimation_service(context).estimate, tasks)
    except LLMProviderError as error:
        await update.message.reply_text(
            "Не удалось получить AI-оценку: "
            f"{_format_ai_provider_error(error)} Изменения не применены."
        )
        return ConversationHandler.END
    except ValueError as error:
        await update.message.reply_text(f"AI-оценка отклонена: {error}")
        return ConversationHandler.END
    draft_id = _task_service(context).save_ai_estimate_draft(
        update.effective_user.id, plan_date, estimates
    )
    _store_ai_estimate(context, plan_date, estimates, draft_id)
    await update.message.reply_text(
        _format_ai_estimate_summary(estimates),
        reply_markup=ai_estimate_actions_keyboard(),
    )
    return AI_ACTION


async def receive_ai_estimate_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return ConversationHandler.END
    await query.answer()
    estimates = list(context.user_data.get("ai_estimates") or [])
    if not estimates:
        await query.edit_message_text("AI-оценка устарела. Запустите /ai_estimate заново.")
        return ConversationHandler.END
    if not _task_service(context).is_ai_estimate_draft_active(
        update.effective_user.id, context.user_data.get("ai_estimate_draft_id")
    ):
        _clear_ai_estimate(context)
        await query.edit_message_text("Черновик устарел. Запустите /ai_estimate заново.")
        return ConversationHandler.END
    action = query.data.removeprefix("aiest:")
    if action == "cancel":
        _clear_ai_estimate(context)
        await query.edit_message_text(
            "Предложения сохранены. Чтобы вернуться к ним, запустите /ai_estimate для этой даты."
        )
        return ConversationHandler.END
    if action == "open":
        await query.edit_message_text(
            _format_ai_estimate_summary(estimates),
            reply_markup=ai_estimate_actions_keyboard(),
        )
        return AI_ACTION
    if action == "new":
        plan_date_raw = context.user_data.get("ai_estimate_date")
        if not plan_date_raw:
            await query.edit_message_text("Дата оценки потеряна. Запустите /ai_estimate заново.")
            return ConversationHandler.END
        plan_date = date.fromisoformat(plan_date_raw)
        tasks = [
            task
            for task in _task_service(context).get_visible_tasks_for_date(
                update.effective_user.id, plan_date
            )
            if task.status == TaskStatus.planned
        ]
        if not tasks:
            await query.edit_message_text("На эту дату нет активных задач.")
            return ConversationHandler.END
        await query.edit_message_text("Создаю новую AI-оценку.")
        try:
            estimates = await asyncio.to_thread(_ai_estimation_service(context).estimate, tasks)
        except LLMProviderError as error:
            await query.edit_message_text(
                "Не удалось получить AI-оценку: "
                f"{_format_ai_provider_error(error)} Черновик сохранён."
            )
            return ConversationHandler.END
        except ValueError as error:
            await query.edit_message_text(f"AI-оценка отклонена: {error}")
            return ConversationHandler.END
        draft_id = _task_service(context).save_ai_estimate_draft(
            update.effective_user.id, plan_date, estimates
        )
        _store_ai_estimate(context, plan_date, estimates, draft_id)
        await query.edit_message_text(
            _format_ai_estimate_summary(estimates),
            reply_markup=ai_estimate_actions_keyboard(),
        )
        return AI_ACTION
    if action == "all":
        updated = _task_service(context).apply_ai_estimates(
            update.effective_user.id,
            estimates,
            {estimate.task.id for estimate in estimates},
        )
        _task_service(context).mark_ai_estimate_draft_applied(
            update.effective_user.id, context.user_data.get("ai_estimate_draft_id")
        )
        _clear_ai_estimate(context)
        await query.edit_message_text(f"Применено AI-изменений: {len(updated)}.")
        return ConversationHandler.END
    if action == "view":
        overview_parts = _format_ai_estimate_overview(estimates)
        await query.edit_message_text(
            overview_parts[0], reply_markup=ai_estimate_actions_keyboard()
        )
        if query.message is not None:
            for part in overview_parts[1:]:
                await query.message.reply_text(part)
        return AI_ACTION
    if action == "select":
        await query.edit_message_text(
            "Выберите задачу, чтобы посмотреть предложение и подтвердить допустимые изменения:",
            reply_markup=ai_estimate_task_keyboard(estimates),
        )
        return AI_TASK
    return AI_ACTION


async def receive_ai_estimate_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return ConversationHandler.END
    await query.answer()
    estimates = {estimate.task.id: estimate for estimate in context.user_data.get("ai_estimates") or []}
    if not _task_service(context).is_ai_estimate_draft_active(
        update.effective_user.id, context.user_data.get("ai_estimate_draft_id")
    ):
        _clear_ai_estimate(context)
        await query.edit_message_text("Черновик устарел. Запустите /ai_estimate заново.")
        return ConversationHandler.END
    parts = query.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit() or int(parts[2]) not in estimates:
        await query.edit_message_text("Предложение устарело. Запустите /ai_estimate заново.")
        return ConversationHandler.END
    action, task_id = parts[1], int(parts[2])
    estimate = estimates[task_id]
    if action == "apply":
        updated = _task_service(context).apply_ai_estimates(
            update.effective_user.id, [estimate], {task_id}
        )
        _task_service(context).decide_ai_estimate_item(
            update.effective_user.id,
            context.user_data.get("ai_estimate_draft_id"),
            task_id,
            "applied",
        )
        context.user_data["ai_estimates"] = [
            candidate
            for candidate in context.user_data.get("ai_estimates") or []
            if candidate.task.id != task_id
        ]
        await query.edit_message_text(
            f"Применено изменений: {len(updated)}. Остальные предложения сохранены.",
            reply_markup=ai_estimate_actions_keyboard(),
        )
        return AI_ACTION
    if action == "dismiss":
        _task_service(context).decide_ai_estimate_item(
            update.effective_user.id,
            context.user_data.get("ai_estimate_draft_id"),
            task_id,
            "dismissed",
        )
        context.user_data["ai_estimates"] = [
            candidate
            for candidate in context.user_data.get("ai_estimates") or []
            if candidate.task.id != task_id
        ]
        await query.edit_message_text(
            "Предложение отклонено. Задача не изменена.",
            reply_markup=ai_estimate_actions_keyboard(),
        )
        return AI_ACTION
    if action == "skip":
        await query.edit_message_text(
            "Решение не принято. Предложение сохранено.",
            reply_markup=ai_estimate_actions_keyboard(),
        )
        return AI_ACTION
    if action == "task":
        buttons = [
            [InlineKeyboardButton("Применить допустимое", callback_data=f"aiest:apply:{task_id}")],
            [InlineKeyboardButton("Отклонить предложение", callback_data=f"aiest:dismiss:{task_id}")],
            [InlineKeyboardButton("Назад без решения", callback_data=f"aiest:skip:{task_id}")],
        ]
        await query.edit_message_text(
            _format_ai_estimate_detail(estimate),
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    return AI_TASK


def _clear_ai_estimate(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("ai_estimates", None)
    context.user_data.pop("ai_estimate_date", None)
    context.user_data.pop("ai_estimate_draft_id", None)


def _store_ai_estimate(context: ContextTypes.DEFAULT_TYPE, plan_date: date, estimates, draft_id: int | None) -> None:
    context.user_data["ai_estimates"] = estimates
    context.user_data["ai_estimate_date"] = plan_date.isoformat()
    context.user_data["ai_estimate_draft_id"] = draft_id


def _format_ai_estimate_summary(estimates) -> str:
    changes = [estimate.applicable_changes for estimate in estimates]
    return (
        "🤖 AI-оценка задач\n\nПредлагается изменить:\n"
        f"• важность — {sum('priority' in change for change in changes)} задач;\n"
        f"• сложность — {sum('effort' in change for change in changes)} задач;\n"
        f"• длительность — {sum('estimated_minutes' in change for change in changes)} задач."
    )


def _format_ai_estimate_overview(estimates) -> list[str]:
    pending = [estimate for estimate in estimates if estimate.applicable_changes]
    if not pending:
        return ["🤖 Нерассмотренных AI-предложений не осталось."]

    entries = []
    for estimate in pending:
        task, proposal = estimate.task, estimate.proposal
        changes = estimate.applicable_changes
        values = []
        if "priority" in changes:
            values.append(f"важность {task.priority} → {proposal.priority}")
        if "effort" in changes:
            values.append(f"сложность {task.effort} → {proposal.effort}")
        if "estimated_minutes" in changes:
            values.append(
                f"длительность {task.estimated_minutes} → {proposal.estimated_minutes} мин"
            )
        entries.append(f"• {task.text}\n  " + " · ".join(values))

    chunks = [f"🤖 Нерассмотренные AI-предложения: {len(entries)}\n"]
    for entry in entries:
        candidate = f"{chunks[-1]}\n{entry}"
        if len(candidate) > 3_700:
            chunks.append(entry)
        else:
            chunks[-1] = candidate
    return chunks


def _format_ai_provider_error(error: LLMProviderError) -> str:
    if "empty response" in str(error):
        return "модель вернула пустой ответ."
    if "timed out" in str(error):
        return "превышено время ожидания ответа."
    if "HTTP 429" in str(error):
        return "бесплатный маршрут временно ограничил число запросов."
    if "HTTP" in str(error):
        return "провайдер вернул временную HTTP-ошибку."
    return "провайдер временно недоступен или не поддерживает требуемый JSON-формат."


def _format_ai_estimate_detail(estimate) -> str:
    task, proposal = estimate.task, estimate.proposal
    protected = []
    if task.priority_source == "user":
        protected.append("важность")
    if task.effort_source == "user":
        protected.append("сложность")
    if task.duration_source == "user":
        protected.append("длительность")
    lines = [
        f"{task.text}\n",
        f"Важность: {task.priority} → {proposal.priority} (уверенность {proposal.priority_confidence:.0%})",
        f"Сложность: {task.effort} → {proposal.effort} (уверенность {proposal.effort_confidence:.0%})",
        f"Длительность: {task.estimated_minutes} → {proposal.estimated_minutes} мин (уверенность {proposal.duration_confidence:.0%})",
        f"Причина: {proposal.explanation}",
    ]
    if protected:
        lines.append("Пользовательские значения не будут заменены: " + ", ".join(protected) + ".")
    if proposal.missing_data:
        lines.append("Не хватает данных: " + "; ".join(proposal.missing_data))
    return "\n".join(lines)


async def idea(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    await update.message.reply_text("Введите идеи: по одной в строке.")
    return IDEA_TEXT


async def receive_idea(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    try:
        saved_ideas = _capture_service(context).add_ideas(
            update.effective_user.id,
            (update.message.text or "").splitlines(),
        )
    except ValueError as error:
        await update.message.reply_text(str(error))
        return IDEA_TEXT
    await update.message.reply_text(f"Сохранено идей: {len(saved_ideas)}.")
    return ConversationHandler.END


async def ideas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    saved_ideas = _capture_service(context).list_ideas(update.effective_user.id)
    if not saved_ideas:
        await update.message.reply_text("Идей пока нет. Используйте /idea.")
        return
    await update.message.reply_text(
        "Идеи:\n" + "\n".join(f"{index}. {idea.text}" for index, idea in enumerate(saved_ideas, 1))
    )


async def inbox(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    await update.message.reply_text(
        "Введите задачу без даты. Можно указать длительность, важность, сложность и контекст."
    )
    return INBOX_TEXT


async def receive_inbox_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    try:
        task = parse_task_lines([(update.message.text or "")])[0]
        saved_task = _capture_service(context).add_unscheduled_task(
            update.effective_user.id,
            task,
        )
    except (TaskInputError, ValueError, IndexError) as error:
        await update.message.reply_text(str(error) or "Введите непустую задачу.")
        return INBOX_TEXT
    await update.message.reply_text(f"Задача без даты сохранена: {saved_task.text}")
    return ConversationHandler.END


async def backlog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    tasks = _capture_service(context).list_unscheduled_tasks(update.effective_user.id)
    if not tasks:
        await update.message.reply_text("Задач без даты пока нет. Используйте /inbox.")
        return
    await update.message.reply_text(
        "Задачи без даты:\n" + _format_unscheduled_tasks(tasks)
    )


async def upcoming(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    result = _capture_service(context).get_upcoming_tasks(update.effective_user.id)
    if not result.dated_tasks and not result.unscheduled_tasks:
        await update.message.reply_text("Будущих задач и задач без даты пока нет.")
        return
    lines = ["Ближайшие задачи:"]
    current_date = None
    for task, plan_date in result.dated_tasks:
        if plan_date != current_date:
            lines.append(f"\n{plan_date}:")
            current_date = plan_date
        lines.append(f"- {task.text}")
    if result.unscheduled_tasks:
        lines.append("\nБез даты:")
        lines.extend(f"- {task.text}" for task in result.unscheduled_tasks)
    if result.unscheduled_remaining:
        lines.append(
            f"\nБез даты не вошло: {result.unscheduled_remaining}. Полный список: /backlog."
        )
    await update.message.reply_text("\n".join(lines))


async def schedule_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    tasks = _capture_service(context).list_unscheduled_tasks(update.effective_user.id)
    saved_ideas = _capture_service(context).list_ideas(update.effective_user.id)
    if not tasks and not saved_ideas:
        await update.message.reply_text("Нет идей или задач без даты для планирования.")
        return ConversationHandler.END
    await update.message.reply_text(
        "Выберите идею или задачу без даты:",
        reply_markup=schedule_source_keyboard(tasks, saved_ideas),
    )
    return SCHEDULE_SELECT


async def receive_schedule_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.data is None:
        return ConversationHandler.END
    parts = query.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return ConversationHandler.END
    await query.answer()
    context.user_data["schedule_source_type"] = parts[1]
    context.user_data["schedule_source_id"] = int(parts[2])
    await query.edit_message_text(
        "На какую дату назначить? Выберите «Сегодня», «Завтра» или введите YYYY-MM-DD.",
    )
    return SCHEDULE_DATE


async def receive_schedule_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    target_date = _parse_plan_date(update.message.text or "")
    if target_date is None:
        await update.message.reply_text("Введите «Сегодня», «Завтра» или будущую дату YYYY-MM-DD.")
        return SCHEDULE_DATE
    source_type = context.user_data.get("schedule_source_type")
    source_id = context.user_data.get("schedule_source_id")
    if source_type not in {"task", "idea"} or not isinstance(source_id, int):
        await update.message.reply_text("Выберите запись заново через /schedule_task.")
        return ConversationHandler.END
    service = _capture_service(context)
    task = (
        service.schedule_unscheduled_task(source_id, telegram_id=update.effective_user.id, target_date=target_date)
        if source_type == "task"
        else service.schedule_idea(source_id, telegram_id=update.effective_user.id, target_date=target_date)
    )
    context.user_data.pop("schedule_source_type", None)
    context.user_data.pop("schedule_source_id", None)
    if task is None:
        await update.message.reply_text("Запись не найдена или уже была запланирована.")
        return ConversationHandler.END
    await update.message.reply_text(f"Задача назначена на {target_date}: {task.text}")
    return ConversationHandler.END


async def _move_feasibility_tasks_to_tomorrow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    task_ids: list[int],
) -> int:
    user = update.effective_user
    if user is None:
        return ConversationHandler.END
    result = await _move_with_repeat_confirmation(
        update, context, task_ids=task_ids, target_date=date.today() + timedelta(days=1)
    )
    if result == ConversationHandler.END:
        _clear_feasibility_move_data(context)
    return result


async def _move_with_repeat_confirmation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    task_ids: list[int],
    target_date: date,
    known_tasks=None,
) -> int:
    user = update.effective_user
    if user is None:
        return ConversationHandler.END
    tasks_by_id = {task.id: task for task in known_tasks or []}
    repeated = []
    ordinary_ids = []
    for task_id in task_ids:
        task = tasks_by_id.get(task_id)
        if task is None:
            details = _task_service(context).get_task_details(task_id, user.id)
            task = details.task if details is not None else None
        if task is None or task.status != TaskStatus.planned:
            continue
        if task.postponement_count >= 2:
            repeated.append(task)
        else:
            ordinary_ids.append(task_id)
    moved_count = len(
        _task_service(context).move_tasks(ordinary_ids, telegram_id=user.id, target_date=target_date)
    )
    if not repeated:
        await _reply_move_text(update, f"Перенесено задач: {moved_count}. Новая дата: {target_date}.")
        return ConversationHandler.END
    context.user_data["repeat_move_task_ids"] = [task.id for task in repeated]
    context.user_data["repeat_move_target_date"] = target_date.isoformat()
    prefix = f"Обычных задач перенесено: {moved_count}.\n\n" if moved_count else ""
    await _reply_move_text(
        update,
        prefix
        + "Эти задачи уже переносились два или более раза:\n"
        + "\n".join(f"• {task.text} — переносов: {task.postponement_count}" for task in repeated)
        + "\n\nПеренести их снова?",
        reply_markup=repeated_move_keyboard(),
    )
    return MOVE_REPEAT_CONFIRM


async def _reply_move_text(update: Update, text: str, *, reply_markup=None) -> None:
    query = getattr(update, "callback_query", None)
    if query is not None:
        if reply_markup is None:
            await query.edit_message_text(text)
        else:
            await query.edit_message_text(text, reply_markup=reply_markup)
    elif update.message is not None:
        if reply_markup is None:
            await update.message.reply_text(text)
        else:
            await update.message.reply_text(text, reply_markup=reply_markup)


async def receive_repeat_move_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.data is None or update.effective_user is None:
        return ConversationHandler.END
    await query.answer()
    task_ids = list(context.user_data.get("repeat_move_task_ids") or [])
    raw_target_date = context.user_data.get("repeat_move_target_date")
    _clear_repeat_move_data(context)
    if query.data == "repeatmove:cancel":
        await query.edit_message_text("Эти задачи оставлены без переноса.")
        return ConversationHandler.END
    if query.data != "repeatmove:confirm" or not isinstance(raw_target_date, str):
        return ConversationHandler.END
    moved = _task_service(context).move_tasks(
        task_ids, telegram_id=update.effective_user.id, target_date=date.fromisoformat(raw_target_date)
    )
    await query.edit_message_text(f"Повторно перенесено задач: {len(moved)}. Новая дата: {raw_target_date}.")
    return ConversationHandler.END


def _clear_repeat_move_data(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("repeat_move_task_ids", None)
    context.user_data.pop("repeat_move_target_date", None)


def _clear_feasibility_move_data(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (
        "feasibility_default_task_ids",
        "feasibility_selectable_task_ids",
        "feasibility_source_date",
    ):
        context.user_data.pop(key, None)


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
    if context.args:
        return await _quick_move_tasks(update, context)
    if update.message is None:
        return ConversationHandler.END
    await update.message.reply_text(
        "Выберите дату, с которой нужно перенести задачи: «Сегодня», «Завтра» "
        "или YYYY-MM-DD.",
        reply_markup=PLAN_DATE_KEYBOARD,
    )
    return MOVE_SOURCE_DATE


async def _quick_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    raw_value = " ".join(context.args).strip()
    parts = raw_value.split(maxsplit=1)
    explicit_date = _parse_plan_date(parts[0], allow_past=True) if parts else None
    if explicit_date is not None and len(parts) == 2:
        plan_date = explicit_date
        indexes_arg = parts[1]
    elif explicit_date is None:
        plan_date = date.today()
        indexes_arg = raw_value
    else:
        await update.message.reply_text(
            "Формат: /done 1,2,3 или /done 2026-07-16 1,2,3"
        )
        return ConversationHandler.END
    tasks = _tasks_in_display_order(
        _task_service(context).get_visible_tasks_for_date(
            update.effective_user.id,
            plan_date,
        )
    )
    indexes = _parse_task_indexes(indexes_arg, maximum=len(tasks))
    if indexes is None:
        await update.message.reply_text(
            f"На {plan_date} нет таких задач. Укажите номера через запятую: 1, 2, 3."
        )
        return ConversationHandler.END
    selected_tasks = [tasks[index - 1] for index in indexes]
    if any(task.status != TaskStatus.planned for task in selected_tasks):
        await update.message.reply_text(
            "Завершать можно только задачи со статусом planned."
        )
        return ConversationHandler.END
    completed = [
        _task_service(context).mark_done(task.id, update.effective_user.id)
        for task in selected_tasks
    ]
    completed_count = sum(task is not None for task in completed)
    message = (
        f"Отмечено выполненными: {completed_count}."
        if completed_count
        else "Задачи уже были изменены или не найдены."
    )
    awards = [
        _award_for_completed_task(
            context,
            telegram_id=update.effective_user.id,
            task_id=task.id,
        )
        for task in completed
        if task is not None
    ]
    award_messages = [format_awarded_goal_achievement(award) for award in awards if award]
    if award_messages:
        message += "\n\n" + "\n\n".join(award_messages)
    await update.message.reply_text(message)
    return ConversationHandler.END


async def _quick_task_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    if len(context.args) >= 2 and context.args[0].isdigit():
        plan_date = date.today()
        index = int(context.args[0])
        update_args = context.args[1:]
    elif len(context.args) >= 3 and context.args[1].isdigit():
        plan_date = _parse_plan_date(context.args[0], allow_past=True)
        index = int(context.args[1])
        update_args = context.args[2:]
    else:
        await update.message.reply_text(
            "Формат: /task_edit today 6 -важность:2 или "
            "/task_edit 6 -название:Новое название"
        )
        return ConversationHandler.END
    if plan_date is None:
        await update.message.reply_text("Укажите дату: today, tomorrow или YYYY-MM-DD.")
        return ConversationHandler.END
    tasks = _tasks_in_display_order(
        _task_service(context).get_visible_tasks_for_date(
            update.effective_user.id,
            plan_date,
        )
    )
    if index < 1 or index > len(tasks):
        await update.message.reply_text(f"На {plan_date} нет задачи с номером {index}.")
        return ConversationHandler.END
    try:
        update_values = parse_task_update(" ".join(update_args))
        details = _task_service(context).update_task(
            tasks[index - 1].id,
            telegram_id=update.effective_user.id,
            update=update_values,
        )
    except (TaskInputError, ValueError) as error:
        await update.message.reply_text(str(error))
        return ConversationHandler.END
    await update.message.reply_text(
        f"Задача обновлена: {details.task.text}"
        if details
        else "Задача не найдена или отменена."
    )
    return ConversationHandler.END


async def _quick_move_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    raw_value = " ".join(context.args).strip()
    parts = raw_value.rsplit(maxsplit=1)
    if len(parts) != 2:
        await update.message.reply_text(
            "Формат: /move_task today 1,5,6 tomorrow или /move_task 1,5,6 tomorrow"
        )
        return ConversationHandler.END
    source_and_indexes, target_arg = parts
    source_parts = source_and_indexes.split(maxsplit=1)
    explicit_date = _parse_plan_date(source_parts[0], allow_past=True) if source_parts else None
    if explicit_date is not None and len(source_parts) == 2:
        source_date = explicit_date
        indexes_arg = source_parts[1]
    elif explicit_date is None:
        source_date = date.today()
        indexes_arg = source_and_indexes
    else:
        await update.message.reply_text(
            "Формат: /move_task today 1,5,6 tomorrow или /move_task 1,5,6 tomorrow"
        )
        return ConversationHandler.END
    target_date = _parse_plan_date(target_arg)
    if source_date is None or target_date is None or source_date == target_date:
        await update.message.reply_text(
            "Укажите разные даты: /move_task today 1,5,6 tomorrow или /move_task 1,5,6 tomorrow"
        )
        return ConversationHandler.END
    source_tasks = _tasks_in_display_order(
        _task_service(context).get_visible_tasks_for_date(
            update.effective_user.id,
            source_date,
        )
    )
    indexes = _parse_task_indexes(indexes_arg, maximum=len(source_tasks))
    if indexes is None:
        await update.message.reply_text("Укажите номера задач через запятую: 1,5,6.")
        return ConversationHandler.END
    selected_tasks = [source_tasks[index - 1] for index in indexes]
    if any(task.status != TaskStatus.planned for task in selected_tasks):
        await update.message.reply_text("Переносить можно только задачи со статусом planned.")
        return ConversationHandler.END
    return await _move_with_repeat_confirmation(
        update, context, task_ids=[task.id for task in selected_tasks], target_date=target_date,
        known_tasks=selected_tasks,
    )


async def unschedule_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Move numbered planned tasks from a date into the no-date backlog."""
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END
    raw_value = " ".join(context.args).strip()
    parts = raw_value.split(maxsplit=1)
    explicit_date = _parse_plan_date(parts[0], allow_past=True) if parts else None
    if explicit_date is not None and len(parts) == 2:
        source_date = explicit_date
        indexes_arg = parts[1]
    elif explicit_date is None:
        source_date = date.today()
        indexes_arg = raw_value
    else:
        await update.message.reply_text(
            "Формат: /unschedule_task 1,2,3 или /unschedule_task 2026-07-16 1,2,3"
        )
        return ConversationHandler.END
    source_tasks = _tasks_in_display_order(
        _task_service(context).get_visible_tasks_for_date(
            update.effective_user.id, source_date
        )
    )
    indexes = _parse_task_indexes(indexes_arg, maximum=len(source_tasks))
    if indexes is None:
        await update.message.reply_text("Укажите номера задач через запятую: 1,2,3.")
        return ConversationHandler.END
    selected_tasks = [source_tasks[index - 1] for index in indexes]
    if any(task.status != TaskStatus.planned for task in selected_tasks):
        await update.message.reply_text("Убирать в список без даты можно только задачи со статусом planned.")
        return ConversationHandler.END
    moved = _task_service(context).move_tasks_to_backlog(
        [task.id for task in selected_tasks], telegram_id=update.effective_user.id
    )
    await update.message.reply_text(
        f"В список задач без даты перенесено: {len(moved)}."
        if moved
        else "Задачи уже были изменены или не найдены."
    )
    return ConversationHandler.END


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
    raw_value = (update.message.text or "").strip()
    parts = raw_value.rsplit(maxsplit=1)
    date_tokens = {"today", "сегодня", "tomorrow", "завтра"}
    target_value = (
        parts[1]
        if len(parts) == 2 and ("-" in parts[1] or parts[1].casefold() in date_tokens)
        else ""
    )
    inline_target = _parse_plan_date(target_value) if target_value else None
    indexes_value = parts[0] if target_value else raw_value
    indexes = _parse_task_indexes(indexes_value, maximum=len(task_ids))
    if indexes is None:
        await update.message.reply_text(
            "Введите номера через запятую, например: 1, 2, 3. "
            "Можно сразу указать дату: 5 2026-07-18."
        )
        return MOVE_TASKS
    context.user_data["selected_move_task_ids"] = [task_ids[index - 1] for index in indexes]
    if target_value.strip():
        target_date = inline_target
        source_date = date.fromisoformat(str(context.user_data.get("move_source_date")))
        if target_date is None:
            await update.message.reply_text("Укажите дату: today, tomorrow или YYYY-MM-DD.")
            return MOVE_TASKS
        if target_date == source_date:
            await update.message.reply_text("Выберите дату, отличающуюся от исходной.")
            return MOVE_TASKS
        return await _move_with_repeat_confirmation(
            update,
            context,
            task_ids=list(context.user_data["selected_move_task_ids"]),
            target_date=target_date,
        )
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
    return await _move_with_repeat_confirmation(
        update, context, task_ids=task_ids, target_date=target_date
    )


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


async def stat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return

    period = (context.args[0].casefold() if context.args else "week")
    today = date.today()
    if period in {"week", "неделя", "неделю", "7", "7d"}:
        start_date = today - timedelta(days=today.weekday())
        period_name = "текущую неделю"
        include_achievements = True
    elif period in {"month", "месяц", "месяц", "30", "30d"}:
        start_date = today.replace(day=1)
        period_name = "текущий месяц"
        include_achievements = False
    else:
        await update.message.reply_text(
            "Формат: /stat week или /stat month\n"
            "Без аргумента показывается текущая неделя."
        )
        return

    stats = _statistics_service(context).get_period_stats(
        update.effective_user.id,
        start_date,
        today,
    )
    if stats is None:
        await update.message.reply_text("Пользователь ещё не зарегистрирован. Используйте /start.")
        return
    text = format_period_stats(stats, period_name)
    if include_achievements:
        try:
            achievement_service = _weekly_achievement_service(context)
            report = achievement_service.get_or_create_report(
                telegram_id=update.effective_user.id,
                week_start=start_date,
                week_end=today,
                stats=stats,
            ) if achievement_service is not None else None
            if report is not None:
                text += "\n\n" + format_weekly_achievements(report)
        except (LLMProviderError, PsycopgError, ValueError) as error:
            if isinstance(error, LLMProviderError):
                failure_kind = "LLM"
            elif isinstance(error, PsycopgError):
                failure_kind = "DB"
            else:
                failure_kind = "VALIDATION"
            logger.exception(
                "Weekly achievement generation failed: telegram_id=%s, period=%s..%s, kind=%s",
                update.effective_user.id,
                start_date,
                today,
                failure_kind,
            )
            text += (
                "\n\n🎭 Комитет ачивок сегодня не собрал кворум. "
                f"Статистика всё равно действительна. Код: {failure_kind}."
            )
    for chunk in _split_telegram_message(text):
        await update.message.reply_text(chunk)


def _tasks_in_display_order(tasks):
    return [assessment.task for assessment in order_tasks_by_priority(tasks)]


def _format_minutes(value: int | None) -> str:
    if value is None:
        return "длительность не указана"
    hours, minutes = divmod(value, 60)
    if hours and minutes:
        return f"{hours} ч {minutes} мин"
    if hours:
        return f"{hours} ч"
    return f"{minutes} мин"


def _split_telegram_message(text: str, *, limit: int = 4000) -> list[str]:
    """Split a long plain-text response at line boundaries under Telegram's limit."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        else:
            split_at += 1
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    chunks.append(remaining)
    return chunks


async def _reply_text_in_chunks(message, text: str, *, reply_markup=None) -> None:
    chunks = _split_telegram_message(text)
    for index, chunk in enumerate(chunks):
        await message.reply_text(
            chunk,
            reply_markup=reply_markup if index == len(chunks) - 1 else None,
        )


def _format_unscheduled_tasks(tasks) -> str:
    return "\n".join(f"{index}. {task.text}" for index, task in enumerate(tasks, 1))
