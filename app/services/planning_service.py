from dataclasses import dataclass
from datetime import date

from app.database import Database
from app.models.daily_plan import DailyPlan
from app.models.task import Task
from app.models.user import User
from app.repositories.daily_plan_repository import DailyPlanRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository


@dataclass(frozen=True)
class PlanWithTasks:
    plan: DailyPlan
    tasks: list[Task]


class PlanningService:
    def __init__(self, db: Database, default_timezone: str) -> None:
        self._db = db
        self._default_timezone = default_timezone

    def register_user(self, telegram_id: int, timezone: str | None = None) -> User:
        with self._db.connection() as conn:
            user_repo = UserRepository(conn)
            user = user_repo.create_user(telegram_id, timezone or self._default_timezone)
            conn.commit()
            return user

    def create_plan(
        self,
        telegram_id: int,
        plan_date: date,
        day_type: str,
        tasks: list[str],
    ) -> PlanWithTasks:
        clean_tasks = [task.strip() for task in tasks if task.strip()]
        if not clean_tasks:
            raise ValueError("Enter at least one non-empty task.")

        with self._db.connection() as conn:
            user_repo = UserRepository(conn)
            plan_repo = DailyPlanRepository(conn)
            task_repo = TaskRepository(conn)

            user = user_repo.get_user_by_telegram_id(telegram_id)
            if user is None:
                user = user_repo.create_user(telegram_id, self._default_timezone)

            plan = plan_repo.create_plan(user.id, plan_date, day_type)
            if plan_date <= date.today():
                task_repo.move_overdue_tasks_to_plan(
                    user_id=user.id,
                    target_plan_id=plan.id,
                    target_date=plan_date,
                )
            [task_repo.create_task(plan.id, task_text) for task_text in clean_tasks]
            all_tasks = task_repo.get_visible_tasks(plan.id)
            conn.commit()

        return PlanWithTasks(plan=plan, tasks=all_tasks)

    def get_today_plan(self, telegram_id: int) -> PlanWithTasks | None:
        today = date.today()
        with self._db.connection() as conn:
            user_repo = UserRepository(conn)
            plan_repo = DailyPlanRepository(conn)
            task_repo = TaskRepository(conn)

            user = user_repo.get_user_by_telegram_id(telegram_id)
            if user is None:
                return None

            plan = plan_repo.get_today_plan(user.id, today)
            if plan is None:
                return None

            if today <= date.today():
                task_repo.move_overdue_tasks_to_plan(
                    user_id=user.id,
                    target_plan_id=plan.id,
                    target_date=today,
                )
                conn.commit()
            tasks = task_repo.get_visible_tasks(plan.id)
            return PlanWithTasks(plan=plan, tasks=tasks)
