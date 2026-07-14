from datetime import date

from psycopg import Connection

from app.models.task import Task, TaskStatus


class TaskRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create_task(self, daily_plan_id: int, text: str) -> Task:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tasks (daily_plan_id, text)
                VALUES (%s, %s)
                RETURNING id, daily_plan_id, text, status, created_at, updated_at
                """,
                (daily_plan_id, text),
            )
            row = cur.fetchone()
        return Task.model_validate(row)

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
                    updated_at = now()
                FROM daily_plans AS source_plan
                WHERE task.daily_plan_id = source_plan.id
                  AND source_plan.user_id = %s
                  AND source_plan.plan_date < %s
                  AND task.status = %s
                RETURNING task.id, task.daily_plan_id, task.text, task.status,
                          task.created_at, task.updated_at
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
                SELECT id, daily_plan_id, text, status, created_at, updated_at
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
                SELECT id, daily_plan_id, text, status, created_at, updated_at
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
                SELECT id, daily_plan_id, text, status, created_at, updated_at
                FROM tasks
                WHERE daily_plan_id = %s AND status <> %s
                ORDER BY id
                """,
                (daily_plan_id, TaskStatus.cancelled.value),
            )
            rows = cur.fetchall()
        return [Task.model_validate(row) for row in rows]

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
                    updated_at = now()
                FROM daily_plans AS source_plan, users
                WHERE task.id = ANY(%s)
                  AND task.daily_plan_id = source_plan.id
                  AND source_plan.user_id = users.id
                  AND users.telegram_id = %s
                  AND task.status = %s
                RETURNING task.id, task.daily_plan_id, task.text, task.status,
                          task.created_at, task.updated_at
                """,
                (target_plan_id, task_ids, telegram_id, TaskStatus.planned.value),
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
                          task.created_at, task.updated_at
                """,
                (status.value, task_id, telegram_id, TaskStatus.planned.value),
            )
            row = cur.fetchone()
        return Task.model_validate(row) if row else None
