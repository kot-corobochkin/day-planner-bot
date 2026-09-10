import re
from dataclasses import dataclass
from datetime import time

from app.models.task import TaskStatus
from app.models.task import TaskValueSource


class TaskInputError(ValueError):
    pass


@dataclass(frozen=True)
class TaskDraft:
    text: str
    estimated_minutes: int = 60
    start_time: time | None = None
    due_time: time | None = None
    priority: int = 5
    effort: int = 5
    context: str | None = None
    priority_source: TaskValueSource = TaskValueSource.default
    effort_source: TaskValueSource = TaskValueSource.default
    duration_source: TaskValueSource = TaskValueSource.default


@dataclass(frozen=True)
class TaskUpdate:
    provided_fields: frozenset[str]
    text: str | None = None
    estimated_minutes: int | None = None
    start_time: time | None = None
    due_time: time | None = None
    priority: int | None = None
    effort: int | None = None
    context: str | None = None
    status: TaskStatus | None = None


_PARAMETER_NAMES = {
    "длительность",
    "время начала",
    "дедлайн",
    "важность",
    "сложность",
    "контекст",
}
_EDIT_PARAMETER_NAMES = _PARAMETER_NAMES | {"название", "статус"}
_PARAMETER_RE = re.compile(
    r"(?<!\S)-?(?P<name>длительность|время\s+начала|дедлайн|важность|сложность|контекст)\s*:",
    re.IGNORECASE,
)
_EDIT_PARAMETER_RE = re.compile(
    r"(?<!\S)-?(?P<name>длительность|время\s+начала|дедлайн|важность|сложность|контекст|название|статус)\s*:",
    re.IGNORECASE,
)
_DASHED_PARAMETER_RE = re.compile(
    r"(?<!\S)-(?P<name>[а-яё]+(?:\s+[а-яё]+)?)\s*:",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(
    r"(?P<value>\d+)\s*(?P<unit>минута|минуты|минут|мин|м|час|часа|часов|ч)",
    re.IGNORECASE,
)
_CLOCK_DURATION_RE = re.compile(r"(?P<hours>\d{1,2}):(?P<minutes>[0-5]\d)")
_TIME_RE = re.compile(r"(?:[01]?\d|2[0-3]):[0-5]\d")


def parse_task_lines(lines: list[str]) -> list[TaskDraft]:
    drafts = [parse_task_line(line, line_number=index) for index, line in enumerate(lines, 1)]
    return [draft for draft in drafts if draft is not None]


def parse_task_line(line: str, *, line_number: int) -> TaskDraft | None:
    raw = line.strip()
    if not raw:
        return None

    for match in _DASHED_PARAMETER_RE.finditer(raw):
        name = _normalize_name(match.group("name"))
        if name not in _PARAMETER_NAMES:
            raise TaskInputError(f"Строка {line_number}: неизвестный параметр «{name}».")

    matches = list(_PARAMETER_RE.finditer(raw))
    text = raw[: matches[0].start()].strip() if matches else raw
    if not text:
        raise TaskInputError(f"Строка {line_number}: укажите название задачи перед параметрами.")
    if len(text) > 500:
        raise TaskInputError(f"Строка {line_number}: название длиннее 500 символов.")

    values: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = _normalize_name(match.group("name"))
        value_end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        value = raw[match.end() : value_end].strip()
        if name in values:
            raise TaskInputError(f"Строка {line_number}: параметр «{name}» указан дважды.")
        if not value:
            raise TaskInputError(f"Строка {line_number}: укажите значение параметра «{name}».")
        values[name] = value

    start_time = _parse_time(values.get("время начала"), "время начала", line_number)
    due_time = _parse_time(values.get("дедлайн"), "дедлайн", line_number)
    if start_time and due_time and due_time <= start_time:
        raise TaskInputError(
            f"Строка {line_number}: дедлайн должен быть позже времени начала."
        )

    context = values.get("контекст")
    if context and len(context) > 200:
        raise TaskInputError(f"Строка {line_number}: контекст длиннее 200 символов.")

    return TaskDraft(
        text=text,
        estimated_minutes=_parse_duration(values.get("длительность"), line_number) or 60,
        start_time=start_time,
        due_time=due_time,
        priority=_parse_scale(values.get("важность"), "важность", line_number),
        effort=_parse_scale(values.get("сложность"), "сложность", line_number),
        context=context,
        priority_source=(
            TaskValueSource.user if "важность" in values else TaskValueSource.default
        ),
        effort_source=(
            TaskValueSource.user if "сложность" in values else TaskValueSource.default
        ),
        duration_source=(
            TaskValueSource.user if "длительность" in values else TaskValueSource.default
        ),
    )


def parse_task_update(value: str) -> TaskUpdate:
    raw = value.strip()
    if not raw:
        raise TaskInputError("Укажите хотя бы один параметр для изменения.")

    for match in _DASHED_PARAMETER_RE.finditer(raw):
        name = _normalize_name(match.group("name"))
        if name not in _EDIT_PARAMETER_NAMES:
            raise TaskInputError(f"Неизвестный параметр «{name}».")

    matches = list(_EDIT_PARAMETER_RE.finditer(raw))
    if not matches:
        raise TaskInputError("Укажите параметры, например: -важность:2.")
    if raw[: matches[0].start()].strip():
        raise TaskInputError("Укажите параметры в формате «-название:Новое название».")

    values: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = _normalize_name(match.group("name"))
        value_end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        parameter_value = raw[match.end() : value_end].strip()
        if name in values:
            raise TaskInputError(f"Параметр «{name}» указан дважды.")
        if not parameter_value:
            raise TaskInputError(f"Укажите значение параметра «{name}».")
        values[name] = parameter_value

    cleared = {name for name, parameter_value in values.items() if _is_clear_value(parameter_value)}
    for name in cleared - {"длительность", "время начала", "дедлайн", "контекст"}:
        raise TaskInputError(f"Параметр «{name}» нельзя очистить.")

    return TaskUpdate(
        provided_fields=frozenset(values),
        text=(None if "название" not in values else _parse_title(values["название"])),
        estimated_minutes=(
            None
            if "длительность" in cleared
            else _parse_duration(values.get("длительность"), 1)
        ),
        start_time=(
            None
            if "время начала" in cleared
            else _parse_time(values.get("время начала"), "время начала", 1)
        ),
        due_time=(
            None if "дедлайн" in cleared else _parse_time(values.get("дедлайн"), "дедлайн", 1)
        ),
        priority=(
            None
            if "важность" not in values
            else _parse_scale(values.get("важность"), "важность", 1)
        ),
        effort=(
            None
            if "сложность" not in values
            else _parse_scale(values.get("сложность"), "сложность", 1)
        ),
        context=(
            None
            if "контекст" in cleared or "контекст" not in values
            else _parse_context(values["контекст"])
        ),
        status=(
            None
            if "статус" not in values
            else _parse_status(values["статус"])
        ),
    )


def parse_available_minutes(value: str) -> int:
    try:
        minutes = _parse_duration(value.strip(), 1)
    except TaskInputError as error:
        raise TaskInputError(
            "Укажите доступное время как «6 ч», «6:30» или «360 м»."
        ) from error
    assert minutes is not None
    return minutes


def _normalize_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _parse_duration(value: str | None, line_number: int) -> int | None:
    if value is None:
        return None
    clock_match = _CLOCK_DURATION_RE.fullmatch(value)
    if clock_match is not None:
        minutes = int(clock_match.group("hours")) * 60 + int(
            clock_match.group("minutes")
        )
        if not 1 <= minutes <= 24 * 60:
            raise TaskInputError(
                f"Строка {line_number}: длительность должна быть от 1 до 1440 минут."
            )
        return minutes
    match = _DURATION_RE.fullmatch(value)
    if match is None:
        raise TaskInputError(
            f"Строка {line_number}: длительность укажите как «30 минут», «2 ч» или «1:30»."
        )
    amount = int(match.group("value"))
    unit = match.group("unit").casefold()
    minutes = amount * 60 if unit in {"час", "часа", "часов", "ч"} else amount
    if not 1 <= minutes <= 24 * 60:
        raise TaskInputError(f"Строка {line_number}: длительность должна быть от 1 до 1440 минут.")
    return minutes


def _parse_time(value: str | None, name: str, line_number: int) -> time | None:
    if value is None:
        return None
    if _TIME_RE.fullmatch(value) is None:
        raise TaskInputError(f"Строка {line_number}: {name} укажите в формате ЧЧ:ММ.")
    hours, minutes = value.split(":")
    return time(hour=int(hours), minute=int(minutes))


def _parse_scale(value: str | None, name: str, line_number: int) -> int:
    if value is None:
        return 5
    if not value.isdecimal() or not 1 <= int(value) <= 10:
        raise TaskInputError(f"Строка {line_number}: {name} укажите числом от 1 до 10.")
    return int(value)


def _is_clear_value(value: str) -> bool:
    return value.casefold() in {"-", "нет", "очистить"}


def _parse_context(value: str) -> str:
    if len(value) > 200:
        raise TaskInputError("Контекст длиннее 200 символов.")
    return value


def _parse_title(value: str) -> str:
    title = value.strip()
    if not title or _is_clear_value(title):
        raise TaskInputError("Название задачи нельзя очистить.")
    if len(title) > 500:
        raise TaskInputError("Название задачи длиннее 500 символов.")
    return title


def _parse_status(value: str) -> TaskStatus:
    normalized = value.casefold().strip()
    statuses = {
        "planned": TaskStatus.planned,
        "запланирована": TaskStatus.planned,
        "done": TaskStatus.done,
        "выполнена": TaskStatus.done,
        "postponed": TaskStatus.postponed,
        "отложена": TaskStatus.postponed,
    }
    status = statuses.get(normalized)
    if status is None:
        raise TaskInputError(
            "Статус: «запланирована», «выполнена» или «отложена». "
            "Для отмены используйте /cancel_task."
        )
    return status
