from dataclasses import dataclass
from datetime import date

from app.database import Database
from app.models.task import Task, TaskStatus
from app.repositories.daily_plan_repository import DailyPlanRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository


@dataclass(frozen=True)
class TaskStats:
    total: int
    completed: int
    postponed: int
    cancelled: int
    completion_percentage: int


class TaskService:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get_unfinished_tasks_for_date(
        self,
        telegram_id: int,
        plan_date: date,
    ) -> list[Task]:
        with self._db.connection() as conn:
            plan_id = self._get_plan_id(conn, telegram_id, plan_date)
            if plan_id is None:
                return []
            return TaskRepository(conn).get_unfinished_tasks(plan_id)

    def get_unfinished_tasks_for_today(self, telegram_id: int) -> list[Task]:
        return self.get_unfinished_tasks_for_date(telegram_id, date.today())

    def mark_done(self, task_id: int, telegram_id: int) -> Task | None:
        with self._db.connection() as conn:
            task_repo = TaskRepository(conn)
            task = task_repo.mark_done(task_id, telegram_id)
            conn.commit()
            return task

    def cancel_task(self, task_id: int, telegram_id: int) -> Task | None:
        with self._db.connection() as conn:
            task_repo = TaskRepository(conn)
            task = task_repo.cancel_task(task_id, telegram_id)
            conn.commit()
            return task

    def move_tasks(
        self,
        task_ids: list[int],
        *,
        telegram_id: int,
        target_date: date,
    ) -> list[Task]:
        with self._db.connection() as conn:
            user_repo = UserRepository(conn)
            user = user_repo.get_user_by_telegram_id(telegram_id)
            if user is None:
                return []
            target_plan = DailyPlanRepository(conn).ensure_plan(
                user.id,
                target_date,
            )
            tasks = TaskRepository(conn).move_tasks(
                task_ids,
                telegram_id=telegram_id,
                target_plan_id=target_plan.id,
            )
            conn.commit()
            return tasks

    def get_stats_for_today(self, telegram_id: int) -> TaskStats | None:
        with self._db.connection() as conn:
            plan_id = self._get_plan_id(conn, telegram_id, date.today())
            if plan_id is None:
                return None
            tasks = TaskRepository(conn).get_tasks(plan_id)

        total = len(tasks)
        completed = len([task for task in tasks if task.status == TaskStatus.done])
        postponed = len([task for task in tasks if task.status == TaskStatus.postponed])
        cancelled = len([task for task in tasks if task.status == TaskStatus.cancelled])
        completion_percentage = round((completed / total) * 100) if total else 0

        return TaskStats(
            total=total,
            completed=completed,
            postponed=postponed,
            cancelled=cancelled,
            completion_percentage=completion_percentage,
        )

    def _get_plan_id(self, conn, telegram_id: int, plan_date: date) -> int | None:
        user_repo = UserRepository(conn)
        plan_repo = DailyPlanRepository(conn)

        user = user_repo.get_user_by_telegram_id(telegram_id)
        if user is None:
            return None

        plan = plan_repo.get_today_plan(user.id, plan_date)
        if plan is None:
            return None

        return plan.id
