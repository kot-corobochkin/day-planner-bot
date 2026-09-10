from dataclasses import dataclass
from datetime import date

from app.database import Database
from app.models.task import Task, TaskStatus, TaskValueSource
from app.models.daily_plan import DailyPlan
from app.models.user import User
from app.models.schedule import DailyScheduleRun, ScheduleSlot
from app.repositories.daily_plan_repository import DailyPlanRepository
from app.repositories.ai_estimate_draft_repository import AIEstimateDraftRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.day_state_repository import DayStateRepository
from app.repositories.ai_reflection_repository import AIReflectionRepository
from app.repositories.evening_reflection_repository import EveningReflectionRepository
from app.repositories.planning_agent_repository import PlanningAgentRepository
from app.repositories.planning_agent_checkpoint_repository import PlanningAgentCheckpointRepository
from app.repositories.plan_feedback_repository import PlanFeedbackRepository
from app.repositories.user_repository import UserRepository
from app.repositories.unscheduled_task_repository import UnscheduledTaskRepository
from app.services.task_input_parser import TaskDraft, TaskUpdate
from app.services.ai_estimation import dump_estimates, load_draft_estimates
from app.services.feasibility import PlanFeasibility, analyze_plan_feasibility
from app.services.day_capacity import available_minutes_for_date, default_available_minutes
from app.services.task_category import extract_task_category


@dataclass(frozen=True)
class TaskStats:
    total: int
    completed: int
    postponed: int
    cancelled: int
    completion_percentage: int


@dataclass(frozen=True)
class TaskDetails:
    task: Task
    plan_date: date


@dataclass(frozen=True)
class ScheduleContext:
    plan: DailyPlan
    user: User
    tasks: list[Task]
    available_minutes: int


