from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.models.task import Task, TaskStatus


NEUTRAL_PRIORITY_SCORE = 50
ELEVATED_PRIORITY_SCORE = 55


@dataclass(frozen=True)
class PriorityBreakdown:
    importance: int
    deadline: int
    postponements: int
    dependencies: int = 0

    @property
    def modifiers_total(self) -> int:
        return self.importance + self.deadline + self.postponements + self.dependencies


@dataclass(frozen=True)
class TaskPriorityAssessment:
    task: Task
    breakdown: PriorityBreakdown

    @property
    def score(self) -> int:
        return max(0, min(100, NEUTRAL_PRIORITY_SCORE + self.breakdown.modifiers_total))

    @property
    def emoji(self) -> str | None:
        if self.task.status != TaskStatus.planned:
            return None
        if self.score >= 80:
            return "🔴"
        if self.score >= 65:
            return "🟠"
        if self.score >= ELEVATED_PRIORITY_SCORE:
            return "🟡"
        return None


def assess_task(task: Task, *, now: datetime | None = None) -> TaskPriorityAssessment:
    reference_time = now or datetime.now(UTC)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=UTC)

    # Dependencies are not modelled yet, so their modifier remains zero.
    breakdown = PriorityBreakdown(
        importance=(task.priority - 5) * 4,
        deadline=_deadline_score(task, reference_time),
        postponements=_postponement_score(task.postponement_count),
    )
    return TaskPriorityAssessment(task=task, breakdown=breakdown)


def explain_priority_factors(
    assessment: TaskPriorityAssessment,
) -> list[tuple[str, int, str]]:
    """Return only modifiers that changed the neutral 50-point priority."""
    task = assessment.task
    breakdown = assessment.breakdown
    factors: list[tuple[str, int, str]] = []
    if breakdown.importance:
        factors.append(("Важность", breakdown.importance, f"важность {task.priority}/10"))
    if breakdown.deadline:
        factors.append(("Дедлайн", breakdown.deadline, _deadline_reason(breakdown.deadline)))
    if breakdown.postponements:
        factors.append(
            ("Переносы", breakdown.postponements, f"переносов: {task.postponement_count}")
        )
    if breakdown.dependencies:
        factors.append(("Зависимости", breakdown.dependencies, "есть зависимые задачи"))
    return factors


def order_tasks_by_priority(
    tasks: list[Task], *, now: datetime | None = None
) -> list[TaskPriorityAssessment]:
    assessments = [assess_task(task, now=now) for task in tasks]
    elevated = sorted(
        (
            assessment
            for assessment in assessments
            if assessment.task.status == TaskStatus.planned
            and assessment.score >= ELEVATED_PRIORITY_SCORE
        ),
        key=lambda assessment: (-assessment.score, assessment.task.id),
    )
    elevated_ids = {assessment.task.id for assessment in elevated}
    return elevated + [
        assessment for assessment in assessments if assessment.task.id not in elevated_ids
    ]


def _deadline_score(task: Task, now: datetime) -> int:
    if task.due_at is None:
        return 0
    if task.due_at <= now:
        return 35
    remaining = task.due_at - now
    if remaining <= timedelta(hours=2):
        return 30
    if remaining <= timedelta(hours=6):
        return 20
    if remaining <= timedelta(hours=24):
        return 15
    if remaining <= timedelta(days=3):
        return 10
    if remaining <= timedelta(days=7):
        return 5
    return 0


def _postponement_score(postponement_count: int) -> int:
    if postponement_count >= 3:
        return 8
    return postponement_count * 3


def _deadline_reason(score: int) -> str:
    return {
        35: "дедлайн уже просрочен",
        30: "дедлайн в ближайшие 2 часа",
        20: "дедлайн в ближайшие 6 часов",
        15: "дедлайн в ближайшие 24 часа",
        10: "дедлайн в ближайшие 3 дня",
        5: "дедлайн в ближайшие 7 дней",
    }[score]
