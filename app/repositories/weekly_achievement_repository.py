from datetime import date

from psycopg import Connection
from psycopg.types.json import Jsonb


class WeeklyAchievementRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def get_for_week(self, *, user_id: int, week_start: date):
        with self._conn.cursor() as cur:
            cur.execute(
                """SELECT id, week_start, week_end, earned_achievements,
                          goal_achievement_name,
                          goal_achievement_description, goal_status, goal_awarded_at
                   FROM weekly_achievement_reports
                   WHERE user_id = %s AND week_start = %s""",
                (user_id, week_start),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                """SELECT task_id, task_text
                   FROM weekly_achievement_goal_tasks
                   WHERE report_id = %s
                   ORDER BY position""",
                (row["id"],),
            )
            result = dict(row)
            result["goal_tasks"] = cur.fetchall()
            return result

    def create(
        self,
        *,
        user_id: int,
        week_start: date,
        week_end: date,
        earned_achievements: list[dict[str, str]],
        goal_tasks: list[tuple[int, str]],
        goal_achievement_name: str | None,
        goal_achievement_description: str | None,
    ):
        with self._conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (user_id,))
            existing = self.get_for_week(user_id=user_id, week_start=week_start)
            if existing is not None:
                return existing
            cur.execute(
                """UPDATE weekly_achievement_reports
                   SET goal_status = 'expired'
                   WHERE user_id = %s AND goal_status = 'pending'""",
                (user_id,),
            )
            cur.execute(
                """INSERT INTO weekly_achievement_reports (
                       user_id, week_start, week_end, earned_achievements,
                       goal_achievement_name,
                       goal_achievement_description, goal_status
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                   RETURNING id, week_start, week_end, earned_achievements,
                             goal_achievement_name,
                             goal_achievement_description, goal_status, goal_awarded_at""",
                (
                    user_id,
                    week_start,
                    week_end,
                    Jsonb(earned_achievements),
                    goal_achievement_name,
                    goal_achievement_description,
                    "pending" if goal_tasks else "none",
                ),
            )
            row = cur.fetchone()
            assert row is not None
            if goal_tasks:
                cur.executemany(
                    """INSERT INTO weekly_achievement_goal_tasks (
                           report_id, task_id, task_text, position
                       ) VALUES (%s, %s, %s, %s)""",
                    [
                        (row["id"], task_id, task_text, position)
                        for position, (task_id, task_text) in enumerate(goal_tasks, start=1)
                    ],
                )
        return self.get_for_week(user_id=user_id, week_start=week_start)

    def award_for_task(self, *, user_id: int, task_id: int):
        with self._conn.cursor() as cur:
            cur.execute(
                """UPDATE weekly_achievement_reports AS report
                   SET goal_status = 'awarded', goal_awarded_at = now()
                   WHERE report.user_id = %s
                     AND report.goal_status = 'pending'
                     AND EXISTS (
                         SELECT 1 FROM weekly_achievement_goal_tasks AS selected
                         WHERE selected.report_id = report.id AND selected.task_id = %s
                     )
                     AND NOT EXISTS (
                         SELECT 1
                         FROM weekly_achievement_goal_tasks AS goal_task
                         LEFT JOIN tasks AS task ON task.id = goal_task.task_id
                         WHERE goal_task.report_id = report.id
                           AND (task.id IS NULL OR task.status <> 'done')
                     )
                   RETURNING report.id, report.goal_achievement_name,
                             report.goal_achievement_description""",
                (user_id, task_id),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                """SELECT task_text
                   FROM weekly_achievement_goal_tasks
                   WHERE report_id = %s ORDER BY position""",
                (row["id"],),
            )
            result = dict(row)
            result["goal_task_texts"] = [item["task_text"] for item in cur.fetchall()]
            return result
