from psycopg import Connection


class PlanFeedbackRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(self, *, daily_plan_id: int, text: str) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO plan_feedback (daily_plan_id, text) VALUES (%s, %s) RETURNING id",
                (daily_plan_id, text),
            )
            row = cur.fetchone()
        assert row is not None
        return row["id"]
