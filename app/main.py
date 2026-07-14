from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.bot.callbacks import handle_done_callback
from app.bot.handlers import (
    DAY_TYPE,
    DONE_DATE,
    MOVE_SOURCE_DATE,
    MOVE_TARGET_DATE,
    MOVE_TASKS,
    PLAN_DATE,
    TASKS,
    CANCEL_DATE,
    cancel,
    cancel_task,
    done,
    move_task,
    plan_start,
    receive_day_type,
    receive_move_source_date,
    receive_move_target_date,
    receive_move_tasks,
    receive_plan_date,
    receive_task_action_date,
    receive_tasks,
    start,
    status,
    today,
)
from app.config import get_settings
from app.database import Database
from app.scheduler.jobs import schedule_jobs
from app.services.planning_service import PlanningService
from app.services.task_service import TaskService


def build_application() -> Application:
    settings = get_settings()
    db = Database(settings)

    application = Application.builder().token(settings.bot_token).build()
    application.bot_data["db"] = db
    application.bot_data["planning_service"] = PlanningService(db, settings.default_timezone)
    application.bot_data["task_service"] = TaskService(db)

    planning_conversation = ConversationHandler(
        entry_points=[CommandHandler("plan", plan_start)],
        states={
            PLAN_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_plan_date)],
            DAY_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_day_type)],
            TASKS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_tasks)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    done_conversation = ConversationHandler(
        entry_points=[CommandHandler("done", done)],
        states={
            DONE_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_task_action_date)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    cancel_task_conversation = ConversationHandler(
        entry_points=[CommandHandler("cancel_task", cancel_task)],
        states={
            CANCEL_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_task_action_date)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    move_task_conversation = ConversationHandler(
        entry_points=[CommandHandler("move_task", move_task)],
        states={
            MOVE_SOURCE_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_move_source_date)
            ],
            MOVE_TASKS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_move_tasks)
            ],
            MOVE_TARGET_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_move_target_date)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(planning_conversation)
    application.add_handler(CommandHandler("today", today))
    application.add_handler(done_conversation)
    application.add_handler(cancel_task_conversation)
    application.add_handler(move_task_conversation)
    application.add_handler(CommandHandler("status", status))
    application.add_handler(
        CallbackQueryHandler(handle_done_callback, pattern=r"^(done|cancel):\d+$")
    )

    schedule_jobs(application, settings)
    return application


def main() -> None:
    application = build_application()
    application.run_polling()


if __name__ == "__main__":
    main()
