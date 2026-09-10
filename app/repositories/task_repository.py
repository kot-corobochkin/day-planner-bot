from datetime import date
from datetime import datetime

from psycopg import Connection

from app.models.task import Task, TaskStatus


class TaskRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create_task(
        self,
        daily_plan_id: int,
        text: str,
        *,
        first_planned_date: date,
        estimated_minutes: int | None = None,
        due_at: datetime | None = None,
        starts_at: datetime | None = None,
        priority: int = 5,
        effort: int = 5,
        context: str | None = None,
        category: str | None = None,
        priority_source: str = "default",
        effort_source: str = "default",
        duration_source: str = "default",
    ) -> Task:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tasks (
                    daily_plan_id, text, first_planned_date, estimated_minutes, starts_at, due_at,
                    priority, effort, context, category, priority_source, effort_source, duration_source
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, daily_plan_id, text, status, first_planned_date,
                          postponement_count, estimated_minutes, starts_at, due_at, priority,
                          effort, priority_source, effort_source, duration_source, context, category,
                          created_at, updated_at
                """,
                (
                    daily_plan_id,
                    text,
                    first_planned_date,
                    estimated_minutes,
                    starts_at,
                    due_at,
                    priority,
                    effort,
                    context,
                    category,
                    priority_source,
                    effort_source,
                    duration_source,
                ),
            )
            row = cur.fetchone()
        return Task.model_validate(row)

    def get_planned_tasks_by_category(
        self, *, user_id: int, category: str, start_date: date, end_date: date
    ) -> list[tuple[Task, date]]:
        with self._conn.cursor() as cur:
            cur.execute(
                """SELECT task.id, task.daily_plan_id, task.text, task.status,
                    task.first_planned_date, task.postponement_count, task.estimated_minutes,
                    task.starts_at, task.due_at, task.priority, task.effort,
                    task.priority_source, task.effort_source, task.duration_source,
                    task.context, task.category, task.created_at, task.updated_at, plan.plan_date
                FROM tasks AS task JOIN daily_plans AS plan ON plan.id = task.daily_plan_id
                WHERE plan.user_id = %s AND task.status = %s
                  AND LOWER(task.category) = LOWER(%s)
                  AND plan.plan_date BETWEEN %s AND %s
                ORDER BY plan.plan_date, task.id""",
                (user_id, TaskStatus.planned.value, category, start_date, end_date),
            )
            rows = cur.fetchall()
        return [(Task.model_validate(row), row["plan_date"]) for row in rows]

    def move_overdue_tasks_to_plan(
        self,
        *,
        user_id: int,
        target_plan_id: int,
        target_date: date,
    ) -> list[Task]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tasks AS task
                SET daily_plan_id = %s,
                    postponement_count = task.postponement_count + 1,
                    updated_at = now()
                FROM daily_plans AS source_plan
                WHERE task.daily_plan_id = source_plan.id
                  AND source_plan.user_id = %s
                  AND source_plan.plan_date < %s
                  AND task.status = %s
                RETURNING task.id, task.daily_plan_id, task.text, task.status,
                          task.first_planned_date, task.postponement_count,
                          task.estimated_minutes, task.starts_at, task.due_at, task.priority,
                          task.effort, task.priority_source, task.effort_source,
                          task.duration_source, task.context, task.created_at, task.updated_at
                """,
                (
                    target_plan_id,
                    user_id,
                    target_date,
                    TaskStatus.planned.value,
                ),
            )
            rows = cur.fetchall()
        return [Task.model_validate(row) for row in rows]

    def get_tasks(self, daily_plan_id: int) -> list[Task]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, daily_plan_id, text, status, first_planned_date, postponement_count,
                       estimated_minutes, starts_at, due_at, priority, effort, priority_source,
                       effort_source, duration_source, context,
                       created_at, updated_at
                FROM tasks
                WHERE daily_plan_id = %s
                ORDER BY id
                """,
                (daily_plan_id,),
            )
            rows = cur.fetchall()
        return [Task.model_validate(row) for row in rows]

    def get_unfinished_tasks(self, daily_plan_id: int) -> list[Task]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, daily_plan_id, text, status, first_planned_date, postponement_count,
                       estimated_minutes, starts_at, due_at, priority, effort, priority_source,
                       effort_source, duration_source, context,
                       created_at, updated_at
                FROM tasks
                WHERE daily_plan_id = %s AND status = %s
                ORDER BY id
                """,
                (daily_plan_id, TaskStatus.planned.value),
            )
            rows = cur.fetchall()
        return [Task.model_validate(row) for row in rows]

    def get_visible_tasks(self, daily_plan_id: int) -> list[Task]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, daily_plan_id, text, status, first_planned_date, postponement_count,
                       estimated_minutes, starts_at, due_at, priority, effort, priority_source,
                       effort_source, duration_source, context,
                       created_at, updated_at
                FROM tasks
                WHERE daily_plan_id = %s AND status <> %s
                ORDER BY id
                """,
                (daily_plan_id, TaskStatus.cancelled.value),
            )
            rows = cur.fetchall()
        return [Task.model_validate(row) for row in rows]

    def get_future_tasks(
        self,
        user_id: int,
        from_date: date,
        limit: int,
    ) -> list[tuple[Task, date]]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT task.id, task.daily_plan_id, task.text, task.status,
                       task.first_planned_date, task.postponement_count,
                       task.estimated_minutes, task.starts_at, task.due_at, task.priority,
                       task.effort, task.priority_source, task.effort_source,
                       task.duration_source, task.context, task.created_at, task.updated_at,
                       plan.plan_date
                FROM tasks AS task
                JOIN daily_plans AS plan ON task.daily_plan_id = plan.id
                WHERE plan.user_id = %s
                  AND plan.plan_date > %s
                  AND task.status = %s
                ORDER BY plan.plan_date, task.id
                LIMIT %s
                """,
                (user_id, from_date, TaskStatus.planned.value, limit),
            )
            rows = cur.fetchall()
        return [(Task.model_validate(row), row["plan_date"]) for row in rows]

    def get_task_details(
        self,
        task_id: int,
        telegram_id: int,
    ) -> tuple[Task, date] | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT task.id, task.daily_plan_id, task.text, task.status,
                       task.first_planned_date, task.postponement_count,
                       task.estimated_minutes, task.starts_at, task.due_at, task.priority,
                       task.effort, task.priority_source, task.effort_source,
                       task.duration_source, task.context, task.created_at, task.updated_at,
                       plan.plan_date
                FROM tasks AS task
                JOIN daily_plans AS plan ON task.daily_plan_id = plan.id
                JOIN users ON plan.user_id = users.id
                WHERE task.id = %s
                  AND users.telegram_id = %s
                  AND task.status <> %s
                """,
                (task_id, telegram_id, TaskStatus.cancelled.value),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return Task.model_validate(row), row["plan_date"]

    def update_task(
        self,
        task_id: int,
        telegram_id: int,
        changes: dict[str, object],
    ) -> Task | None:
        allowed_columns = {
            "text",
            "estimated_minutes",
            "starts_at",
            "due_at",
            "priority",
            "effort",
            "priority_source",
            "effort_source",
            "duration_source",
            "context",
            "status",
            "category",
        }
        if not changes or not set(changes).issubset(allowed_columns):
            raise ValueError("Invalid task update.")

        assignments = ", ".join(f"{column} = %s" for column in changes)
        values = [
            value.value if isinstance(value, TaskStatus) else value
            for value in changes.values()
        ]
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE tasks AS task
                SET {assignments}, updated_at = now()
                FROM daily_plans AS plan, users
                WHERE task.id = %s
                  AND task.daily_plan_id = plan.id
                  AND plan.user_id = users.id
                  AND users.telegram_id = %s
                  AND task.status <> %s
                RETURNING task.id, task.daily_plan_id, task.text, task.status,
                          task.first_planned_date, task.postponement_count,
                          task.estimated_minutes, task.starts_at, task.due_at, task.priority,
                          task.effort, task.priority_source, task.effort_source,
                          task.duration_source, task.context, task.created_at, task.updated_at
                """,
                (*values, task_id, telegram_id, TaskStatus.cancelled.value),
            )
            row = cur.fetchone()
        return Task.model_validate(row) if row else None

    def mark_done(self, task_id: int, telegram_id: int) -> Task | None:
        return self._update_status(task_id, telegram_id, TaskStatus.done)

    def cancel_task(self, task_id: int, telegram_id: int) -> Task | None:
        return self._update_status(task_id, telegram_id, TaskStatus.cancelled)

    def move_tasks(
        self,
        task_ids: list[int],
        *,
        telegram_id: int,
        target_plan_id: int,
    ) -> list[Task]:
        if not task_ids:
            return []
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tasks AS task
                SET daily_plan_id = %s,
                    postponement_count = task.postponement_count + 1,
                    updated_at = now()
                FROM daily_plans AS source_plan, users
                WHERE task.id = ANY(%s)
                  AND task.daily_plan_id = source_plan.id
                  AND source_plan.user_id = users.id
                  AND users.telegram_id = %s
                  AND task.status = %s
                RETURNING task.id, task.daily_plan_id, task.text, task.status,
                          task.first_planned_date, task.postponement_count,
                          task.estimated_minutes, task.starts_at, task.due_at, task.priority,
                          task.effort, task.priority_source, task.effort_source,
                          task.duration_source, task.context, task.created_at, task.updated_at
                """,
                (target_plan_id, task_ids, telegram_id, TaskStatus.planned.value),
            )
            rows = cur.fetchall()
        return [Task.model_validate(row) for row in rows]

    def extract_planned_tasks(
        self,
        task_ids: list[int],
        *,
        telegram_id: int,
    ) -> list[Task]:
        """Delete selected active tasks and return their data for moving to the backlog."""
        if not task_ids:
            return []
        with self._conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM tasks AS task
                USING daily_plans AS plan, users
                WHERE task.id = ANY(%s)
                  AND task.daily_plan_id = plan.id
                  AND plan.user_id = users.id
                  AND users.telegram_id = %s
                  AND task.status = %s
                RETURNING task.id, task.daily_plan_id, task.text, task.status,
                          task.first_planned_date, task.postponement_count,
                          task.estimated_minutes, task.starts_at, task.due_at, task.priority,
                          task.effort, task.priority_source, task.effort_source,
                          task.duration_source, task.context, task.created_at, task.updated_at
                """,
                (task_ids, telegram_id, TaskStatus.planned.value),
            )
            rows = cur.fetchall()
        return [Task.model_validate(row) for row in rows]

    def _update_status(
        self,
        task_id: int,
        telegram_id: int,
        status: TaskStatus,
    ) -> Task | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tasks AS task
                SET status = %s, updated_at = now()
                FROM daily_plans AS plan, users
                WHERE task.id = %s
                  AND task.daily_plan_id = plan.id
                  AND plan.user_id = users.id
                  AND users.telegram_id = %s
                  AND task.status = %s
                RETURNING task.id, task.daily_plan_id, task.text, task.status,
                          task.first_planned_date, task.postponement_count,
                          task.estimated_minutes, task.starts_at, task.due_at, task.priority,
                          task.effort, task.priority_source, task.effort_source,
                          task.duration_source, task.context, task.created_at, task.updated_at
                """,
                (status.value, task_id, telegram_id, TaskStatus.planned.value),
            )
            row = cur.fetchone()
        return Task.model_validate(row) if row else None
