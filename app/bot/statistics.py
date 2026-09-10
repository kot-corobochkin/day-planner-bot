from app.services.statistics_service import PeriodStats
from app.services.weekly_achievements import AwardedGoalAchievement, WeeklyAchievementReport


_WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def format_period_stats(stats: PeriodStats, period_name: str) -> str:
    completion = round(stats.completed_tasks / stats.total_tasks * 100) if stats.total_tasks else 0
    lines = [
        f"📊 Статистика за {period_name}",
        f"{stats.start_date:%d.%m} — {stats.end_date:%d.%m.%Y}",
        "",
        "Задачи",
        f"  Всего в планах: {stats.total_tasks}",
        f"  ✅ Выполнено: {stats.completed_tasks} ({completion}%)",
        f"     ├─ новых: {stats.completed_new_tasks}",
        f"     └─ активных: {stats.completed_active_tasks}",
        "",
        "Новые входящие",
        f"  💡 Идей: {stats.new_ideas}",
        f"  📥 Задач без даты: {stats.new_unscheduled_tasks}",
        "",
        "По дням",
    ]
    lines.extend(_format_daily_stats(stats))
    lines.extend([
        "",
        "По категориям",
    ])

    if stats.categories:
        for category in stats.categories:
            category_completion = (
                round(category.completed / category.total * 100) if category.total else 0
            )
            lines.append(
                f"  • {category.name}: выполнено {category.completed} из {category.total} "
                f"({category_completion}%)"
            )
    else:
        lines.append("  Пока нет задач за этот период.")

    lines.extend(["", "Что стоит пересмотреть"])
    if stats.stale_tasks:
        lines.append("  🔁 Долго не выполняются:")
        for task in stats.stale_tasks:
            category = f" · {task.category}" if task.category else ""
            lines.append(
                f"  • #{task.task_id} {task.text[:65]}{'…' if len(task.text) > 65 else ''}"
                f" — переносов: {task.postponement_count}{category}"
            )
    else:
        lines.append("  Нет задач с переносами — отличный знак.")

    suggestions = _suggestions(stats)
    if suggestions:
        lines.extend(["", "Предложения"])
        lines.extend(f"  → {suggestion}" for suggestion in suggestions)

    return "\n".join(lines)


def format_weekly_achievements(report: WeeklyAchievementReport) -> str:
    lines = ["🎭 Выданные вам ачивки Комитета по Наблюдению за Продуктивностью"]
    for achievement in report.achievements:
        lines.extend([f"🏆 «{achievement.name}»", achievement.description, ""])
    if report.goal_tasks and report.goal_status == "pending":
        lines.extend(
            [
                "🎯 Новая цель, одобренная без вашего участия",
            ]
        )
        lines.extend(
            f"• #{task_id} {task_text}" if task_id is not None else f"• {task_text}"
            for task_id, task_text in report.goal_tasks
        )
        lines.extend(
            [
                f"Награда за выполнение всей цели: «{report.goal_achievement_name}»",
                str(report.goal_achievement_description),
            ]
        )
    elif report.goal_status == "awarded":
        lines.append("🎯 Цель этой недели уже выполнена. Отдел удивлён, но документы подписаны.")
    else:
        lines.append("🎯 Невыполненных задач нет. Комитет временно лишён смысла существования.")
    return "\n".join(lines).rstrip()


def format_awarded_goal_achievement(award: AwardedGoalAchievement) -> str:
    return (
        f"🏆 Ачивка разблокирована: «{award.name}»\n"
        f"{award.description}\n"
        "Вся цель выполнена:\n"
        + "\n".join(f"• {task_text}" for task_text in award.task_texts)
    )


def _format_daily_stats(stats: PeriodStats) -> list[str]:
    return [
        f"  • {_WEEKDAYS[item.day.weekday()]} {item.day:%d.%m}: "
        f"выполнено {item.completed}"
        for item in stats.daily_completed
    ]


def _suggestions(stats: PeriodStats) -> list[str]:
    suggestions: list[str] = []
    if stats.completed_tasks == 0 and stats.total_tasks > 0:
        suggestions.append("выбрать одну маленькую задачу и закрыть её первой")
    if stats.new_ideas >= 5:
        suggestions.append("отдельно просмотреть идеи и превратить самые важные в задачи")
    if stats.new_unscheduled_tasks >= 5:
        suggestions.append("разобрать список задач без даты и назначить 1–3 ближайшие")
    if stats.stale_tasks and stats.stale_tasks[0].postponement_count >= 3:
        suggestions.append("для часто переносимых задач выбрать: сделать, упростить, делегировать или удалить")
    if stats.categories:
        weakest = min(
            stats.categories,
            key=lambda item: item.completed / item.total if item.total else 0,
        )
        if weakest.total >= 3 and weakest.completed / weakest.total < 0.5:
            suggestions.append(f"проверить категорию «{weakest.name}»: в ней закрыто меньше половины задач")
    return suggestions[:4]
