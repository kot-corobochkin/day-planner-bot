from psycopg import Connection

from app.models.idea import Idea


class IdeaRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(self, user_id: int, text: str) -> Idea:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ideas (user_id, text)
                VALUES (%s, %s)
                RETURNING id, user_id, text, created_at
                """,
                (user_id, text),
            )
            row = cur.fetchone()
        return Idea.model_validate(row)

    def list_for_user(self, user_id: int, limit: int) -> list[Idea]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, text, created_at
                FROM ideas
                WHERE user_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
            rows = cur.fetchall()
        return [Idea.model_validate(row) for row in rows]

    def delete_for_user(self, idea_id: int, user_id: int) -> Idea | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM ideas
                WHERE id = %s AND user_id = %s
                RETURNING id, user_id, text, created_at
                """,
                (idea_id, user_id),
            )
            row = cur.fetchone()
        return Idea.model_validate(row) if row else None
