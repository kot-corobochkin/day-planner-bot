import json
import time as clock
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from app.models.task import Task
from app.services.llm_provider import LLMProvider, LLMProviderError


class EveningQuestionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[str] = Field(min_length=10, max_length=10)


@dataclass(frozen=True)
class EveningReflectionDraft:
    questions: list[str]
    source: str


FALLBACK_QUESTIONS = [
    "Какая задача сегодня дала самый заметный прогресс и почему?",
    "Какая запланированная задача не была завершена? Что ей помешало?",
    "Насколько реалистичным оказался объём плана на сегодня?",
    "В какой момент дня было проще всего сосредоточиться?",
    "Какая задача потребовала больше или меньше времени, чем ожидалось?",
    "Помогла ли выбранная стратегия дня? Что именно сработало или не сработало?",
    "Какая задача или действие забрало непропорционально много энергии?",
    "Что стоило перенести, делегировать, разбить или убрать раньше?",
    "Какой один вывод стоит учесть при планировании завтрашнего дня?",
    "Что сегодня получилось хорошо, независимо от количества завершённых задач?",
]


class EveningReflectionService:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def create_questions(self, tasks: list[Task], day_state=None) -> EveningReflectionDraft:
        payload = {
            "tasks": [
                {
                    "title": task.text,
                    "status": task.status.value,
                    "estimated_minutes": task.estimated_minutes,
                    "priority": task.priority,
                    "effort": task.effort,
                    "postponement_count": task.postponement_count,
                }
                for task in tasks
            ],
            "day_strategy": getattr(day_state, "selected_strategy", None),
            "desired_day_mode": getattr(day_state, "desired_day_mode", None),
        }
        questions: list[str] | None = None
        for attempt in range(3):
            if attempt:
                clock.sleep(10)
            round_payload = {**payload, "previous_questions": questions, "revision_round": attempt + 1}
            try:
                response = self._provider.generate_json(
                    system_prompt=(
                        "Составь ровно 10 коротких, бережных вопросов для вечерней рефлексии. "
                        "Они должны опираться на задачи и стратегию дня, помогать понять прогресс, "
                        "перегрузку и следующий шаг. Не ставь диагнозов, не используй оценочный тон. "
                        "Если передан прошлый вариант, улучши его: убери повторы и сделай вопросы конкретнее. "
                        "Верни только JSON по схеме."
                    ),
                    user_prompt=json.dumps(round_payload, ensure_ascii=False),
                    response_model=EveningQuestionsResponse,
                    max_output_tokens=1_200,
                )
                candidate = [question.strip() for question in response.questions]
                if all(candidate):
                    questions = candidate
            except (LLMProviderError, ValueError):
                continue
        return EveningReflectionDraft(
            questions=questions or FALLBACK_QUESTIONS,
            source="ai" if questions else "fallback",
        )
