from dataclasses import dataclass
from datetime import date

from app.database import Database
from app.models.idea import Idea
from app.models.task import Task
from app.models.unscheduled_task import UnscheduledTask
from app.repositories.daily_plan_repository import DailyPlanRepository
from app.repositories.idea_repository import IdeaRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.unscheduled_task_repository import UnscheduledTaskRepository
from app.repositories.user_repository import UserRepository
from app.services.day_capacity import default_available_minutes
from app.services.task_input_parser import TaskDraft


@dataclass(frozen=True)
class UpcomingTasks:
    dated_tasks: list[tuple[Task, date]]
    unscheduled_tasks: list[UnscheduledTask]
    unscheduled_remaining: int


class CaptureService:
    def __init__(self, db: Database, default_timezone: str) -> None:
        self._db = db
        self._default_timezone = default_timezone

    def add_idea(self, telegram_id: int, text: str) -> Idea:
        return self.add_ideas(telegram_id, [text])[0]

    def add_ideas(self, telegram_id: int, texts: list[str]) -> list[Idea]:
        clean_texts = [text.strip() for text in texts if text.strip()]
        if not clean_texts:
            raise ValueError("Введите хотя бы одну идею.")
        if any(len(text) > 1000 for text in clean_texts):
            raise ValueError("Каждая идея должна содержать не более 1000 символов.")
        with self._db.connection() as conn:
            user = self._get_or_create_user(conn, telegram_id)
            idea_repo = IdeaRepository(conn)
            ideas = [idea_repo.create(user.id, text) for text in clean_texts]
            conn.commit()
        return ideas

    def list_ideas(self, telegram_id: int, limit: int = 30) -> list[Idea]:
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            return IdeaRepository(conn).list_for_user(user.id, limit) if user else []

    def add_unscheduled_task(self, telegram_id: int, task: TaskDraft) -> UnscheduledTask:
        if task.start_time or task.due_time:
            raise ValueError(
                "Для задачи без даты нельзя указать время начала или дедлайн."
            )
        with self._db.connection() as conn:
            user = self._get_or_create_user(conn, telegram_id)
            unscheduled_task = UnscheduledTaskRepository(conn).create(user.id, task)
            conn.commit()
        return unscheduled_task

    def list_unscheduled_tasks(
        self,
        telegram_id: int,
        limit: int = 30,
    ) -> list[UnscheduledTask]:
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            return UnscheduledTaskRepository(conn).list_for_user(user.id, limit) if user else []

    def get_upcoming_tasks(self, telegram_id: int, limit: int = 30) -> UpcomingTasks:
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return UpcomingTasks([], [], 0)
            task_repo = TaskRepository(conn)
            dated_tasks = task_repo.get_future_tasks(user.id, date.today(), limit)
            remaining_slots = max(0, limit - len(dated_tasks))
            unscheduled_repo = UnscheduledTaskRepository(conn)
            unscheduled_tasks = unscheduled_repo.list_for_user(user.id, remaining_slots)
            unscheduled_total = unscheduled_repo.count_for_user(user.id)
        return UpcomingTasks(
            dated_tasks=dated_tasks,
            unscheduled_tasks=unscheduled_tasks,
            unscheduled_remaining=max(0, unscheduled_total - len(unscheduled_tasks)),
        )

    def schedule_unscheduled_task(
        self,
        task_id: int,
        *,
        telegram_id: int,
        target_date: date,
    ) -> Task | None:
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            unscheduled_repo = UnscheduledTaskRepository(conn)
            unscheduled = unscheduled_repo.delete_for_user(task_id, user.id)
            if unscheduled is None:
                return None
            plan = DailyPlanRepository(conn).ensure_plan(
                user.id,
                target_date,
                available_minutes=default_available_minutes("Смешанный"),
            )
            task = TaskRepository(conn).create_task(
                plan.id,
                unscheduled.text,
                first_planned_date=target_date,
                estimated_minutes=unscheduled.estimated_minutes,
                priority=unscheduled.priority,
                effort=unscheduled.effort,
                context=unscheduled.context,
            )
            conn.commit()
        return task

    def schedule_idea(
        self,
        idea_id: int,
        *,
        telegram_id: int,
        target_date: date,
    ) -> Task | None:
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            idea = IdeaRepository(conn).delete_for_user(idea_id, user.id)
            if idea is None:
                return None
            plan = DailyPlanRepository(conn).ensure_plan(
                user.id,
                target_date,
                available_minutes=default_available_minutes("Смешанный"),
            )
            task = TaskRepository(conn).create_task(
                plan.id,
                idea.text,
                first_planned_date=target_date,
            )
            conn.commit()
        return task

    def _get_or_create_user(self, conn, telegram_id: int):
        user_repo = UserRepository(conn)
        user = user_repo.get_user_by_telegram_id(telegram_id)
        return user or user_repo.create_user(telegram_id, self._default_timezone)
