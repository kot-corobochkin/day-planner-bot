from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.database import Database
from app.models.daily_plan import DailyPlan
from app.models.task import Task
from app.models.user import User
from app.repositories.daily_plan_repository import DailyPlanRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository
from app.services.task_input_parser import TaskDraft
from app.services.day_capacity import default_available_minutes
from app.services.task_category import extract_task_category


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
        tasks: list[TaskDraft],
    ) -> PlanWithTasks:
        if not tasks:
            raise ValueError("Enter at least one non-empty task.")

        with self._db.connection() as conn:
            user_repo = UserRepository(conn)
            plan_repo = DailyPlanRepository(conn)
            task_repo = TaskRepository(conn)

            user = user_repo.get_user_by_telegram_id(telegram_id)
            if user is None:
                user = user_repo.create_user(telegram_id, self._default_timezone)

            plan = plan_repo.create_plan(
                user.id,
                plan_date,
                day_type,
                default_available_minutes(day_type),
            )
            if plan_date <= date.today():
                task_repo.move_overdue_tasks_to_plan(
                    user_id=user.id,
                    target_plan_id=plan.id,
                    target_date=plan_date,
                )
            timezone = ZoneInfo(user.timezone)
            for task in tasks:
                task_repo.create_task(
                    plan.id,
                    task.text,
                    first_planned_date=plan_date,
                    estimated_minutes=task.estimated_minutes,
                    starts_at=_combine_local_time(plan_date, task.start_time, timezone),
                    due_at=_combine_local_time(plan_date, task.due_time, timezone),
                    priority=task.priority,
                    effort=task.effort,
                    context=task.context,
                    category=extract_task_category(task.text),
                    priority_source=task.priority_source,
                    effort_source=task.effort_source,
                    duration_source=task.duration_source,
                )
            all_tasks = task_repo.get_visible_tasks(plan.id)
            conn.commit()

        return PlanWithTasks(plan=plan, tasks=all_tasks)

    def get_plan_for_date(self, telegram_id: int, plan_date: date) -> DailyPlan | None:
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            return DailyPlanRepository(conn).get_today_plan(user.id, plan_date)

    def get_plan_with_tasks_for_date(
        self,
        telegram_id: int,
        plan_date: date,
    ) -> PlanWithTasks | None:
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            plan = DailyPlanRepository(conn).get_today_plan(user.id, plan_date)
            if plan is None:
                return None
            tasks = TaskRepository(conn).get_visible_tasks(plan.id)
        return PlanWithTasks(plan=plan, tasks=tasks)

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
                plan = plan_repo.ensure_plan(
                    user.id,
                    today,
                    day_type="Смешанный",
                    available_minutes=default_available_minutes("Смешанный"),
                )

            task_repo.move_overdue_tasks_to_plan(
                user_id=user.id,
                target_plan_id=plan.id,
                target_date=today,
            )
            conn.commit()
            tasks = task_repo.get_visible_tasks(plan.id)
            return PlanWithTasks(plan=plan, tasks=tasks)


def _combine_local_time(
    plan_date: date,
    value: time | None,
    timezone: ZoneInfo,
) -> datetime | None:
    return datetime.combine(plan_date, value, tzinfo=timezone) if value else None
