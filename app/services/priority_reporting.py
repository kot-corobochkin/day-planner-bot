from collections import OrderedDict
from datetime import date, datetime

from app.models.task import Task
from app.services.feasibility import MoveRecommendation, PlanFeasibility
from app.services.task_prioritization import (
    TaskPriorityAssessment,
    assess_task,
    explain_priority_factors,
)


PRIORITY_GROUPS = (
    ("🔴", "Критический приоритет", 80, 100),
    ("🟠", "Высокий приоритет", 65, 79),
    ("🟡", "Повышенный приоритет", 55, 64),
    ("⚪", "Обычный приоритет", 45, 54),
    ("🔵", "Низкий приоритет", 0, 44),
)


def group_priority_assessments(
    tasks: list[Task], *, now: datetime | None = None
) -> OrderedDict[tuple[str, str], list[TaskPriorityAssessment]]:
    groups: OrderedDict[tuple[str, str], list[TaskPriorityAssessment]] = OrderedDict(
        ((emoji, name), []) for emoji, name, _, _ in PRIORITY_GROUPS
    )
    for assessment in sorted(
        (assess_task(task, now=now) for task in tasks), key=lambda item: (-item.score, item.task.id)
    ):
        for emoji, name, lower, upper in PRIORITY_GROUPS:
            if lower <= assessment.score <= upper:
                groups[(emoji, name)].append(assessment)
                break
    return groups


def format_feasibility_report(
    plan_date: date,
    result: PlanFeasibility,
    recommendation: MoveRecommendation | None = None,
    *,
    now: datetime | None = None,
) -> str:
    lines = [f"📊 Анализ плана на {plan_date:%d.%m.%Y}", ""]
    lines.append("⚠️ План перегружен" if result.is_overloaded else "✅ План выполним")
    lines.extend(
        [
            f"Доступно: {_format_minutes(result.available_minutes)}",
            f"Запланировано: {_format_minutes(result.scheduled_minutes)}",
        ]
    )
    if result.is_overloaded:
        lines.append(f"Перегрузка: {_format_minutes(-result.remaining_minutes)}")
    else:
        lines.append(f"Запас времени: {_format_minutes(result.remaining_minutes)}")

    if result.planned_tasks:
        lines.extend(["", *_format_priority_groups(result.planned_tasks, now=now)])
    if result.is_overloaded:
        lines.extend(
            [
                "",
                "Чтобы сделать план выполнимым, нужно освободить не менее "
                f"{_format_minutes(-result.remaining_minutes)}.",
            ]
        )
        if recommendation and recommendation.tasks:
            lines.extend(["Предлагается перенести:"])
            lines.extend(
                f"• {candidate.task.text} — {_format_minutes(candidate.task.estimated_minutes or 0)}"
                for candidate in recommendation.tasks
            )
            lines.append(f"Освободится: {_format_minutes(recommendation.freed_minutes)}.")
            if recommendation.ambiguous:
                lines.append(
                    f"У {recommendation.ambiguous_task_count} задач одинаковый приоритет "
                    "и ограничения. Данных недостаточно для обоснованного выбора: "
                    "укажите важность, дедлайн или выберите задачи вручную."
                )
    if result.unknown_duration_count:
        lines.append(
            f"Без длительности: {result.unknown_duration_count}; вывод по времени неполный."
        )
    return "\n".join(lines)


def format_priority_details(
    plan_date: date, tasks: list[Task], *, now: datetime | None = None
) -> str:
    lines = [f"🔍 Подробный расчёт приоритетов на {plan_date:%d.%m.%Y}"]
    for assessment in sorted(
        (assess_task(task, now=now) for task in tasks), key=lambda item: (-item.score, item.task.id)
    ):
        lines.extend(["", f"{assessment.task.text} — {assessment.score}/100", "Базовый приоритет: 50"])
        for group, points, reason in explain_priority_factors(assessment):
            sign = "+" if points > 0 else ""
            lines.append(f"{group}: {sign}{points}. {reason}.")
        if assessment.task.postponement_count >= 3:
            lines.extend(
                [
                    "Задача переносилась уже 3 раза.",
                    "Рекомендуется: разбить задачу на подзадачи, уточнить следующий шаг, "
                    "изменить дату, убрать в бэклог или отказаться от задачи.",
                ]
            )
        lines.append(f"Итог: {assessment.score}/100")
    return "\n".join(lines)


def _format_priority_groups(tasks: list[Task], *, now: datetime | None = None) -> list[str]:
    lines: list[str] = []
    for (emoji, name), assessments in group_priority_assessments(tasks, now=now).items():
        if not assessments:
            continue
        suffix = f" — {len(assessments)} задач" if len(assessments) > 1 else ""
        lines.extend([f"{emoji} {name}{suffix}", ""])
        shown = assessments[:5]
        for assessment in shown:
            lines.append(f"• {assessment.task.text} — {assessment.score}/100")
            factors = explain_priority_factors(assessment)
            if factors:
                lines.append("  " + " · ".join(reason for _, _, reason in factors))
        if len(assessments) > len(shown):
            extra_count = len(assessments) - len(shown)
            lines.append(f"…и ещё {extra_count} {_task_word(extra_count)}.")
        lines.append("")
    return lines[:-1] if lines and not lines[-1] else lines


def _format_minutes(value: int) -> str:
    hours, minutes = divmod(value, 60)
    if hours and minutes:
        return f"{hours} ч {minutes} мин"
    if hours:
        return f"{hours} ч"
    return f"{minutes} мин"


def _task_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "задача"
    if count % 10 in {2, 3, 4} and count % 100 not in {12, 13, 14}:
        return "задачи"
    return "задач"
