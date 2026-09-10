from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from app.bot.callbacks import handle_done_callback
from app.bot.error_handler import handle_unexpected_error
from app.bot.handlers import (
    DAY_TYPE,
    DONE_DATE,
    MOVE_SOURCE_DATE,
    MOVE_TARGET_DATE,
    MOVE_TASKS,
    MOVE_REPEAT_CONFIRM,
    PLAN_DATE,
    TASKS,
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
    AI_PLAN_AGENT_QUESTION,
    AI_PLAN_FIXED_TIME_SAVE,
    AI_PLAN_FEEDBACK,
    AI_PLAN_GOAL_SUGGESTIONS,
    EVENING_REFLECTION_ANSWER,
    CANCEL_DATE,
    cancel,
    cancel_task,
    done,
    move_task,
    unschedule_task,
    plan_start,
    plan_analysis_details,
    plan_view,
    receive_day_type,
    receive_move_source_date,
    receive_move_target_date,
    receive_move_tasks,
    receive_repeat_move_decision,
    receive_plan_date,
    receive_task_date,
    receive_task_edit_date,
    receive_task_edit_fields,
    receive_task_edit_selection,
    receive_feasibility_date,
    receive_feasibility_time,
    receive_feasibility_move_decision,
    receive_feasibility_move_selection,
    receive_ai_estimate_date,
    receive_ai_estimate_action,
    receive_ai_estimate_task,
    receive_ai_plan_date,
    receive_ai_plan_action,
    receive_ai_plan_selection,
    receive_day_state_survey_mode,
    receive_day_state_short_energy,
    receive_day_state_short_concentration,
    receive_day_state_short_mental_fatigue,
    receive_day_state_short_physical_energy,
    receive_day_state_day_mode,
    receive_day_state_long_question,
    receive_day_state_strategy,
    receive_day_state_strategy_reason,
    receive_ai_plan_agent_question,
    receive_fixed_time_save,
    receive_ai_plan_feedback,
    receive_ai_plan_goal_suggestions,
    retry_ai_plan,
    plan_feedback,
    agent_memory,
    receive_evening_reflection_answer,
    receive_idea,
    receive_inbox_task,
    receive_schedule_date,
    receive_schedule_source,
    receive_task_action_date,
    receive_tasks,
    start,
    status,
    stat,
    task_card,
    task_edit,
    feasibility,
    ai_estimate,
    ai_plan,
    ai_plan_view,
    evening_reflection,
    category_tasks,
    help_command,
    idea,
    ideas,
    inbox,
    backlog,
    upcoming,
    schedule_task,
    today,
)
from app.config import get_settings
from app.database import Database
from app.scheduler.jobs import schedule_jobs
from app.services.planning_service import PlanningService
from app.services.task_service import TaskService
from app.services.capture_service import CaptureService
from app.services.llm_provider import LLMProvider
from app.services.statistics_service import StatisticsService
from app.services.weekly_achievements import WeeklyAchievementService