@dataclass(frozen=True)
class ActiveSchedule:
    run: DailyScheduleRun
    slots: list[tuple[ScheduleSlot, Task]]


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

    def get_visible_tasks_for_date(
        self,
        telegram_id: int,
        plan_date: date,
    ) -> list[Task]:
        with self._db.connection() as conn:
            plan_id = self._get_plan_id(conn, telegram_id, plan_date)
            if plan_id is None:
                return []
            return TaskRepository(conn).get_visible_tasks(plan_id)

    def get_planned_tasks_by_category(
        self, telegram_id: int, category: str, start_date: date, end_date: date
    ):
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return []
            return TaskRepository(conn).get_planned_tasks_by_category(
                user_id=user.id, category=category, start_date=start_date, end_date=end_date
            )

    def get_task_details(self, task_id: int, telegram_id: int) -> TaskDetails | None:
        with self._db.connection() as conn:
            details = TaskRepository(conn).get_task_details(task_id, telegram_id)
        if details is None:
            return None
        task, plan_date = details
        return TaskDetails(task=task, plan_date=plan_date)

    def analyze_feasibility(
        self,
        telegram_id: int,
        plan_date: date,
        available_minutes: int | None = None,
    ) -> PlanFeasibility | None:
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            plan_repo = DailyPlanRepository(conn)
            plan = plan_repo.get_today_plan(user.id, plan_date)
            if plan is None:
                return None
            base_available_minutes = (
                available_minutes
                if available_minutes is not None
                else plan.available_minutes or default_available_minutes(plan.day_type)
            )
            if available_minutes is not None:
                plan_repo.set_available_minutes(plan.id, available_minutes)
            tasks = TaskRepository(conn).get_tasks(plan.id)
            conn.commit()
        return analyze_plan_feasibility(
            tasks,
            available_minutes=available_minutes_for_date(
                base_available_minutes,
                plan_date,
                user.timezone,
            ),
        )

    def get_available_minutes(self, telegram_id: int, plan_date: date) -> int | None:
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            plan = DailyPlanRepository(conn).get_today_plan(user.id, plan_date)
            if plan is None:
                return None
        return available_minutes_for_date(
            plan.available_minutes or default_available_minutes(plan.day_type),
            plan_date,
            user.timezone,
        )

    def update_task(
        self,
        task_id: int,
        *,
        telegram_id: int,
        update: TaskUpdate,
    ) -> TaskDetails | None:
        with self._db.connection() as conn:
            task_repo = TaskRepository(conn)
            details = task_repo.get_task_details(task_id, telegram_id)
            if details is None:
                return None
            current_task, plan_date = details
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None

            changes = self._build_task_changes(
                current_task,
                plan_date=plan_date,
                timezone=user.timezone,
                update=update,
            )
            updated_task = task_repo.update_task(task_id, telegram_id, changes)
            if updated_task is not None:
                AIEstimateDraftRepository(conn).invalidate_for_task_ids([task_id])
                ScheduleRepository(conn).invalidate_for_task_ids([task_id])
            conn.commit()
        return TaskDetails(task=updated_task, plan_date=plan_date) if updated_task else None

    def get_unfinished_tasks_for_today(self, telegram_id: int) -> list[Task]:
        return self.get_unfinished_tasks_for_date(telegram_id, date.today())

    def mark_done(self, task_id: int, telegram_id: int) -> Task | None:
        with self._db.connection() as conn:
            task_repo = TaskRepository(conn)
            task = task_repo.mark_done(task_id, telegram_id)
            if task is not None:
                AIEstimateDraftRepository(conn).invalidate_for_task_ids([task_id])
                ScheduleRepository(conn).invalidate_for_task_ids([task_id])
            conn.commit()
            return task

    def apply_ai_estimates(self, telegram_id: int, estimates, selected_task_ids: set[int]) -> list[Task]:
        updated: list[Task] = []
        with self._db.connection() as conn:
            repository = TaskRepository(conn)
            for estimate in estimates:
                if estimate.task.id not in selected_task_ids:
                    continue
                details = repository.get_task_details(estimate.task.id, telegram_id)
                if details is None:
                    continue
                task, _ = details
                changes = estimate.applicable_changes
                if not changes:
                    continue
                if "priority" in changes and task.priority_source != TaskValueSource.user:
                    changes["priority_source"] = TaskValueSource.ai_confirmed
                if "effort" in changes and task.effort_source != TaskValueSource.user:
                    changes["effort_source"] = TaskValueSource.ai_confirmed
                if "estimated_minutes" in changes and task.duration_source != TaskValueSource.user:
                    changes["duration_source"] = TaskValueSource.ai_confirmed
                changed = repository.update_task(estimate.task.id, telegram_id, changes)
                if changed:
                    updated.append(changed)
            conn.commit()
        return updated

    def get_schedule_context(self, telegram_id: int, plan_date: date) -> ScheduleContext | None:
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            plan = DailyPlanRepository(conn).get_today_plan(user.id, plan_date)
            if plan is None:
                return None
            tasks = [
                task
                for task in TaskRepository(conn).get_visible_tasks(plan.id)
                if task.status == TaskStatus.planned
            ]
        available = available_minutes_for_date(
            plan.available_minutes or default_available_minutes(plan.day_type),
            plan_date,
            user.timezone,
        )
        return ScheduleContext(
            plan=plan,
            user=user,
            tasks=tasks,
            available_minutes=available,
        )

    def save_day_state(self, telegram_id: int, plan_date: date, **values):
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            plan = DailyPlanRepository(conn).get_today_plan(user.id, plan_date)
            if plan is None:
                return None
            profile = DayStateRepository(conn).upsert(daily_plan_id=plan.id, **values)
            conn.commit()
        return profile

    def get_day_state(self, telegram_id: int, plan_date: date):
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            plan = DailyPlanRepository(conn).get_today_plan(user.id, plan_date)
            if plan is None:
                return None
            return DayStateRepository(conn).get(plan.id)

    def record_ai_reflection(self, telegram_id: int, plan_date: date, **values) -> int | None:
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            plan = DailyPlanRepository(conn).get_today_plan(user.id, plan_date)
            if plan is None:
                return None
            reflection_id = AIReflectionRepository(conn).create(daily_plan_id=plan.id, **values)
            conn.commit()
        return reflection_id

    def decide_ai_reflection(self, telegram_id: int, plan_date: date, reflection_id: int | None, decision: str) -> None:
        if reflection_id is None:
            return
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return
            plan = DailyPlanRepository(conn).get_today_plan(user.id, plan_date)
            if plan is not None:
                AIReflectionRepository(conn).decide(
                    reflection_id=reflection_id, daily_plan_id=plan.id, decision=decision
                )
                conn.commit()

    def get_pending_evening_reflection(self, telegram_id: int, plan_date: date):
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            return EveningReflectionRepository(conn).get_pending(user_id=user.id, plan_date=plan_date)

    def create_evening_reflection(self, telegram_id: int, plan_date: date, *, questions: list[str], source: str):
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            plan = DailyPlanRepository(conn).get_today_plan(user.id, plan_date)
            if plan is None:
                return None
            reflection = EveningReflectionRepository(conn).create(
                daily_plan_id=plan.id, questions=questions, source=source
            )
            conn.commit()
        return reflection

    def answer_evening_reflection(self, reflection_id: int, answer: str):
        with self._db.connection() as conn:
            reflection = EveningReflectionRepository(conn).append_answer(
                reflection_id=reflection_id, answer=answer
            )
            conn.commit()
        return reflection

    def record_planning_agent_run(self, telegram_id: int, plan_date: date, trace: list[str]) -> int | None:
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            plan = DailyPlanRepository(conn).get_today_plan(user.id, plan_date)
            if plan is None:
                return None
            run_id = PlanningAgentRepository(conn).create_run(daily_plan_id=plan.id, trace=trace)
            conn.commit()
        return run_id

    def get_recent_plan_history(self, telegram_id: int, before_date: date, limit: int = 14) -> list[dict]:
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return []
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT plan.plan_date, COUNT(task.id) AS total,
                        COUNT(task.id) FILTER (WHERE task.status = 'done') AS completed
                    FROM daily_plans AS plan
                    LEFT JOIN tasks AS task ON task.daily_plan_id = plan.id
                    WHERE plan.user_id = %s AND plan.plan_date < %s
                    GROUP BY plan.id, plan.plan_date
                    ORDER BY plan.plan_date DESC LIMIT %s""",
                    (user.id, before_date, limit),
                )
                rows = cur.fetchall()
        return [
            {
                "date": row["plan_date"].isoformat(),
                "total": row["total"],
                "completed": row["completed"],
                "completion_percentage": round((row["completed"] / row["total"]) * 100) if row["total"] else 0,
            }
            for row in rows
        ]

    def save_planning_agent_checkpoint(self, telegram_id: int, plan_date: date, *, failed_step: str, context: dict, error: str) -> int | None:
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            plan = DailyPlanRepository(conn).get_today_plan(user.id, plan_date)
            if plan is None:
                return None
            checkpoint_id = PlanningAgentCheckpointRepository(conn).create(
                daily_plan_id=plan.id, failed_step=failed_step, context=context, error=error
            )
            conn.commit()
        return checkpoint_id

    def consume_planning_agent_checkpoint(self, telegram_id: int, checkpoint_id: int):
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            row = PlanningAgentCheckpointRepository(conn).consume(
                checkpoint_id=checkpoint_id, user_id=user.id
            )
            conn.commit()
        return row

    def save_plan_feedback(self, telegram_id: int, plan_date: date, text: str) -> bool:
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return False
            plan = DailyPlanRepository(conn).get_today_plan(user.id, plan_date)
            if plan is None:
                return False
            PlanFeedbackRepository(conn).create(daily_plan_id=plan.id, text=text)
            ScheduleRepository(conn).invalidate_active(plan.id)
            conn.commit()
        return True

    def apply_ai_schedule(self, telegram_id: int, plan_date: date, slots) -> ActiveSchedule | None:
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            plan = DailyPlanRepository(conn).get_today_plan(user.id, plan_date)
            if plan is None:
                return None
            tasks_by_id = {
                task.id: task
                for task in TaskRepository(conn).get_visible_tasks(plan.id)
                if task.status == TaskStatus.planned
            }
            if any(slot.task.id not in tasks_by_id for slot in slots):
                raise ValueError("Одна из задач плана была изменена. Создайте порядок заново.")
            stored = ScheduleRepository(conn).replace_active(
                daily_plan_id=plan.id,
                source="ai",
                slots=[
                    (
                        slot.task.id,
                        slot.position,
                        slot.starts_at,
                        slot.ends_at,
                        slot.buffer_after_minutes,
                        None,
                    )
                    for slot in slots
                ],
            )
            conn.commit()
        return ActiveSchedule(
            run=stored.run,
            slots=[(slot, tasks_by_id[slot.task_id]) for slot in stored.slots],
        )

    def get_active_schedule(self, telegram_id: int, plan_date: date) -> ActiveSchedule | None:
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            plan = DailyPlanRepository(conn).get_today_plan(user.id, plan_date)
            if plan is None:
                return None
            stored = ScheduleRepository(conn).get_active(plan.id)
            if stored is None:
                return None
            tasks_by_id = {
                task.id: task for task in TaskRepository(conn).get_visible_tasks(plan.id)
            }
            if any(slot.task_id not in tasks_by_id for slot in stored.slots):
                ScheduleRepository(conn).invalidate_for_task_ids([slot.task_id for slot in stored.slots])
                conn.commit()
                return None
        return ActiveSchedule(
            run=stored.run,
            slots=[(slot, tasks_by_id[slot.task_id]) for slot in stored.slots],
        )

    def save_ai_estimate_draft(self, telegram_id: int, plan_date: date, estimates) -> int | None:
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            draft_id = AIEstimateDraftRepository(conn).replace_pending(
                user_id=user.id,
                plan_date=plan_date,
                proposals=dump_estimates(estimates),
            )
            conn.commit()
        return draft_id

    def get_ai_estimate_draft(self, telegram_id: int, plan_date: date):
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return None
            plan_id = self._get_plan_id(conn, telegram_id, plan_date)
            if plan_id is None:
                return None
            repository = AIEstimateDraftRepository(conn)
            draft = repository.get_pending(user_id=user.id, plan_date=plan_date)
            if draft is None:
                conn.commit()
                return None
            tasks = [
                task for task in TaskRepository(conn).get_visible_tasks(plan_id)
                if task.status == TaskStatus.planned
            ]
            try:
                estimates = load_draft_estimates(tasks, draft.proposals)
            except ValueError:
                repository.invalidate_for_task_ids([task.id for task in tasks])
                conn.commit()
                return None
            conn.commit()
        return draft.id, estimates

    def mark_ai_estimate_draft_applied(self, telegram_id: int, draft_id: int | None) -> None:
        if draft_id is None:
            return
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is not None:
                AIEstimateDraftRepository(conn).mark_applied(draft_id=draft_id, user_id=user.id)
                conn.commit()

    def decide_ai_estimate_item(
        self,
        telegram_id: int,
        draft_id: int | None,
        task_id: int,
        decision: str,
    ) -> bool:
        if draft_id is None:
            return False
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return False
            changed = AIEstimateDraftRepository(conn).decide_item(
                draft_id=draft_id,
                task_id=task_id,
                user_id=user.id,
                decision=decision,
            )
            conn.commit()
        return changed

    def is_ai_estimate_draft_active(self, telegram_id: int, draft_id: int | None) -> bool:
        if draft_id is None:
            return False
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return False
            return AIEstimateDraftRepository(conn).is_pending(
                draft_id=draft_id, user_id=user.id
            )

    def cancel_task(self, task_id: int, telegram_id: int) -> Task | None:
        with self._db.connection() as conn:
            task_repo = TaskRepository(conn)
            task = task_repo.cancel_task(task_id, telegram_id)
            if task is not None:
                AIEstimateDraftRepository(conn).invalidate_for_task_ids([task_id])
                ScheduleRepository(conn).invalidate_for_task_ids([task_id])
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
            AIEstimateDraftRepository(conn).invalidate_for_task_ids([task.id for task in tasks])
            ScheduleRepository(conn).invalidate_for_task_ids([task.id for task in tasks])
            conn.commit()
            return tasks

    def move_tasks_to_backlog(self, task_ids: list[int], *, telegram_id: int) -> list[Task]:
        """Move active dated tasks to the user's list of tasks without a date."""
        with self._db.connection() as conn:
            user = UserRepository(conn).get_user_by_telegram_id(telegram_id)
            if user is None:
                return []
            tasks = TaskRepository(conn).extract_planned_tasks(
                task_ids, telegram_id=telegram_id
            )
            backlog = UnscheduledTaskRepository(conn)
            for task in tasks:
                backlog.create(
                    user.id,
                    TaskDraft(
                        text=task.text,
                        estimated_minutes=task.estimated_minutes or 60,
                        priority=task.priority,
                        effort=task.effort,
                        context=task.context,
                        priority_source=task.priority_source,
                        effort_source=task.effort_source,
                        duration_source=task.duration_source,
                    ),
                )
            moved_ids = [task.id for task in tasks]
            AIEstimateDraftRepository(conn).invalidate_for_task_ids(moved_ids)
            ScheduleRepository(conn).invalidate_for_task_ids(moved_ids)
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

    @staticmethod
    def _build_task_changes(
        current_task: Task,
        *,
        plan_date: date,
        timezone: str,
        update: TaskUpdate,
    ) -> dict[str, object]:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        changes: dict[str, object] = {}
        if "название" in update.provided_fields:
            changes["text"] = update.text
            changes["category"] = extract_task_category(update.text or "")
        if "длительность" in update.provided_fields:
            changes["estimated_minutes"] = update.estimated_minutes
            changes["duration_source"] = TaskValueSource.user
        if "важность" in update.provided_fields:
            changes["priority"] = update.priority
            changes["priority_source"] = TaskValueSource.user
        if "сложность" in update.provided_fields:
            changes["effort"] = update.effort
            changes["effort_source"] = TaskValueSource.user
        if "контекст" in update.provided_fields:
            changes["context"] = update.context
        if "статус" in update.provided_fields:
            changes["status"] = update.status

        zone = ZoneInfo(timezone)
        starts_at = current_task.starts_at
        due_at = current_task.due_at
        if "время начала" in update.provided_fields:
            starts_at = (
                datetime.combine(plan_date, update.start_time, tzinfo=zone)
                if update.start_time
                else None
            )
            changes["starts_at"] = starts_at
        if "дедлайн" in update.provided_fields:
            due_at = (
                datetime.combine(plan_date, update.due_time, tzinfo=zone)
                if update.due_time
                else None
            )
            changes["due_at"] = due_at
        if starts_at and due_at and due_at <= starts_at:
            raise ValueError("Дедлайн должен быть позже времени начала.")
        return changes
