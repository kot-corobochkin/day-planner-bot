import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.bot.statistics import format_awarded_goal_achievement, format_weekly_achievements
from app.services.statistics_service import (
    CategoryStats,
    DailyCompletion,
    PeriodStats,
    StatisticsTask,
)
from app.services.weekly_achievements import (
    Achievement,
    AwardedGoalAchievement,
    WeeklyAchievementReport,
    WeeklyAchievementResponse,
    _build_prompt,
)


def _stats() -> PeriodStats:
    return PeriodStats(
        start_date=date(2026, 7, 27),
        end_date=date(2026, 8, 2),
        total_tasks=3,
        completed_tasks=2,
        completed_new_tasks=1,
        completed_active_tasks=1,
        new_ideas=4,
        new_unscheduled_tasks=1,
        daily_completed=[DailyCompletion(day=date(2026, 8, 1), completed=2)],
        categories=[CategoryStats(name="Работа", total=3, completed=2)],
        stale_tasks=[],
        completed_task_items=[
            StatisticsTask(
                task_id=10,
                text="Отправить отчёт",
                status="done",
                plan_date=date(2026, 8, 1),
                postponement_count=0,
                category="Работа",
            )
        ],
        unfinished_task_items=[
            StatisticsTask(
                task_id=11,
                text="Разобрать почту",
                status="planned",
                plan_date=date(2026, 8, 2),
                postponement_count=3,
                category="Работа",
            )
        ],
    )


def test_weekly_prompt_contains_completed_and_unfinished_tasks() -> None:
    prompt = json.loads(_build_prompt(_stats()))

    assert prompt["completed_tasks"] == [
        {"id": 10, "title": "Отправить отчёт", "date": "2026-08-01"}
    ]
    assert prompt["unfinished_tasks"][0]["id"] == 11
    assert prompt["statistics"]["completed_tasks"] == 2


def test_weekly_prompt_limits_task_volume_and_title_length() -> None:
    stats = _stats()
    stats = PeriodStats(
        **{
            **stats.__dict__,
            "completed_task_items": [
                StatisticsTask(
                    task_id=index,
                    text="в" * 500,
                    status="done",
                    plan_date=date(2026, 8, 1),
                    postponement_count=0,
                    category=None,
                )
                for index in range(40)
            ],
            "unfinished_task_items": [
                StatisticsTask(
                    task_id=index,
                    text="н" * 500,
                    status="planned",
                    plan_date=date(2026, 8, 2),
                    postponement_count=0,
                    category=None,
                )
                for index in range(40)
            ],
        }
    )

    prompt = json.loads(_build_prompt(stats))

    assert len(prompt["completed_tasks"]) == 30
    assert len(prompt["unfinished_tasks"]) == 30
    assert max(len(item["title"]) for item in prompt["completed_tasks"]) == 200
    assert max(len(item["title"]) for item in prompt["unfinished_tasks"]) == 200


def test_future_achievement_is_required_when_model_selects_a_goal() -> None:
    with pytest.raises(ValidationError):
        WeeklyAchievementResponse(
            achievements=[{"name": "Отдел доволен", "description": "Это ненадолго."}],
            goal_task_ids=[11, 12],
            goal_achievement_name=None,
            goal_achievement_description=None,
        )


def test_weekly_and_unlocked_achievement_formatting() -> None:
    report = WeeklyAchievementReport(
        achievements=[Achievement(name="Два из трёх", description="Система ожидала меньше.")],
        goal_tasks=[(11, "Разобрать почту"), (12, "Ответить на важные письма")],
        goal_achievement_name="Археолог входящих",
        goal_achievement_description="Папка увидела дно и теперь жалеет об этом.",
        goal_status="pending",
    )
    weekly_text = format_weekly_achievements(report)
    unlocked_text = format_awarded_goal_achievement(
        AwardedGoalAchievement(
            task_texts=["Разобрать почту", "Ответить на важные письма"],
            name="Археолог входящих",
            description="Папка увидела дно и теперь жалеет об этом.",
        )
    )

    assert "🏆 «Два из трёх»" in weekly_text
    assert "Награда за выполнение всей цели: «Археолог входящих»" in weekly_text
    assert "#12 Ответить на важные письма" in weekly_text
    assert "Ачивка разблокирована: «Археолог входящих»" in unlocked_text


def test_weekly_achievement_migration_preserves_one_active_goal() -> None:
    migration = Path("app/db/migrations/020_add_weekly_achievement_reports.sql").read_text()

    assert "UNIQUE (user_id, week_start)" in migration
    assert "WHERE goal_status = 'pending'" in migration
    assert "goal_awarded_at" in migration
    assert "weekly_achievement_goal_tasks" in migration