def build_application() -> Application:
    settings = get_settings()
    db = Database(settings)

    request_options = {
        "connect_timeout": settings.telegram_connect_timeout_seconds,
        "read_timeout": settings.telegram_read_timeout_seconds,
        "write_timeout": settings.telegram_write_timeout_seconds,
        "pool_timeout": settings.telegram_pool_timeout_seconds,
    }
    application = (
        Application.builder()
        .token(settings.bot_token)
        .request(HTTPXRequest(**request_options))
        .get_updates_request(HTTPXRequest(**request_options))
        .build()
    )
    application.bot_data["db"] = db
    application.bot_data["planning_service"] = PlanningService(db, settings.default_timezone)
    application.bot_data["task_service"] = TaskService(db)
    application.bot_data["capture_service"] = CaptureService(db, settings.default_timezone)
    application.bot_data["statistics_service"] = StatisticsService(db)
    application.bot_data["llm_provider"] = LLMProvider(
        api_key=settings.llm_api_key.get_secret_value(),
        model_name=[settings.model_name, *settings.model_fallbacks.split(",")],
        base_url=settings.llm_base_url,
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
        max_response_bytes=settings.llm_max_response_bytes,
    )
    application.bot_data["weekly_achievement_service"] = WeeklyAchievementService(
        db, application.bot_data["llm_provider"]
    )

    workflow_conversation = ConversationHandler(
        entry_points=[
            CommandHandler("plan", plan_start),
            CommandHandler("done", done),
            CommandHandler("cancel_task", cancel_task),
            CommandHandler("task", task_card),
            CommandHandler("task_edit", task_edit),
            CommandHandler("feasibility", feasibility),
            CommandHandler("idea", idea),
            CommandHandler("inbox", inbox),
            CommandHandler("schedule_task", schedule_task),
            CommandHandler("move_task", move_task),
            CommandHandler("unschedule_task", unschedule_task),
            CommandHandler("ai_estimate", ai_estimate),
            CommandHandler("ai_plan", ai_plan),
            CommandHandler("evening_reflection", evening_reflection),
        ],
        states={
            PLAN_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_plan_date)],
            DAY_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_day_type)],
            TASKS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_tasks)],
            DONE_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_task_action_date)
            ],
            CANCEL_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_task_action_date)
            ],
            TASK_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_task_date)],
            TASK_EDIT_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_task_edit_date)
            ],
            TASK_EDIT_SELECT: [
                CallbackQueryHandler(
                    receive_task_edit_selection,
                    pattern=r"^taskedit:\d+$",
                )
            ],
            TASK_EDIT_FIELDS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_task_edit_fields)
            ],
            FEASIBILITY_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_feasibility_date)
            ],
            FEASIBILITY_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_feasibility_time)
            ],
            FEASIBILITY_MOVE_DECISION: [
                CallbackQueryHandler(
                    receive_feasibility_move_decision,
                    pattern=r"^feasmove:(default|select|skip)$",
                )
            ],
            FEASIBILITY_MOVE_SELECT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_feasibility_move_selection,
                )
            ],
            IDEA_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_idea)],
            INBOX_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_inbox_task)],
            SCHEDULE_SELECT: [
                CallbackQueryHandler(
                    receive_schedule_source,
                    pattern=r"^schedule:(task|idea):\d+$",
                )
            ],
            SCHEDULE_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_schedule_date)
            ],
            MOVE_SOURCE_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_move_source_date)
            ],
            MOVE_TASKS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_move_tasks)
            ],
            MOVE_TARGET_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_move_target_date)
            ],
            MOVE_REPEAT_CONFIRM: [
                CallbackQueryHandler(
                    receive_repeat_move_decision,
                    pattern=r"^repeatmove:(confirm|cancel)$",
                )
            ],
            AI_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ai_estimate_date)
            ],
            AI_ACTION: [
                CallbackQueryHandler(
                    receive_ai_estimate_action,
                    pattern=r"^aiest:(view|all|select|cancel|open|new)$",
                )
            ],
            AI_TASK: [
                CallbackQueryHandler(
                    receive_ai_estimate_task,
                    pattern=r"^aiest:(task|apply|dismiss|skip):\d+$",
                )
            ],
            AI_PLAN_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ai_plan_date)
            ],
            AI_PLAN_ACTION: [
                CallbackQueryHandler(
                    receive_ai_plan_action,
                    pattern=r"^aiplan:(apply|apply_reflected|apply_original|select|feedback|cancel)$",
                )
            ],
            AI_PLAN_SELECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ai_plan_selection)
            ],
            AI_PLAN_SURVEY_MODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_day_state_survey_mode)
            ],
            AI_PLAN_SHORT_ENERGY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_day_state_short_energy)
            ],
            AI_PLAN_SHORT_CONCENTRATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_day_state_short_concentration)
            ],
            AI_PLAN_SHORT_MENTAL_FATIGUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_day_state_short_mental_fatigue)
            ],
            AI_PLAN_SHORT_PHYSICAL_ENERGY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_day_state_short_physical_energy)
            ],
            AI_PLAN_DAY_MODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_day_state_day_mode)
            ],
            AI_PLAN_LONG_QUESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_day_state_long_question)
            ],
            AI_PLAN_STRATEGY: [
                CallbackQueryHandler(receive_day_state_strategy, pattern=r"^daystrategy:\d+$")
            ],
            AI_PLAN_STRATEGY_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_day_state_strategy_reason)
            ],
            AI_PLAN_AGENT_QUESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ai_plan_agent_question)
            ],
            AI_PLAN_FIXED_TIME_SAVE: [
                CallbackQueryHandler(receive_fixed_time_save, pattern=r"^fixedtime:(save|skip)$")
            ],
            AI_PLAN_FEEDBACK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ai_plan_feedback)
            ],
            AI_PLAN_GOAL_SUGGESTIONS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ai_plan_goal_suggestions)
            ],
            EVENING_REFLECTION_ANSWER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_evening_reflection_answer)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(workflow_conversation)
    application.add_handler(CommandHandler("plan_view", plan_view))
    application.add_handler(CommandHandler("plan_analysis_details", plan_analysis_details))
    application.add_handler(CommandHandler("ai_plan_view", ai_plan_view))
    application.add_handler(CommandHandler("plan_feedback", plan_feedback))
    application.add_handler(CommandHandler("agent_memory", agent_memory))
    application.add_handler(CallbackQueryHandler(retry_ai_plan, pattern=r"^aiplanretry:\d+$"))
    application.add_handler(CommandHandler("category", category_tasks))
    application.add_handler(CommandHandler("today", today))
    application.add_handler(CommandHandler("ideas", ideas))
    application.add_handler(CommandHandler("backlog", backlog))
    application.add_handler(CommandHandler("upcoming", upcoming))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("stat", stat))
    application.add_handler(
        CallbackQueryHandler(handle_done_callback, pattern=r"^(done|cancel|task):\d+$")
    )
    application.add_error_handler(handle_unexpected_error)

    schedule_jobs(application, settings)
    return application


def main() -> None:
    application = build_application()
    application.run_polling()


if __name__ == "__main__":
    main()
