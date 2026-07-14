from datetime import date

from psycopg import Connection

from app.models.daily_plan import DailyPlan


class DailyPlanRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create_plan(self, user_id: int, plan_date: date, day_type: str) -> DailyPlan:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO daily_plans (user_id, plan_date, day_type)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, plan_date) DO UPDATE
                SET day_type = EXCLUDED.day_type
                RETURNING id, user_id, plan_date, day_type, created_at
                """,
                (user_id, plan_date, day_type),
            )
            row = cur.fetchone()
        return DailyPlan.model_validate(row)

    def ensure_plan(
        self,
        user_id: int,
        plan_date: date,
        *,
        day_type: str = "Смешанный",
    ) -> DailyPlan:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO daily_plans (user_id, plan_date, day_type)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, plan_date) DO NOTHING
                RETURNING id, user_id, plan_date, day_type, created_at
                """,
                (user_id, plan_date, day_type),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    """
                    SELECT id, user_id, plan_date, day_type, created_at
                    FROM daily_plans
                    WHERE user_id = %s AND plan_date = %s
                    """,
                    (user_id, plan_date),
                )
                row = cur.fetchone()
        assert row is not None
        return DailyPlan.model_validate(row)

    def get_today_plan(self, user_id: int, plan_date: date) -> DailyPlan | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, plan_date, day_type, created_at
                FROM daily_plans
                WHERE user_id = %s AND plan_date = %s
                """,
                (user_id, plan_date),
            )
            row = cur.fetchone()
        return DailyPlan.model_validate(row) if row else None
