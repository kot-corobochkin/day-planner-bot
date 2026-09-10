from dataclasses import dataclass
from datetime import date

from app.database import Database
from app.repositories.user_repository import UserRepository


@dataclass(frozen=True)
class CategoryStats:
    name: str
    total: int
    completed: int


@dataclass(frozen=True)
class DailyCompletion:
    day: date
    completed: int


@dataclass(frozen=True)
class StaleTask:
    task_id: int
    text: str
    postponement_count: int
    first_planned_date: date
    category: str | None


@dataclass(frozen=True)
class StatisticsTask:
    task_id: int
    text: str
    status: str
    plan_date: date
    postponement_count: int
    category: str | None


@dataclass(frozen=True)
class PeriodStats:
    start_date: date
    end_date: date
    total_tasks: int
    completed_tasks: int
    completed_new_tasks: int
    completed_active_tasks: int
    new_ideas: int
    new_unscheduled_tasks: int
    daily_completed: list[DailyCompletion]
    categories: list[CategoryStats]
    stale_tasks: list[StaleTask]
    completed_task_items: list[StatisticsTask]
    unfinished_task_items: list[StatisticsTask]


class StatisticsService:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get_period_stats(
        self,
        telegram_id: int,
        start_date: date,
        end_date: date,
    ) -> PeriodStats | None:
        if start_date > end_date:
            raise ValueError("Начало периода не может быть позже его конца.")

        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT days.day::date AS day,
                           COUNT(task.id) FILTER (WHERE task.status = 'done') AS completed
                    FROM generate_series(%s::date, %s::date, interval '1 day') AS days(day)
                    LEFT JOIN daily_plans AS plan
                      ON plan.user_id = %s AND plan.plan_date = days.day::date
                    LEFT JOIN tasks AS task ON task.daily_plan_id = plan.id
                    GROUP BY days.day::date
                    ORDER BY days.day::date
                    """,
                    (start_date, end_date, user.id),
                )
                daily_completed = [
                    DailyCompletion(day=row["day"], completed=int(row["completed"]))
                    for row in cur.fetchall()
                ]

                cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE task.status <> 'cancelled') AS total_tasks,
                        COUNT(*) FILTER (WHERE task.status = 'done') AS completed_tasks,
                        COUNT(*) FILTER (
                            WHERE task.status = 'done'
                              AND task.first_planned_date BETWEEN %s AND %s
                        ) AS completed_new_tasks,
                        COUNT(*) FILTER (
                            WHERE task.status = 'done'
                              AND task.first_planned_date < %s
                        ) AS completed_active_tasks
                    FROM tasks AS task
                    JOIN daily_plans AS plan ON plan.id = task.daily_plan_id
                    WHERE plan.user_id = %s
                      AND plan.plan_date BETWEEN %s AND %s
                    """,
                    (start_date, end_date, start_date, user.id, start_date, end_date),
                )
                summary = cur.fetchone()

                cur.execute(
                    """
                    WITH categorized_tasks AS (
                        SELECT task.status,
                               CASE
                                   WHEN task.category ~* '(^|[[:space:](/-])(https?|ftp)$'
                                       THEN NULL
                                   ELSE task.category
                               END AS category
                        FROM tasks AS task
                        JOIN daily_plans AS plan ON plan.id = task.daily_plan_id
                        WHERE plan.user_id = %s
                          AND plan.plan_date BETWEEN %s AND %s
                    )
                    SELECT
                        COALESCE(NULLIF(TRIM(category), ''), 'Без категории') AS name,
                        COUNT(*) FILTER (WHERE status <> 'cancelled') AS total,
                        COUNT(*) FILTER (WHERE status = 'done') AS completed
                    FROM categorized_tasks
                    GROUP BY COALESCE(NULLIF(TRIM(category), ''), 'Без категории')
                    ORDER BY completed DESC, total DESC, name
                    """,
                    (user.id, start_date, end_date),
                )
                categories = [
                    CategoryStats(
                        name=row["name"],
                        total=int(row["total"]),
                        completed=int(row["completed"]),
                    )
                    for row in cur.fetchall()
                ]

                cur.execute(
                    """
                    SELECT task.id, task.text, task.postponement_count,
                           task.first_planned_date, task.category
                    FROM tasks AS task
                    JOIN daily_plans AS plan ON plan.id = task.daily_plan_id
                    WHERE plan.user_id = %s
                      AND task.status IN ('planned', 'postponed')
                      AND task.postponement_count > 0
                    ORDER BY task.postponement_count DESC,
                             task.first_planned_date ASC, task.id
                    LIMIT 5
                    """,
                    (user.id,),
                )
                stale_tasks = [
                    StaleTask(
                        task_id=int(row["id"]),
                        text=row["text"],
                        postponement_count=int(row["postponement_count"]),
                        first_planned_date=row["first_planned_date"],
                        category=row["category"],
                    )
                    for row in cur.fetchall()
                ]

                cur.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM ideas
                    WHERE user_id = %s AND created_at::date BETWEEN %s AND %s
                    """,
                    (user.id, start_date, end_date),
                )
                new_ideas = int(cur.fetchone()["total"])

                cur.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM unscheduled_tasks
                    WHERE user_id = %s AND created_at::date BETWEEN %s AND %s
                    """,
                    (user.id, start_date, end_date),
                )
                new_unscheduled_tasks = int(cur.fetchone()["total"])

                cur.execute(
                    """
                    SELECT task.id, task.text, task.status, plan.plan_date,
                           task.postponement_count, task.category
                    FROM tasks AS task
                    JOIN daily_plans AS plan ON plan.id = task.daily_plan_id
                    WHERE plan.user_id = %s
                      AND plan.plan_date BETWEEN %s AND %s
                      AND task.status = 'done'
                    ORDER BY plan.plan_date, task.id
                    LIMIT 100
                    """,
                    (user.id, start_date, end_date),
                )
                completed_task_items = [_statistics_task(row) for row in cur.fetchall()]

                cur.execute(
                    """
                    SELECT task.id, task.text, task.status, plan.plan_date,
                           task.postponement_count, task.category
                    FROM tasks AS task
                    JOIN daily_plans AS plan ON plan.id = task.daily_plan_id
                    WHERE plan.user_id = %s
                      AND task.status IN ('planned', 'postponed')
                    ORDER BY task.postponement_count DESC,
                             task.first_planned_date, task.id
                    LIMIT 100
                    """,
                    (user.id,),
                )
                unfinished_task_items = [_statistics_task(row) for row in cur.fetchall()]

        return PeriodStats(
            start_date=start_date,
            end_date=end_date,
            total_tasks=int(summary["total_tasks"]),
            completed_tasks=int(summary["completed_tasks"]),
            completed_new_tasks=int(summary["completed_new_tasks"]),
            completed_active_tasks=int(summary["completed_active_tasks"]),
            new_ideas=new_ideas,
            new_unscheduled_tasks=new_unscheduled_tasks,
            daily_completed=daily_completed,
            categories=categories,
            stale_tasks=stale_tasks,
            completed_task_items=completed_task_items,
            unfinished_task_items=unfinished_task_items,
        )


def _statistics_task(row) -> StatisticsTask:
    return StatisticsTask(
        task_id=int(row["id"]),
        text=row["text"],
        status=row["status"],
        plan_date=row["plan_date"],
        postponement_count=int(row["postponement_count"]),
        category=row["category"],
    )
