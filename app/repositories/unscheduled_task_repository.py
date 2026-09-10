from psycopg import Connection

from app.models.unscheduled_task import UnscheduledTask
from app.services.task_input_parser import TaskDraft


class UnscheduledTaskRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(self, user_id: int, task: TaskDraft) -> UnscheduledTask:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO unscheduled_tasks (user_id, text, estimated_minutes, priority, effort, context)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, user_id, text, estimated_minutes, priority, effort, context,
                          created_at, updated_at
                """,
                (
                    user_id,
                    task.text,
                    task.estimated_minutes,
                    task.priority,
                    task.effort,
                    task.context,
                ),
            )
            row = cur.fetchone()
        return UnscheduledTask.model_validate(row)

    def list_for_user(self, user_id: int, limit: int) -> list[UnscheduledTask]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, text, estimated_minutes, priority, effort, context,
                       created_at, updated_at
                FROM unscheduled_tasks
                WHERE user_id = %s
                ORDER BY created_at, id
                LIMIT %s
                """,
                (user_id, limit),
            )
            rows = cur.fetchall()
        return [UnscheduledTask.model_validate(row) for row in rows]

    def count_for_user(self, user_id: int) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS total FROM unscheduled_tasks WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
        return int(row["total"])

    def delete_for_user(self, task_id: int, user_id: int) -> UnscheduledTask | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM unscheduled_tasks
                WHERE id = %s AND user_id = %s
                RETURNING id, user_id, text, estimated_minutes, priority, effort, context,
                          created_at, updated_at
                """,
                (task_id, user_id),
            )
            row = cur.fetchone()
        return UnscheduledTask.model_validate(row) if row else None
