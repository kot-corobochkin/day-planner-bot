from dataclasses import dataclass
from datetime import date

from psycopg import Connection
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class StoredEveningReflection:
    id: int
    questions: list[str]
    answers: list[str]
    source: str
    status: str


class EveningReflectionRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def get_pending(self, *, user_id: int, plan_date: date) -> StoredEveningReflection | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """SELECT reflection.id, reflection.questions, reflection.answers,
                    reflection.source, reflection.status
                FROM evening_reflections AS reflection
                JOIN daily_plans AS plan ON plan.id = reflection.daily_plan_id
                WHERE plan.user_id = %s AND plan.plan_date = %s AND reflection.status = 'pending'
                ORDER BY reflection.created_at DESC LIMIT 1""",
                (user_id, plan_date),
            )
            row = cur.fetchone()
        return StoredEveningReflection(**row) if row else None

    def create(self, *, daily_plan_id: int, questions: list[str], source: str) -> StoredEveningReflection:
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO evening_reflections (daily_plan_id, questions, source)
                VALUES (%s, %s, %s)
                RETURNING id, questions, answers, source, status""",
                (daily_plan_id, Jsonb(questions), source),
            )
            row = cur.fetchone()
        assert row is not None
        return StoredEveningReflection(**row)

    def append_answer(self, *, reflection_id: int, answer: str) -> StoredEveningReflection | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """UPDATE evening_reflections
                SET answers = answers || jsonb_build_array(%s::text),
                    status = CASE WHEN jsonb_array_length(answers) + 1 >= 10 THEN 'completed' ELSE 'pending' END,
                    completed_at = CASE WHEN jsonb_array_length(answers) + 1 >= 10 THEN now() ELSE NULL END
                WHERE id = %s AND status = 'pending'
                RETURNING id, questions, answers, source, status""",
                (answer, reflection_id),
            )
            row = cur.fetchone()
        return StoredEveningReflection(**row) if row else None
