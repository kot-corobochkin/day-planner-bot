import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.models.task import Task, TaskValueSource
from app.services.llm_provider import LLMProvider, LLMProviderError


class AITaskEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: int
    priority: int = Field(ge=1, le=10)
    effort: int = Field(ge=1, le=10)
    estimated_minutes: int = Field(ge=1, le=1440)
    priority_confidence: float = Field(ge=0, le=1)
    effort_confidence: float = Field(ge=0, le=1)
    duration_confidence: float = Field(ge=0, le=1)
    explanation: str = Field(min_length=1, max_length=500)
    missing_data: list[str] = Field(default_factory=list, max_length=10)


class AIEstimateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    estimates: list[AITaskEstimate] = Field(min_length=1)


@dataclass(frozen=True)
class ValidatedEstimate:
    task: Task
    proposal: AITaskEstimate

    @property
    def applicable_changes(self) -> dict[str, int]:
        changes: dict[str, int] = {}
        if self.task.priority_source != TaskValueSource.user and self.task.priority != self.proposal.priority:
            changes["priority"] = self.proposal.priority
        if self.task.effort_source != TaskValueSource.user and self.task.effort != self.proposal.effort:
            changes["effort"] = self.proposal.effort
        if self.task.duration_source != TaskValueSource.user and self.task.estimated_minutes != self.proposal.estimated_minutes:
            changes["estimated_minutes"] = self.proposal.estimated_minutes
        return changes


class AIEstimationService:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        debug_log_path: Path = Path("data/debug/ai_estimate_errors.jsonl"),
    ) -> None:
        self._provider = provider
        self._debug_log_path = debug_log_path

    def estimate(self, tasks: list[Task]) -> list[ValidatedEstimate]:
        if not tasks:
            return []
        validated: list[ValidatedEstimate] = []
        for batch_number, batch in enumerate(_batches(tasks, size=3), start=1):
            validated.extend(self._estimate_batch(batch, batch_number))
        return validated

    def _estimate_batch(
        self, batch: list[Task], batch_number: int
    ) -> list[ValidatedEstimate]:
        for attempt in range(3):
            try:
                response = self._provider.generate_json(
                    system_prompt=(
                        "Оцени важность, сложность и длительность задач. Верни только JSON, "
                        "соответствующий схеме. Для каждого переданного task_id верни ровно одну "
                        "оценку без дополнительных ID. Значения с источником 'default' являются "
                        "заглушками, а не подтверждёнными фактами: оцени их независимо по названию "
                        "и описанию задачи. Не повторяй значения 5/10 или 60 минут только потому, "
                        "что они переданы во входных данных. Если название или описание дают достаточно "
                        "оснований, укажи конкретную сложность и длительность; сохраняй значение только "
                        "если оно действительно подходит, либо укажи недостающие данные. Не предлагай "
                        "подзадачи. Не используй инструменты."
                    ),
                    user_prompt=_build_prompt(batch),
                    response_model=AIEstimateResponse,
                )
                return validate_estimates(batch, response)
            except LLMProviderError as error:
                self._write_debug_error(batch, batch_number, attempt + 1, error)
                if attempt == 2 or not _is_temporary_provider_error(error):
                    raise LLMProviderError(
                        f"AI batch {batch_number} failed: {error}"
                    ) from error
                time.sleep(2**attempt)
            except ValueError as error:
                self._write_debug_error(batch, batch_number, attempt + 1, error)
                if attempt == 2:
                    raise ValueError(f"AI batch {batch_number} invalid: {error}") from error
                time.sleep(2**attempt)
        raise AssertionError("unreachable")

    def _write_debug_error(
        self,
        batch: list[Task],
        batch_number: int,
        attempt: int,
        error: Exception,
    ) -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "batch_number": batch_number,
            "attempt": attempt,
            "task_ids": [task.id for task in batch],
            "error": str(error),
        }
        try:
            self._debug_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._debug_log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            # Debug logging must not make the AI command fail differently.
            pass


def validate_estimates(tasks: list[Task], response: AIEstimateResponse) -> list[ValidatedEstimate]:
    tasks_by_id = {task.id: task for task in tasks}
    estimates_by_id = {estimate.task_id: estimate for estimate in response.estimates}
    if len(estimates_by_id) != len(response.estimates):
        raise ValueError("ИИ вернул повторяющиеся task ID.")
    if set(estimates_by_id) != set(tasks_by_id):
        raise ValueError("ИИ вернул неизвестный или неполный набор task ID.")
    return [ValidatedEstimate(task=task, proposal=estimates_by_id[task.id]) for task in tasks]


def dump_estimates(estimates: list[ValidatedEstimate]) -> list[tuple[int, dict]]:
    return [
        (estimate.task.id, estimate.proposal.model_dump(mode="json"))
        for estimate in estimates
    ]


def load_draft_estimates(tasks: list[Task], proposals: list[dict]) -> list[ValidatedEstimate]:
    return validate_estimates(
        tasks,
        AIEstimateResponse.model_validate({"estimates": proposals}),
    )


def _build_prompt(tasks: list[Task]) -> str:
    payload = [
        {
            "id": task.id,
            "title": task.text,
            "description": task.context,
            "priority": task.priority,
            "priority_source": task.priority_source.value,
            "effort": task.effort,
            "effort_source": task.effort_source.value,
            "estimated_minutes": task.estimated_minutes,
            "duration_source": task.duration_source.value,
            "deadline": task.due_at.isoformat() if task.due_at else None,
            "postponement_count": task.postponement_count,
            "category": None,
            "goal": None,
        }
        for task in tasks
    ]
    task_ids = [task.id for task in tasks]
    return (
        f"Верни оценки ровно для этих task_id: {task_ids}. "
        "Массив estimates должен содержать каждый указанный ID ровно один раз.\nЗадачи:\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def _batches(tasks: list[Task], *, size: int) -> list[list[Task]]:
    return [tasks[index : index + size] for index in range(0, len(tasks), size)]


def _is_temporary_provider_error(error: LLMProviderError) -> bool:
    message = str(error)
    return (
        "timed out" in message
        or "empty response" in message
        or "does not match the schema" in message
        or any(
        f"HTTP {status}" in message for status in (429, 500, 502, 503, 504)
        )
    )
