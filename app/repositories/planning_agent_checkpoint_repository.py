from psycopg import Connection
from psycopg.types.json import Jsonb


class PlanningAgentCheckpointRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(self, *, daily_plan_id: int, failed_step: str, context: dict, error: str) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO planning_agent_checkpoints (daily_plan_id, failed_step, context, error)
                VALUES (%s, %s, %s, %s) RETURNING id""",
                (daily_plan_id, failed_step, Jsonb(context), error),
            )
            row = cur.fetchone()
        assert row is not None
        return row["id"]

    def consume(self, *, checkpoint_id: int, user_id: int) -> dict | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """UPDATE planning_agent_checkpoints AS checkpoint
                SET status = 'consumed', consumed_at = now()
                FROM daily_plans AS plan
                WHERE checkpoint.id = %s AND checkpoint.daily_plan_id = plan.id
                  AND plan.user_id = %s AND checkpoint.status = 'pending'
                RETURNING plan.plan_date, checkpoint.context, checkpoint.failed_step""",
                (checkpoint_id, user_id),
            )
            return cur.fetchone()
