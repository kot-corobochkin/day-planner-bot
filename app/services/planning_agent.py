"""Bounded planning agent: it may analyse and propose, never apply changes itself."""

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic import Field

from app.models.task import Task
from app.services.ai_planning import AIPlanProposal, AIPlanningService, calculate_schedule
from app.services.ai_reflection import AIPlanReflection, AIReflectionService
from app.services.feasibility import analyze_plan_feasibility
from app.services.feasibility import recommend_moves
from app.services.day_strategy import recommend_strategies
from app.services.llm_provider import LLMProvider, LLMProviderError


class AgentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["analyze_feasibility", "ask_user", "find_context_switches", "recommend_reduction", "compare_with_history", "suggest_strategy", "create_order", "reflect_plan", "present_plan"]
    reason: str
    question: str | None = None
    field: str | None = None
    options: list[str] = []


@dataclass(frozen=True)
class PlanningAgentQuestion:
    field: str
    question: str
    options: list[str]


class GoalTaskSuggestion(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    estimated_minutes: int = Field(ge=10, le=240)


class GoalTaskSuggestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tasks: list[GoalTaskSuggestion] = Field(min_length=1, max_length=3)


@dataclass(frozen=True)
class PlanningAgentResult:
    proposal: AIPlanProposal | None
    original_proposal: AIPlanProposal | None
    reflection: AIPlanReflection | None
    trace: list[str]
    question: PlanningAgentQuestion | None = None
    insights: list[str] = None
    suggested_goal_tasks: list[GoalTaskSuggestion] | None = None


class PlanningAgentService:
    """A tool-using agent with a small, auditable action space and a hard step limit."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider
        self._planner = AIPlanningService(provider)
        self._reflection = AIReflectionService(provider)

    def run(
        self,
        *,
        tasks: list[Task],
        plan_date,
        timezone: str,
        available_minutes: int,
        day_state=None,
        follow_up_answers: dict[str, str] | None = None,
        history: list[dict] | None = None,
        resume_from: str | None = None,
        memory: str = "",
    ) -> PlanningAgentResult:
        follow_up_answers = follow_up_answers or {}
        history = history or []
        tool_results: dict[str, object] = {}
        trace: list[str] = []
        proposal: AIPlanProposal | None = None
        original_proposal: AIPlanProposal | None = None
        reflection: AIPlanReflection | None = None
        insights: list[str] = []

        goal = follow_up_answers.get("day_goals", "")
        if goal and not follow_up_answers.get("goal_task_choice_made") and not _goal_is_covered(goal, tasks):
            suggestions = self._suggest_goal_tasks(goal, tasks, day_state)
            if suggestions:
                return PlanningAgentResult(None, None, None, ["suggest_goal_tasks: цель не покрыта"],
                                           suggested_goal_tasks=suggestions)

        for task in tasks:
            field = f"fixed_constraint_{task.id}"
            looks_fixed = any(word in task.text.casefold() for word in ("приём", "врач", "доктор", "созвон", "встреч"))
            if looks_fixed and task.starts_at is None and field not in follow_up_answers:
                return PlanningAgentResult(
                    proposal=None, original_proposal=None, reflection=None,
                    trace=["detect_missing_constraints: запросил фиксированное время"],
                    question=PlanningAgentQuestion(
                        field=field,
                        question=(f"У задачи «{task.text}» есть фиксированное время? "
                                  "Если да, укажите ЧЧ:ММ и примерную длительность; иначе напишите «нет»."),
                        options=[],
                    ),
                    insights=[],
                )

        if resume_from == "create_order":
            analysis = analyze_plan_feasibility(tasks, available_minutes=available_minutes)
            tool_results["feasibility"] = {"scheduled_minutes": analysis.scheduled_minutes}
            trace.append("resume: create_order")
        for _ in range(8):
            if resume_from == "create_order":
                if proposal is None:
                    decision = AgentDecision(action="create_order", reason="Возобновляю упавший шаг.")
                elif "reflection" not in tool_results:
                    decision = AgentDecision(action="reflect_plan", reason="Проверяю возобновлённый порядок.")
                else:
                    decision = AgentDecision(action="present_plan", reason="План готов после повтора.")
            else:
                decision = self._choose_action(
                    tasks=tasks,
                    available_minutes=available_minutes,
                    day_state=day_state,
                    tool_results=tool_results,
                    follow_up_answers=follow_up_answers,
                history=history,
                memory=memory,
                )
            action = self._safe_action(
                decision.action,
                proposal,
                reflection,
                feasibility_attempted="feasibility" in tool_results,
                reflection_attempted="reflection" in tool_results,
                follow_up_answered=bool(follow_up_answers),
                completed_tools=set(tool_results),
            )
            trace.append(f"{action}: {decision.reason}")

            if action == "analyze_feasibility":
                analysis = analyze_plan_feasibility(tasks, available_minutes=available_minutes)
                tool_results["feasibility"] = {
                    "scheduled_minutes": analysis.scheduled_minutes,
                    "available_minutes": analysis.available_minutes,
                    "overload_minutes": max(0, -analysis.remaining_minutes),
                    "move_candidate_count": len(analysis.move_candidates),
                }
            elif action == "create_order":
                proposal = self._planner.propose(
                    tasks, available_minutes=available_minutes, day_state=day_state,
                    planning_context={"answers": follow_up_answers, "memory": memory, "insights": insights},
                )
                original_proposal = proposal
                tool_results["order"] = [task.id for task in proposal.ordered_tasks]
            elif action == "ask_user":
                if decision.question and decision.field:
                    return PlanningAgentResult(
                        proposal=None,
                        original_proposal=None,
                        reflection=None,
                        trace=trace,
                        question=PlanningAgentQuestion(
                            field=decision.field,
                            question=decision.question,
                            options=decision.options[:5],
                        ),
                        insights=insights,
                    )
                tool_results["question_unavailable"] = True
            elif action == "find_context_switches":
                grouped = {}
                for task in tasks:
                    key = task.category or task.context
                    if key:
                        grouped[key] = grouped.get(key, 0) + 1
                groups = [f"{name} ({count})" for name, count in grouped.items() if count > 1]
                if groups:
                    insights.append("Можно сгруппировать задачи по контексту: " + ", ".join(groups[:3]) + ".")
                tool_results["context_switches"] = groups
            elif action == "recommend_reduction":
                analysis = analyze_plan_feasibility(tasks, available_minutes=available_minutes)
                recommendation = recommend_moves(analysis)
                if recommendation.tasks:
                    titles = ", ".join(item.task.text for item in recommendation.tasks[:3])
                    insights.append(f"Для снятия перегрузки можно перенести: {titles}.")
                tool_results["reduction"] = len(recommendation.tasks)
            elif action == "compare_with_history":
                if history:
                    average = round(sum(item["completion_percentage"] for item in history) / len(history))
                    insights.append(f"Среднее выполнение за последние {len(history)} дней: {average}%.")
                tool_results["history"] = len(history)
            elif action == "suggest_strategy":
                if day_state is not None:
                    recommendation = recommend_strategies(
                        brain_energy=day_state.brain_energy, concentration=day_state.concentration,
                        mental_fatigue=day_state.mental_fatigue, physical_energy=day_state.physical_energy,
                        desired_day_mode=day_state.desired_day_mode,
                        alternate_categories=day_state.alternate_categories,
                    )
                    if day_state.selected_strategy not in recommendation.strategies:
                        insights.append("По текущему состоянию альтернативная стратегия: " + recommendation.strategies[0] + ".")
                tool_results["strategy"] = True
            elif action == "reflect_plan":
                assert proposal is not None
                preview = calculate_schedule(
                    proposal,
                    plan_date=plan_date,
                    timezone=timezone,
                    available_minutes=available_minutes,
                )
                try:
                    reflection = self._reflection.review(
                        proposal=proposal,
                        tasks=tasks,
                        slots=preview.slots,
                        available_minutes=available_minutes,
                        day_state=day_state,
                    )
                    proposal = reflection.revised_proposal
                    tool_results["reflection"] = {
                        "acceptable": reflection.is_acceptable,
                        "observations": reflection.observations,
                    }
                except (LLMProviderError, ValueError) as error:
                    tool_results["reflection"] = {"unavailable": str(error)}
                    trace.append("reflect_plan: unavailable; keeping initial order")
            else:  # present_plan
                if proposal is not None:
                    return PlanningAgentResult(
                        proposal=proposal,
                        original_proposal=original_proposal or proposal,
                        reflection=reflection,
                        trace=trace,
                        insights=insights,
                    )

        if proposal is None:
            proposal = self._planner.propose(
                tasks, available_minutes=available_minutes, day_state=day_state,
                planning_context={"answers": follow_up_answers, "memory": memory, "insights": insights},
            )
            original_proposal = proposal
            trace.append("create_order: safety fallback after step limit")
        return PlanningAgentResult(
            proposal=proposal,
            original_proposal=original_proposal or proposal,
            reflection=reflection, insights=insights,
            trace=trace,
        )

    def _choose_action(self, *, tasks, available_minutes, day_state, tool_results, follow_up_answers, history, memory) -> AgentDecision:
        context = {
            "goal": "Сформировать выполнимый порядок задач и передать его пользователю на подтверждение.",
            "available_tools": ["analyze_feasibility", "ask_user", "find_context_switches", "recommend_reduction", "compare_with_history", "suggest_strategy", "create_order", "reflect_plan", "present_plan"],
            "available_minutes": available_minutes,
            "task_count": len(tasks),
            "tasks": [
                {
                    "id": task.id, "priority": task.priority, "effort": task.effort,
                    "minutes": task.estimated_minutes, "fixed_start": bool(task.starts_at),
                    "deadline": bool(task.due_at),
                }
                for task in tasks
            ],
            "strategy": getattr(day_state, "selected_strategy", None),
            "tool_results": tool_results,
            "follow_up_answers": follow_up_answers,
            "history_days": len(history),
            "agent_memory": memory,
        }
        try:
            return self._provider.generate_json(
                system_prompt=(
                    "Ты — агент планирования дня. Выбирай только следующий безопасный инструмент. "
                    "Сначала проверь выполнимость. Если после этого критически не хватает одного факта, "
                    "можешь один раз вызвать ask_user с коротким вопросом и максимум пятью вариантами. "
                    "До создания порядка при необходимости используй find_context_switches, recommend_reduction, compare_with_history или suggest_strategy. "
                    "Не спрашивай то, что уже есть в follow_up_answers. Затем создай порядок, затем проверь его через reflexion, "
                    "после этого покажи план. Никогда не применяй изменения и не отменяй задачи. "
                    "Верни только JSON по схеме."
                ),
                user_prompt=json.dumps(context, ensure_ascii=False),
                response_model=AgentDecision,
                max_output_tokens=250,
            )
        except (LLMProviderError, ValueError):
            # Safe deterministic choice keeps the workflow useful during provider degradation.
            if "feasibility" not in tool_results:
                return AgentDecision(action="analyze_feasibility", reason="Проверяю вместимость плана.")
            if "order" not in tool_results:
                return AgentDecision(action="create_order", reason="Строю порядок задач.")
            if "reflection" not in tool_results:
                return AgentDecision(action="reflect_plan", reason="Проверяю предложенный порядок.")
            return AgentDecision(action="present_plan", reason="План готов к подтверждению.")

    def _suggest_goal_tasks(self, goal: str, tasks: list[Task], day_state) -> list[GoalTaskSuggestion]:
        try:
            response = self._provider.generate_json(
                system_prompt="Предложи до трёх конкретных следующих задач для цели дня. Не дублируй существующие. Укажи длительность. Верни JSON.",
                user_prompt=json.dumps({"goal": goal, "existing_tasks": [task.text for task in tasks],
                                        "energy": getattr(day_state, "brain_energy", None)}, ensure_ascii=False),
                response_model=GoalTaskSuggestionResponse,
                max_output_tokens=600,
            )
            return response.tasks
        except (LLMProviderError, ValueError):
            return []
    @staticmethod
    def _safe_action(
        action: str, proposal, reflection, *, feasibility_attempted: bool, reflection_attempted: bool,
        follow_up_answered: bool, completed_tools: set[str],
    ) -> str:
        if proposal is None:
            if not feasibility_attempted:
                return "analyze_feasibility"
            if action == "ask_user" and not follow_up_answered:
                return "ask_user"
            if action in {"find_context_switches", "recommend_reduction", "compare_with_history", "suggest_strategy"} and action not in completed_tools:
                return action
            return "create_order"
        if not reflection_attempted:
            return "reflect_plan"
        return action


def _goal_is_covered(goal: str, tasks: list[Task]) -> bool:
    tokens = [token for token in goal.casefold().split() if len(token) >= 3]
    return any(any(token in task.text.casefold() for token in tokens) for task in tasks)
