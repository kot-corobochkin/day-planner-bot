import json
import time as clock
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from app.models.task import Task, TaskStatus
from app.services.llm_provider import LLMProvider, LLMProviderError
from app.services.task_prioritization import assess_task


BUFFER_MINUTES = 15


class AIPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ordered_task_ids: list[int] = Field(min_length=1)


@dataclass(frozen=True)
class AIPlanProposal:
    ordered_tasks: list[Task]
    deferred_tasks: list[tuple[Task, str]]


@dataclass(frozen=True)
class ProposedScheduleSlot:
    task: Task
    position: int
    starts_at: datetime
    ends_at: datetime
    buffer_after_minutes: int


@dataclass(frozen=True)
class CalculatedSchedule:
    slots: list[ProposedScheduleSlot]
    deferred_tasks: list[tuple[Task, str]]
    available_minutes: int
    scheduled_minutes: int


class AIPlanningService:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        debug_log_path: Path = Path("data/debug/ai_plan_errors.jsonl"),
    ) -> None:
        self._provider = provider
        self._debug_log_path = debug_log_path

    def propose(self, tasks: list[Task], *, available_minutes: int, day_state=None, planning_context=None) -> AIPlanProposal:
        for attempt in range(3):
            try:
                response = self._provider.generate_json(
                    system_prompt=(
                        "Сформируй реалистичный порядок выполнения задач на один день. "
                        "Детерминированный priority_score уже рассчитан: не меняй и не пересчитывай его. "
                        "Учитывай длительность, сложность, фиксированное время начала, реальный дедлайн, "
                        "неопределённость и доступное время. Зависимости не заданы: не выдумывай их. "
                        "Верни каждый переданный task_id ровно один раз в ordered_task_ids: "
                        "это полный порядок всех задач, а Python отдельно решит, что помещается. "
                        "Не опускай высокоприоритетную задачу без веской причины. "
                        "Если в дополнительном контексте есть цели дня, ставь связанные с ними задачи выше, "
                        "если это не нарушает фиксированное время и реальные дедлайны. "
                        "Верни только JSON, соответствующий схеме, без Markdown и без инструментов."
                    ),
                    user_prompt=_build_prompt(tasks, available_minutes, day_state, planning_context),
                    response_model=AIPlanResponse,
                )
                return validate_plan_proposal(tasks, response)
            except (LLMProviderError, ValueError) as error:
                self._write_debug_error(tasks, available_minutes, attempt + 1, error)
                if attempt == 2 or not _is_retryable(error):
                    raise type(error)(f"AI plan failed: {error}") from error
                clock.sleep(2**attempt)
        raise AssertionError("unreachable")

    def _write_debug_error(
        self,
        tasks: list[Task],
        available_minutes: int,
        attempt: int,
        error: Exception,
    ) -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "attempt": attempt,
            "task_ids": [task.id for task in tasks],
            "task_count": len(tasks),
            "available_minutes": available_minutes,
            "error": str(error),
        }
        try:
            self._debug_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._debug_log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass


def validate_plan_proposal(tasks: list[Task], response: AIPlanResponse) -> AIPlanProposal:
    tasks_by_id = {task.id: task for task in tasks}
    ordered_ids = response.ordered_task_ids
    if len(ordered_ids) != len(set(ordered_ids)):
        raise ValueError("ИИ вернул повторяющиеся task ID в порядке выполнения.")
    if set(ordered_ids) != set(tasks_by_id):
        raise ValueError("ИИ вернул неизвестный или неполный набор task ID для плана.")
    return AIPlanProposal(
        ordered_tasks=[tasks_by_id[task_id] for task_id in ordered_ids],
        deferred_tasks=[],
    )


