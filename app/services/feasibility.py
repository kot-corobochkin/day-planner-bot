from dataclasses import dataclass

from app.models.task import Task, TaskStatus
from app.services.task_prioritization import assess_task


@dataclass(frozen=True)
class FeasibilityCandidate:
    task: Task
    priority_score: int
    has_near_deadline: bool
    has_fixed_start: bool


@dataclass(frozen=True)
class MoveRecommendation:
    tasks: list[FeasibilityCandidate]
    freed_minutes: int
    ambiguous: bool
    ambiguous_task_count: int = 0


@dataclass(frozen=True)
class PlanFeasibility:
    available_minutes: int
    scheduled_minutes: int
    unknown_duration_count: int
    remaining_minutes: int
    move_candidates: list[FeasibilityCandidate]
    planned_tasks: list[Task]

    @property
    def is_overloaded(self) -> bool:
        return self.remaining_minutes < 0


def analyze_plan_feasibility(
    tasks: list[Task], *, available_minutes: int
) -> PlanFeasibility:
    planned_tasks = [task for task in tasks if task.status == TaskStatus.planned]
    known_duration_tasks = [
        task for task in planned_tasks if task.estimated_minutes is not None
    ]
    scheduled_minutes = sum(task.estimated_minutes or 0 for task in known_duration_tasks)
    remaining_minutes = available_minutes - scheduled_minutes
    candidates = [_candidate_for(task) for task in known_duration_tasks]

    return PlanFeasibility(
        available_minutes=available_minutes,
        scheduled_minutes=scheduled_minutes,
        unknown_duration_count=len(planned_tasks) - len(known_duration_tasks),
        remaining_minutes=remaining_minutes,
        move_candidates=candidates,
        planned_tasks=planned_tasks,
    )


def recommend_moves(result: PlanFeasibility) -> MoveRecommendation:
    """Choose movable low-priority tasks, while retaining ambiguity information."""
    required_minutes = max(0, -result.remaining_minutes)
    if not required_minutes:
        return MoveRecommendation(tasks=[], freed_minutes=0, ambiguous=False)

    preferred = [
        candidate
        for candidate in result.move_candidates
        if not candidate.has_near_deadline and not candidate.has_fixed_start
    ]
    pool = preferred or result.move_candidates
    ordered = sorted(
        pool,
        key=lambda candidate: (
            candidate.priority_score,
            candidate.has_near_deadline,
            candidate.has_fixed_start,
            -(candidate.task.estimated_minutes or 0),
            candidate.task.id,
        ),
    )
    selected: list[FeasibilityCandidate] = []
    freed_minutes = 0
    for candidate in ordered:
        selected.append(candidate)
        freed_minutes += candidate.task.estimated_minutes or 0
        if freed_minutes >= required_minutes:
            break

    selected_keys = {
        _candidate_comparison_key(candidate)
        for candidate in selected
    }
    unselected_keys = {
        _candidate_comparison_key(candidate)
        for candidate in ordered
        if candidate not in selected
    }
    ambiguous_keys = selected_keys & unselected_keys
    ambiguous_task_count = sum(
        _candidate_comparison_key(candidate) in ambiguous_keys for candidate in ordered
    )
    return MoveRecommendation(
        tasks=selected,
        freed_minutes=freed_minutes,
        ambiguous=bool(ambiguous_keys),
        ambiguous_task_count=ambiguous_task_count,
    )


def _candidate_for(task: Task) -> FeasibilityCandidate:
    assessment = assess_task(task)
    return FeasibilityCandidate(
        task=task,
        priority_score=assessment.score,
        has_near_deadline=assessment.breakdown.deadline > 0,
        has_fixed_start=task.starts_at is not None,
    )


def _candidate_comparison_key(candidate: FeasibilityCandidate) -> tuple[int, bool, bool, int]:
    return (
        candidate.priority_score,
        candidate.has_near_deadline,
        candidate.has_fixed_start,
        candidate.task.estimated_minutes or 0,
    )
