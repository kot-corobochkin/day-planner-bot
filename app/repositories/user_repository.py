from psycopg import Connection

from app.models.user import User


class UserRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create_user(self, telegram_id: int, timezone: str) -> User:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (telegram_id, timezone)
                VALUES (%s, %s)
                ON CONFLICT (telegram_id) DO UPDATE
                SET timezone = EXCLUDED.timezone
                RETURNING id, telegram_id, timezone, created_at
                """,
                (telegram_id, timezone),
            )
            row = cur.fetchone()
        return User.model_validate(row)

    def get_user_by_telegram_id(self, telegram_id: int) -> User | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, telegram_id, timezone, created_at
                FROM users
                WHERE telegram_id = %s
                """,
                (telegram_id,),
            )
            row = cur.fetchone()
        return User.model_validate(row) if row else None

    def list_users(self) -> list[User]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, telegram_id, timezone, created_at
                FROM users
                ORDER BY id
                """
            )
            rows = cur.fetchall()
        return [User.model_validate(row) for row in rows]