def calculate_schedule(
    proposal: AIPlanProposal,
    *,
    plan_date: date,
    timezone: str,
    available_minutes: int,
    now: datetime | None = None,
) -> CalculatedSchedule:
    zone = ZoneInfo(timezone)
    reference_now = now or datetime.now(zone)
    local_now = (
        reference_now.replace(tzinfo=zone)
        if reference_now.tzinfo is None
        else reference_now.astimezone(zone)
    )
    if plan_date < local_now.date() or available_minutes <= 0:
        return CalculatedSchedule(
            slots=[],
            deferred_tasks=[
                *proposal.deferred_tasks,
                *[(task, "На эту дату больше нет доступного времени.") for task in proposal.ordered_tasks],
            ],
            available_minutes=max(0, available_minutes),
            scheduled_minutes=0,
        )

    day_start = datetime.combine(plan_date, time(hour=8), tzinfo=zone)
    day_end = datetime.combine(plan_date, time(hour=22), tzinfo=zone)
    if plan_date == local_now.date():
        start = max(day_start, _round_up_to_five_minutes(local_now))
    else:
        start = day_start

    cursor = start
    used_minutes = 0
    slots: list[ProposedScheduleSlot] = []
    deferred = list(proposal.deferred_tasks)
    for task in proposal.ordered_tasks:
        duration = task.estimated_minutes
        if duration is None or duration <= 0:
            deferred.append((task, "Не указана длительность задачи."))
            continue
        fixed_start = task.starts_at.astimezone(zone) if task.starts_at else None
        if fixed_start is not None and fixed_start.date() != plan_date:
            deferred.append((task, "Фиксированное время начала относится к другой дате."))
            continue
        task_start = fixed_start or cursor
        if task_start < cursor:
            deferred.append((task, "Фиксированное время начала конфликтует с предыдущими задачами."))
            continue
        task_end = task_start + timedelta(minutes=duration)
        buffer = BUFFER_MINUTES
        required_minutes = duration + (BUFFER_MINUTES if slots else 0)
        if used_minutes + required_minutes > available_minutes or task_end > day_end:
            deferred.append((task, "Задача не помещается в доступное время дня."))
            continue
        if slots:
            previous = slots[-1]
            slots[-1] = ProposedScheduleSlot(
                task=previous.task,
                position=previous.position,
                starts_at=previous.starts_at,
                ends_at=previous.ends_at,
                buffer_after_minutes=BUFFER_MINUTES,
            )
        slots.append(
            ProposedScheduleSlot(
                task=task,
                position=len(slots) + 1,
                starts_at=task_start,
                ends_at=task_end,
                buffer_after_minutes=0,
            )
        )
        used_minutes += required_minutes
        cursor = task_end + timedelta(minutes=BUFFER_MINUTES)
    return CalculatedSchedule(
        slots=slots,
        deferred_tasks=deferred,
        available_minutes=available_minutes,
        scheduled_minutes=used_minutes,
    )


def _build_prompt(tasks: list[Task], available_minutes: int, day_state=None, planning_context=None) -> str:
    payload = []
    for task in tasks:
        assessment = assess_task(task)
        payload.append(
            {
                "id": task.id,
                "title": task.text,
                "context": task.context,
                "priority_score": assessment.score,
                "importance": task.priority,
                "effort": task.effort,
                "estimated_minutes": task.estimated_minutes,
                "fixed_start": task.starts_at.isoformat() if task.starts_at else None,
                "deadline": task.due_at.isoformat() if task.due_at else None,
                "postponement_count": task.postponement_count,
            }
        )
    state_context = ""
    if day_state is not None:
        state_context = (
            "\nКонтекст состояния пользователя: "
            + json.dumps(
                {
                    "energy": day_state.brain_energy,
                    "concentration": day_state.concentration,
                    "mental_fatigue": day_state.mental_fatigue,
                    "physical_energy": day_state.physical_energy,
                    "desired_day_mode": day_state.desired_day_mode,
                    "strategy": day_state.selected_strategy,
                    "alternate_categories": day_state.alternate_categories,
                    "extended_answers": day_state.long_answers,
                },
                ensure_ascii=False,
            )
            + "\nСледуй выбранной стратегии, но фиксированное время и реальные дедлайны важнее."
        )
    return (
        f"Доступно времени: {available_minutes} минут. "
        "Верни полный порядок всех задач; переносы определит Python.\nЗадачи:\n"
        + json.dumps(payload, ensure_ascii=False)
        + state_context
        + ("\nДополнительный контекст пользователя: " + json.dumps(planning_context, ensure_ascii=False) if planning_context else "")
    )


def _round_up_to_five_minutes(value: datetime) -> datetime:
    rounded = value.replace(second=0, microsecond=0)
    remainder = rounded.minute % 5
    if remainder:
        rounded += timedelta(minutes=5 - remainder)
    return rounded


def _is_retryable(error: Exception) -> bool:
    message = str(error)
    return (
        isinstance(error, ValueError)
        or "timed out" in message
        or "empty response" in message
        or "invalid response" in message
        or "does not match the schema" in message
        or any(f"HTTP {status}" in message for status in (429, 500, 502, 503, 504))
    )
