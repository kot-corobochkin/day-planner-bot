from app.models.task import TaskStatus
from app.services.task_service import TaskDetails


def format_task_card(details: TaskDetails) -> str:
    task = details.task
    status = {
        TaskStatus.planned: "Запланирована",
        TaskStatus.done: "Выполнена",
        TaskStatus.postponed: "Отложена",
    }.get(task.status, task.status.value)
    lines = [
        f"Задача: {task.text}",
        f"Статус: {status}",
        f"Дата плана: {details.plan_date}",
        f"Первый план: {task.first_planned_date}",
        f"Переносов: {task.postponement_count}",
        f"Важность: {task.priority}/10",
        f"Сложность: {task.effort}/10",
    ]
    if task.estimated_minutes is not None:
        lines.append(f"Длительность: {task.estimated_minutes} мин")
    if task.starts_at is not None:
        lines.append(f"Время начала: {task.starts_at:%Y-%m-%d %H:%M}")
    if task.due_at is not None:
        lines.append(f"Дедлайн: {task.due_at:%Y-%m-%d %H:%M}")
    if task.context:
        lines.append(f"Контекст: {task.context}")
    return "\n".join(lines)
