from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from app.models.task import Task


DAY_TYPE_KEYBOARD = ReplyKeyboardMarkup(
    [["Рабочий день", "Выходной"], ["Смешанный", "Больничный"]],
    one_time_keyboard=True,
    resize_keyboard=True,
)

PLAN_DATE_KEYBOARD = ReplyKeyboardMarkup(
    [["Сегодня", "Завтра"]],
    one_time_keyboard=True,
    resize_keyboard=True,
)


def unfinished_tasks_keyboard(tasks: list[Task]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(task.text[:60], callback_data=f"done:{task.id}")]
        for task in tasks
    ]
    return InlineKeyboardMarkup(buttons)


def cancellable_tasks_keyboard(tasks: list[Task]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(task.text[:60], callback_data=f"cancel:{task.id}")]
        for task in tasks
    ]
    return InlineKeyboardMarkup(buttons)
