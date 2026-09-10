from psycopg import Connection
from psycopg.types.json import Jsonb


class PlanningAgentRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create_run(self, *, daily_plan_id: int, trace: list[str]) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO planning_agent_runs (daily_plan_id, trace)
                VALUES (%s, %s) RETURNING id""",
                (daily_plan_id, Jsonb(trace)),
            )
            row = cur.fetchone()
        assert row is not None
        return row["id"]
