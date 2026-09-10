from psycopg import Connection
from psycopg.types.json import Jsonb


class AIReflectionRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(self, *, daily_plan_id: int, original_task_ids: list[int], reflected_task_ids: list[int],
               is_acceptable: bool, observations: list[str], user_message: str) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ai_plan_reflections (
                    daily_plan_id, original_task_ids, reflected_task_ids, is_acceptable,
                    observations, user_message
                ) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                (daily_plan_id, Jsonb(original_task_ids), Jsonb(reflected_task_ids), is_acceptable,
                 Jsonb(observations), user_message),
            )
            row = cur.fetchone()
        assert row is not None
        return row["id"]

    def decide(self, *, reflection_id: int, daily_plan_id: int, decision: str) -> bool:
        if decision not in {"reflected_applied", "original_applied", "dismissed"}:
            raise ValueError("Unsupported AI reflection decision.")
        with self._conn.cursor() as cur:
            cur.execute(
                """UPDATE ai_plan_reflections SET decision = %s, decided_at = now()
                WHERE id = %s AND daily_plan_id = %s AND decision = 'pending' RETURNING id""",
                (decision, reflection_id, daily_plan_id),
            )
            return cur.fetchone() is not None
