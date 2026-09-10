from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from app.models.task import Task, TaskStatus


DAY_TYPE_KEYBOARD = ReplyKeyboardMarkup(
    [["Рабочий день", "Выходной"], ["Смешанный", "Больничный"]],
    one_time_keyboard=True,
    resize_keyboard=True,
)

PLAN_DATE_KEYBOARD = ReplyKeyboardMarkup(
    [["Сегодня", "Завтра"]],
    is_persistent=True,
    resize_keyboard=True,
    input_field_placeholder="Или введите YYYY-MM-DD",
)

SURVEY_MODE_KEYBOARD = ReplyKeyboardMarkup(
    [["Короткий опрос"], ["Длинный опрос"]], one_time_keyboard=True, resize_keyboard=True
)

DAY_MODE_KEYBOARD = ReplyKeyboardMarkup(
    [["🛋 Восстановительный", "🌿 Спокойный"], ["⚖️ Сбалансированный", "🎯 Сфокусированный"], ["🚀 Проектный"]],
    one_time_keyboard=True,
    resize_keyboard=True,
)


def strategy_selection_keyboard(recommended: tuple[str, str]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(f"⭐ {strategy}", callback_data=f"daystrategy:{index}")]
        for index, strategy in enumerate(recommended)
    ]
    buttons.extend(
        [InlineKeyboardButton(strategy, callback_data=f"daystrategy:{strategy_index}")]
        for strategy_index, strategy in enumerate(
            ("Глубокий фокус", "Чередование категорий", "Быстрый старт", "Сбалансированный режим", "Щадящий режим"),
            start=10,
        )
        if strategy not in recommended
    )
    return InlineKeyboardMarkup(buttons)

FEASIBILITY_TIME_KEYBOARD = ReplyKeyboardMarkup(
    [["По умолчанию"]],
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


def task_details_keyboard(tasks: list[Task]) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                f"{task.status.value}: {task.text[:48]}",
                callback_data=f"task:{task.id}",
            )
        ]
        for task in tasks
        if task.status != TaskStatus.cancelled
    ]
    return InlineKeyboardMarkup(buttons)


def task_edit_keyboard(tasks: list[Task]) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                f"{task.status.value}: {task.text[:48]}",
                callback_data=f"taskedit:{task.id}",
            )
        ]
        for task in tasks
        if task.status != TaskStatus.cancelled
    ]
    return InlineKeyboardMarkup(buttons)


def feasibility_move_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Перенести предложенные", callback_data="feasmove:default")],
            [InlineKeyboardButton("Выбрать задачи", callback_data="feasmove:select")],
            [InlineKeyboardButton("Оставить как есть", callback_data="feasmove:skip")],
        ]
    )


def repeated_move_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Всё же перенести", callback_data="repeatmove:confirm")],
            [InlineKeyboardButton("Оставить без переноса", callback_data="repeatmove:cancel")],
        ]
    )


def ai_estimate_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Посмотреть предложения", callback_data="aiest:view")],
            [InlineKeyboardButton("Применить все допустимые", callback_data="aiest:all")],
            [InlineKeyboardButton("Выбрать изменения", callback_data="aiest:select")],
            [InlineKeyboardButton("Закрыть и сохранить", callback_data="aiest:cancel")],
        ]
    )


def ai_estimate_draft_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Открыть сохранённые", callback_data="aiest:open")],
            [InlineKeyboardButton("Создать новую оценку", callback_data="aiest:new")],
            [InlineKeyboardButton("Закрыть", callback_data="aiest:cancel")],
        ]
    )


def ai_plan_actions_keyboard(*, has_reflection: bool = False) -> InlineKeyboardMarkup:
    if has_reflection:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Применить улучшенный порядок", callback_data="aiplan:apply_reflected")],
                [InlineKeyboardButton("Оставить исходный порядок", callback_data="aiplan:apply_original")],
                [InlineKeyboardButton("Выбрать задачи", callback_data="aiplan:select")],
                [InlineKeyboardButton("Дать обратную связь", callback_data="aiplan:feedback")],
                [InlineKeyboardButton("Закрыть", callback_data="aiplan:cancel")],
            ]
        )
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Применить порядок", callback_data="aiplan:apply")],
                [InlineKeyboardButton("Выбрать изменения", callback_data="aiplan:select")],
                [InlineKeyboardButton("Дать обратную связь", callback_data="aiplan:feedback")],
                [InlineKeyboardButton("Оставить текущий порядок", callback_data="aiplan:cancel")],
        ]
    )


def ai_plan_retry_keyboard(checkpoint_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Повторить AI-план", callback_data=f"aiplanretry:{checkpoint_id}")]]
    )


def save_fixed_time_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Сохранить в задачу", callback_data="fixedtime:save")],
         [InlineKeyboardButton("Учесть только сейчас", callback_data="fixedtime:skip")]]
    )


def ai_estimate_task_keyboard(estimates) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(estimate.task.text[:52], callback_data=f"aiest:task:{estimate.task.id}")]
            for estimate in estimates
        ]
    )


def schedule_source_keyboard(tasks, ideas) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(f"Задача: {task.text[:45]}", callback_data=f"schedule:task:{task.id}")]
        for task in tasks
    ]
    buttons.extend(
        [InlineKeyboardButton(f"Идея: {idea.text[:45]}", callback_data=f"schedule:idea:{idea.id}")]
        for idea in ideas
    )
    return InlineKeyboardMarkup(buttons)
