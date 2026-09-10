from dataclasses import dataclass
from datetime import datetime

from psycopg import Connection

from app.models.schedule import DailyScheduleRun, ScheduleSlot


@dataclass(frozen=True)
class StoredSchedule:
    run: DailyScheduleRun
    slots: list[ScheduleSlot]


class ScheduleRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def replace_active(
        self,
        *,
        daily_plan_id: int,
        source: str,
        slots: list[tuple[int, int, datetime, datetime, int, str | None]],
    ) -> StoredSchedule:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE daily_schedule_runs
                SET status = 'superseded'
                WHERE daily_plan_id = %s AND status = 'active'
                """,
                (daily_plan_id,),
            )
            cur.execute(
                """
                INSERT INTO daily_schedule_runs (daily_plan_id, source)
                VALUES (%s, %s)
                RETURNING id, daily_plan_id, source, status, created_at, applied_at
                """,
                (daily_plan_id, source),
            )
            run = DailyScheduleRun.model_validate(cur.fetchone())
            cur.executemany(
                """
                INSERT INTO daily_schedule_slots (
                    schedule_run_id, task_id, position, starts_at, ends_at,
                    buffer_after_minutes, reason
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (run.id, task_id, position, starts_at, ends_at, buffer, reason)
                    for task_id, position, starts_at, ends_at, buffer, reason in slots
                ],
            )
        return StoredSchedule(run=run, slots=self.get_slots(run.id))

    def get_active(self, daily_plan_id: int) -> StoredSchedule | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, daily_plan_id, source, status, created_at, applied_at
                FROM daily_schedule_runs
                WHERE daily_plan_id = %s AND status = 'active'
                """,
                (daily_plan_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        run = DailyScheduleRun.model_validate(row)
        return StoredSchedule(run=run, slots=self.get_slots(run.id))

    def get_slots(self, schedule_run_id: int) -> list[ScheduleSlot]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, schedule_run_id, task_id, position, starts_at, ends_at,
                       buffer_after_minutes, reason
                FROM daily_schedule_slots
                WHERE schedule_run_id = %s
                ORDER BY position
                """,
                (schedule_run_id,),
            )
            rows = cur.fetchall()
        return [ScheduleSlot.model_validate(row) for row in rows]

    def invalidate_for_task_ids(self, task_ids: list[int]) -> None:
        if not task_ids:
            return
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE daily_schedule_runs AS run
                SET status = 'stale'
                FROM daily_schedule_slots AS slot
                WHERE slot.schedule_run_id = run.id
                  AND slot.task_id = ANY(%s)
                  AND run.status = 'active'
                """,
                (task_ids,),
            )

    def invalidate_active(self, daily_plan_id: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE daily_schedule_runs SET status = 'stale' WHERE daily_plan_id = %s AND status = 'active'",
                (daily_plan_id,),
            )
