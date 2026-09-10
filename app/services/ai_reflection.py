import json
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from app.models.task import Task
from app.services.ai_planning import AIPlanProposal, ProposedScheduleSlot
from app.services.llm_provider import LLMProvider, LLMProviderError


class AIReflectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_acceptable: bool
    observations: list[str] = Field(max_length=5)
    revised_ordered_task_ids: list[int] = Field(min_length=1)
    user_message: str = Field(min_length=1, max_length=600)


@dataclass(frozen=True)
class AIPlanReflection:
    is_acceptable: bool
    observations: list[str]
    revised_proposal: AIPlanProposal
    user_message: str


class AIReflectionService:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def review(
        self,
        *,
        proposal: AIPlanProposal,
        tasks: list[Task],
        slots: list[ProposedScheduleSlot],
        available_minutes: int,
        day_state=None,
    ) -> AIPlanReflection:
        try:
            response = self._provider.generate_json(
                system_prompt=(
                    "Проверь предложенный порядок задач как независимый критик. "
                    "Не меняй состав задач, их priority_score, фиксированное время и дедлайны. "
                    "Выявляй только конкретные конфликты со стратегией дня, нагрузкой и порядком. "
                    "Если порядок приемлем, верни его без изменений. Верни только JSON по схеме."
                ),
                user_prompt=_build_reflection_prompt(
                    proposal, tasks, slots, available_minutes, day_state
                ),
                response_model=AIReflectionResponse,
                max_output_tokens=1_000,
            )
        except (LLMProviderError, ValueError) as error:
            raise type(error)(f"AI reflection failed: {error}") from error
        tasks_by_id = {task.id: task for task in proposal.ordered_tasks}
        ordered_ids = response.revised_ordered_task_ids
        if len(ordered_ids) != len(set(ordered_ids)) or set(ordered_ids) != set(tasks_by_id):
            raise ValueError("AI-проверка вернула неполный или повторяющийся порядок задач.")
        return AIPlanReflection(
            is_acceptable=response.is_acceptable,
            observations=response.observations,
            revised_proposal=AIPlanProposal(
                ordered_tasks=[tasks_by_id[task_id] for task_id in ordered_ids],
                deferred_tasks=proposal.deferred_tasks,
            ),
            user_message=response.user_message,
        )


def _build_reflection_prompt(
    proposal: AIPlanProposal,
    tasks: list[Task],
    slots: list[ProposedScheduleSlot],
    available_minutes: int,
    day_state,
) -> str:
    task_data = [
        {
            "id": task.id,
            "title": task.text,
            "priority": task.priority,
            "effort": task.effort,
            "estimated_minutes": task.estimated_minutes,
            "fixed_start": task.starts_at.isoformat() if task.starts_at else None,
            "deadline": task.due_at.isoformat() if task.due_at else None,
            "context": task.context,
        }
        for task in tasks
    ]
    payload = {
        "available_minutes": available_minutes,
        "selected_strategy": getattr(day_state, "selected_strategy", None),
        "desired_day_mode": getattr(day_state, "desired_day_mode", None),
        "state": {
            "energy": getattr(day_state, "brain_energy", None),
            "concentration": getattr(day_state, "concentration", None),
            "mental_fatigue": getattr(day_state, "mental_fatigue", None),
        },
        "tasks": task_data,
        "proposed_ordered_task_ids": [task.id for task in proposal.ordered_tasks],
        "preliminary_slots": [
            {"task_id": slot.task.id, "starts_at": slot.starts_at.isoformat(), "ends_at": slot.ends_at.isoformat()}
            for slot in slots
        ],
    }
    return json.dumps(payload, ensure_ascii=False)
