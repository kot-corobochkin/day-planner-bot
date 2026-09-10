from dataclasses import dataclass
from datetime import date

from psycopg import Connection
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class StoredAIEstimateDraft:
    id: int
    proposals: list[dict]


class AIEstimateDraftRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def replace_pending(
        self,
        *,
        user_id: int,
        plan_date: date,
        proposals: list[tuple[int, dict]],
    ) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai_estimate_drafts
                SET status = 'superseded', updated_at = now()
                WHERE user_id = %s AND plan_date = %s AND status = 'pending'
                """,
                (user_id, plan_date),
            )
            cur.execute(
                """
                INSERT INTO ai_estimate_drafts (user_id, plan_date)
                VALUES (%s, %s)
                RETURNING id
                """,
                (user_id, plan_date),
            )
            draft_id = cur.fetchone()["id"]
            cur.executemany(
                """
                INSERT INTO ai_estimate_draft_items (draft_id, task_id, proposal)
                VALUES (%s, %s, %s)
                """,
                [(draft_id, task_id, Jsonb(proposal)) for task_id, proposal in proposals],
            )
        return draft_id

    def get_pending(self, *, user_id: int, plan_date: date) -> StoredAIEstimateDraft | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai_estimate_drafts
                SET status = 'expired', updated_at = now()
                WHERE user_id = %s AND plan_date = %s
                  AND status = 'pending' AND expires_at <= now()
                """,
                (user_id, plan_date),
            )
            cur.execute(
                """
                SELECT draft.id, item.proposal
                FROM ai_estimate_drafts AS draft
                JOIN ai_estimate_draft_items AS item ON item.draft_id = draft.id
                WHERE draft.user_id = %s AND draft.plan_date = %s
                  AND draft.status = 'pending' AND draft.expires_at > now()
                  AND item.decision = 'pending'
                ORDER BY item.task_id
                """,
                (user_id, plan_date),
            )
            rows = cur.fetchall()
        if not rows:
            return None
        return StoredAIEstimateDraft(
            id=rows[0]["id"], proposals=[row["proposal"] for row in rows]
        )

    def invalidate_for_task_ids(self, task_ids: list[int]) -> None:
        if not task_ids:
            return
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai_estimate_drafts AS draft
                SET status = 'stale', updated_at = now()
                FROM ai_estimate_draft_items AS item
                WHERE item.draft_id = draft.id
                  AND item.task_id = ANY(%s)
                  AND draft.status = 'pending'
                """,
                (task_ids,),
            )

    def mark_applied(self, *, draft_id: int, user_id: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai_estimate_draft_items AS item
                SET decision = 'applied'
                FROM ai_estimate_drafts AS draft
                WHERE item.draft_id = draft.id
                  AND draft.id = %s AND draft.user_id = %s
                  AND item.decision = 'pending'
                """,
                (draft_id, user_id),
            )
            cur.execute(
                """
                UPDATE ai_estimate_drafts
                SET status = 'applied', updated_at = now()
                WHERE id = %s AND user_id = %s AND status = 'pending'
                """,
                (draft_id, user_id),
            )

    def decide_item(
        self, *, draft_id: int, task_id: int, user_id: int, decision: str
    ) -> bool:
        if decision not in {"applied", "dismissed"}:
            raise ValueError("Unsupported AI estimate decision.")
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai_estimate_draft_items AS item
                SET decision = %s
                FROM ai_estimate_drafts AS draft
                WHERE item.draft_id = draft.id
                  AND draft.id = %s AND item.task_id = %s
                  AND draft.user_id = %s AND draft.status = 'pending'
                  AND item.decision = 'pending'
                RETURNING item.task_id
                """,
                (decision, draft_id, task_id, user_id),
            )
            return cur.fetchone() is not None

    def is_pending(self, *, draft_id: int, user_id: int) -> bool:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM ai_estimate_drafts
                WHERE id = %s AND user_id = %s
                  AND status = 'pending' AND expires_at > now()
                """,
                (draft_id, user_id),
            )
            return cur.fetchone() is not None
