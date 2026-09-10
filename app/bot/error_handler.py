import logging

from telegram import Update
from telegram.error import NetworkError
from telegram.ext import ContextTypes


logger = logging.getLogger(__name__)


async def handle_unexpected_error(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    error = context.error
    if isinstance(error, NetworkError):
        # Polling already retries transient Telegram/DNS failures. A concise
        # warning is enough; logging the full traceback on every retry floods
        # the log without adding useful diagnostic information.
        logger.warning("Temporary Telegram network error: %s", error)
        return

    logger.error(
        "Unhandled bot update error",
        exc_info=(
            (type(error), error, error.__traceback__)
            if isinstance(error, BaseException)
            else None
        ),
    )
    if not isinstance(update, Update) or update.effective_message is None:
        return
    try:
        await update.effective_message.reply_text(
            "Не удалось обработать запрос из-за технической ошибки. "
            "Изменения не сохранены. Повторите попытку."
        )
    except NetworkError as reply_error:
        logger.warning("Could not send error response to Telegram: %s", reply_error)
