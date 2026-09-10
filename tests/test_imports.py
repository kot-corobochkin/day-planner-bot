def test_application_factory_imports() -> None:
    from app.main import build_application

    assert build_application is not None


def test_today_creates_a_plan_and_moves_overdue_tasks(monkeypatch) -> None:
    from datetime import date
    from types import SimpleNamespace

    from app.services.planning_service import PlanningService

    today = date.today()
    plan = SimpleNamespace(id=17, plan_date=today)
    calls: dict[str, object] = {}

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def commit(self):
            calls["committed"] = True

    class Database:
        def connection(self):
            return Connection()

    class UserRepository:
        def __init__(self, conn):
            pass

        def get_user_by_telegram_id(self, telegram_id):
            assert telegram_id == 42
            return SimpleNamespace(id=9)

    class DailyPlanRepository:
        def __init__(self, conn):
            pass

        def get_today_plan(self, user_id, plan_date):
            assert (user_id, plan_date) == (9, today)
            return None

        def ensure_plan(self, user_id, plan_date, *, day_type, available_minutes):
            calls["created"] = (user_id, plan_date, day_type, available_minutes)
            return plan

    class TaskRepository:
        def __init__(self, conn):
            pass

        def move_overdue_tasks_to_plan(self, **kwargs):
            calls["moved"] = kwargs

        def get_visible_tasks(self, plan_id):
            assert plan_id == 17
            return []

    monkeypatch.setattr("app.services.planning_service.UserRepository", UserRepository)
    monkeypatch.setattr("app.services.planning_service.DailyPlanRepository", DailyPlanRepository)
    monkeypatch.setattr("app.services.planning_service.TaskRepository", TaskRepository)

    result = PlanningService(Database(), "Europe/Moscow").get_today_plan(42)

    assert result is not None
    assert calls["created"] == (9, today, "Смешанный", 480)
    assert calls["moved"] == {"user_id": 9, "target_plan_id": 17, "target_date": today}
    assert calls["committed"] is True


def test_state_based_recommendation_prefers_gentle_mode_for_low_resource() -> None:
    from app.services.day_strategy import recommend_strategies

    result = recommend_strategies(
        brain_energy=2,
        concentration=4,
        mental_fatigue=8,
        physical_energy=3,
        desired_day_mode="⚖️ Сбалансированный",
        alternate_categories=False,
    )

    assert result.strategies[0] == "Щадящий режим"


def test_state_based_recommendation_includes_requested_alternation() -> None:
    from app.services.day_strategy import recommend_strategies

    result = recommend_strategies(
        brain_energy=7,
        concentration=7,
        mental_fatigue=3,
        physical_energy=7,
        desired_day_mode="🚀 Проектный",
        alternate_categories=True,
    )

    assert result.strategies == ("Глубокий фокус", "Чередование категорий")


def test_reflection_reorders_only_existing_tasks() -> None:
    from datetime import datetime

    from app.models.task import Task
    from app.services.ai_planning import AIPlanProposal
    from app.services.ai_reflection import AIReflectionResponse, AIReflectionService

    class Provider:
        def generate_json(self, **kwargs):
            return AIReflectionResponse(
                is_acceptable=False,
                observations=["Сложную задачу лучше поставить раньше."],
                revised_ordered_task_ids=[2, 1],
                user_message="Перенёс сложную задачу в начало.",
            )

    tasks = [
        Task(id=1, daily_plan_id=1, text="Рутина", status="planned", first_planned_date=datetime.today().date(), created_at=datetime.now(), updated_at=datetime.now()),
        Task(id=2, daily_plan_id=1, text="Сложная задача", status="planned", first_planned_date=datetime.today().date(), created_at=datetime.now(), updated_at=datetime.now()),
    ]
    result = AIReflectionService(Provider()).review(
        proposal=AIPlanProposal(ordered_tasks=tasks, deferred_tasks=[]),
        tasks=tasks,
        slots=[],
        available_minutes=120,
    )

    assert [task.id for task in result.revised_proposal.ordered_tasks] == [2, 1]


def test_evening_reflection_refines_questions_in_three_ai_calls(monkeypatch) -> None:
    from app.services.evening_reflection import EveningQuestionsResponse, EveningReflectionService

    class Provider:
        def __init__(self):
            self.calls = 0

        def generate_json(self, **kwargs):
            self.calls += 1
            return EveningQuestionsResponse(questions=[f"Вопрос {index}?" for index in range(1, 11)])

    provider = Provider()
    monkeypatch.setattr("app.services.evening_reflection.clock.sleep", lambda seconds: None)

    result = EveningReflectionService(provider).create_questions([])

    assert provider.calls == 3
    assert result.source == "ai"
    assert len(result.questions) == 10


def test_task_category_uses_title_prefix_not_planning_option() -> None:
    from app.services.task_category import extract_task_category
    from app.services.task_input_parser import parse_task_lines

    task = parse_task_lines(["Бот: изменить название -важность:5"])[0]

    assert extract_task_category(task.text) == "Бот"
    assert task.priority == 5


def test_task_category_ignores_url_scheme() -> None:
    from app.services.task_category import extract_task_category

    assert extract_task_category("https://example.com: открыть ссылку") is None
    assert extract_task_category("Изучить https:") is None
    assert extract_task_category("Импортировать скилл - https://example.com") is None
    assert extract_task_category("Проект: открыть ссылку") == "Проект"


def test_application_registers_repeated_move_confirmation_state() -> None:
    from app.bot.handlers import MOVE_REPEAT_CONFIRM, receive_repeat_move_decision

    assert isinstance(MOVE_REPEAT_CONFIRM, int)
    assert callable(receive_repeat_move_decision)


def test_move_dialog_accepts_one_task_and_date_in_one_message(monkeypatch) -> None:
    import asyncio
    from datetime import UTC, date, datetime
    from types import SimpleNamespace

    from app.bot.handlers import receive_move_tasks
    from app.models.task import Task, TaskStatus

    task = Task(
        id=5, daily_plan_id=1, text="Задача", status=TaskStatus.planned,
        first_planned_date=date(2026, 7, 14), created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )

    class Service:
        def get_task_details(self, task_id, telegram_id):
            return SimpleNamespace(task=task)

        def move_tasks(self, task_ids, *, telegram_id, target_date):
            assert task_ids == [5]
            assert target_date == date(2026, 7, 18)
            return [task]

    class Message:
        text = "5 2026-07-18"

        async def reply_text(self, text, **kwargs):
            self.reply = text

    monkeypatch.setattr("app.bot.handlers._task_service", lambda context: Service())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    context = SimpleNamespace(
        user_data={"move_task_ids": [1, 2, 3, 4, 5, 6, 7], "move_source_date": "2026-07-14"}
    )

    result = asyncio.run(receive_move_tasks(update, context=SimpleNamespace(**context.__dict__)))

    assert result == -1
    assert "Перенесено задач: 1" in update.message.reply


def test_planning_agent_runs_only_safe_planning_tools() -> None:
    from datetime import UTC, date, datetime

    from app.models.task import Task, TaskStatus
    from app.services.ai_planning import AIPlanResponse
    from app.services.ai_reflection import AIReflectionResponse
    from app.services.planning_agent import AgentDecision, PlanningAgentService

    class Provider:
        def __init__(self):
            self.actions = iter(["analyze_feasibility", "create_order", "reflect_plan", "present_plan"])

        def generate_json(self, *, response_model, **kwargs):
            if response_model is AgentDecision:
                return AgentDecision(action=next(self.actions), reason="test")
            if response_model is AIPlanResponse:
                return AIPlanResponse(ordered_task_ids=[1])
            if response_model is AIReflectionResponse:
                return AIReflectionResponse(
                    is_acceptable=True, observations=[], revised_ordered_task_ids=[1], user_message="Порядок подходит."
                )
            raise AssertionError(response_model)

    task = Task(
        id=1, daily_plan_id=1, text="Задача", status=TaskStatus.planned,
        first_planned_date=date(2026, 7, 15), estimated_minutes=60,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    result = PlanningAgentService(Provider()).run(
        tasks=[task], plan_date=date(2026, 7, 15), timezone="Europe/Moscow", available_minutes=120
    )

    assert [item.split(":", 1)[0] for item in result.trace] == [
        "analyze_feasibility", "create_order", "reflect_plan", "present_plan"
    ]
    assert result.proposal.ordered_tasks == [task]


def test_planning_agent_can_pause_for_one_follow_up_question() -> None:
    from datetime import UTC, date, datetime

    from app.models.task import Task, TaskStatus
    from app.services.planning_agent import AgentDecision, PlanningAgentService

    class Provider:
        def __init__(self):
            self.actions = iter([
                AgentDecision(action="analyze_feasibility", reason="check"),
                AgentDecision(
                    action="ask_user", reason="need priority", field="must_do",
                    question="Какая задача сегодня обязательна?", options=["Задача 1", "Нет такой"],
                ),
            ])

        def generate_json(self, **kwargs):
            return next(self.actions)

    task = Task(
        id=1, daily_plan_id=1, text="Задача 1", status=TaskStatus.planned,
        first_planned_date=date(2026, 7, 15), estimated_minutes=60,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    result = PlanningAgentService(Provider()).run(
        tasks=[task], plan_date=date(2026, 7, 15), timezone="Europe/Moscow", available_minutes=120
    )

    assert result.proposal is None
    assert result.question is not None
    assert result.question.field == "must_do"


def test_plan_command_starts_date_selection() -> None:
    import asyncio
    from types import SimpleNamespace

    from app.bot.handlers import PLAN_DATE, plan_start

    class Message:
        async def reply_text(self, text, **kwargs):
            self.text = text
            self.kwargs = kwargs

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    context = SimpleNamespace()

    result = asyncio.run(plan_start(update, context))

    assert result == PLAN_DATE
    assert "Выберите дату плана" in update.message.text
    keyboard = update.message.kwargs["reply_markup"]
    assert [[button.text for button in row] for row in keyboard.keyboard] == [
        ["Сегодня", "Завтра"]
    ]
    assert keyboard.is_persistent is True
    assert keyboard.input_field_placeholder == "Или введите YYYY-MM-DD"


def test_plan_date_parser_accepts_tomorrow_and_future_iso_date() -> None:
    from datetime import date, timedelta

    from app.bot.handlers import _parse_plan_date

    assert _parse_plan_date("Завтра") == date.today() + timedelta(days=1)
    assert _parse_plan_date("2030-01-15") == date(2030, 1, 15)


def test_short_plan_creates_mixed_plan_and_parses_task(monkeypatch) -> None:
    import asyncio
    from datetime import date, timedelta
    from types import SimpleNamespace

    from app.bot.handlers import plan_start

    class Service:
        def get_plan_for_date(self, telegram_id, plan_date):
            assert telegram_id == 42
            assert plan_date == date.today() + timedelta(days=1)
            return None

        def create_plan(self, *, telegram_id, plan_date, day_type, tasks):
            assert telegram_id == 42
            assert plan_date == date.today() + timedelta(days=1)
            assert day_type == "Смешанный"
            assert len(tasks) == 1
            assert tasks[0].text == "Сдать кредитную карту в Сбербанк"
            assert tasks[0].estimated_minutes == 60
            return object()

    class Message:
        async def reply_text(self, text, **kwargs):
            self.text = text

    monkeypatch.setattr("app.bot.handlers._planning_service", lambda context: Service())
    monkeypatch.setattr("app.bot.handlers._format_plan", lambda plan: "План сохранён")
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    context = SimpleNamespace(args=["tomorrow", "Сдать", "кредитную", "карту", "в", "Сбербанк"])

    asyncio.run(plan_start(update, context))

    assert update.message.text == "План сохранён"


def test_short_plan_without_date_creates_task_for_today(monkeypatch) -> None:
    import asyncio
    from datetime import date
    from types import SimpleNamespace

    from app.bot.handlers import plan_start

    class Service:
        def get_plan_for_date(self, telegram_id, plan_date):
            assert telegram_id == 42
            assert plan_date == date.today()
            return None

        def create_plan(self, *, telegram_id, plan_date, day_type, tasks):
            assert plan_date == date.today()
            assert day_type == "Смешанный"
            assert tasks[0].text == "Скачать новый подкаст"
            return object()

    class Message:
        async def reply_text(self, text, **kwargs):
            self.text = text

    monkeypatch.setattr("app.bot.handlers._planning_service", lambda context: Service())
    monkeypatch.setattr("app.bot.handlers._format_plan", lambda plan: "План сохранён")
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    context = SimpleNamespace(args=["Скачать", "новый", "подкаст"])

    asyncio.run(plan_start(update, context))

    assert update.message.text == "План сохранён"


def test_short_plan_keeps_existing_day_type(monkeypatch) -> None:
    import asyncio
    from datetime import date, datetime, timedelta
    from types import SimpleNamespace

    from app.bot.handlers import plan_start
    from app.models.daily_plan import DailyPlan

    existing_plan = DailyPlan(
        id=1,
        user_id=1,
        plan_date=date.today() + timedelta(days=1),
        day_type="Выходной",
        created_at=datetime.now(),
    )

    class Service:
        def get_plan_for_date(self, telegram_id, plan_date):
            return existing_plan

        def create_plan(self, *, telegram_id, plan_date, day_type, tasks):
            assert day_type == "Выходной"
            return object()

    class Message:
        async def reply_text(self, text, **kwargs):
            self.text = text

    monkeypatch.setattr("app.bot.handlers._planning_service", lambda context: Service())
    monkeypatch.setattr("app.bot.handlers._format_plan", lambda plan: "План дополнен")
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    context = SimpleNamespace(args=["tomorrow", "Добавить", "задачу"])

    asyncio.run(plan_start(update, context))

    assert update.message.text == "План дополнен"


def test_short_plan_rejects_missing_task_without_saving(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from app.bot.handlers import plan_start

    class Message:
        async def reply_text(self, text, **kwargs):
            self.text = text

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    context = SimpleNamespace(args=["tomorrow"])

    asyncio.run(plan_start(update, context))

    assert "Формат:" in update.message.text


def test_llm_provider_requests_strict_json_and_validates_response(monkeypatch) -> None:
    import json

    from pydantic import BaseModel, ConfigDict

    from app.services.llm_provider import LLMProvider

    class Result(BaseModel):
        model_config = ConfigDict(extra="forbid")

        summary: str

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self, size):
            return b'{"choices":[{"message":{"content":"{\\"summary\\":\\"ok\\"}"}}]}'

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data)
        assert request.full_url == "https://provider.example/v1/chat/completions"
        assert request.get_header("Authorization") == "Bearer secret"
        assert timeout == 12
        assert payload["max_tokens"] == 100
        assert payload["response_format"]["type"] == "json_schema"
        assert payload["response_format"]["json_schema"]["strict"] is True
        assert payload["provider"]["require_parameters"] is True
        return Response()

    monkeypatch.setattr("app.services.llm_provider.urlopen", fake_urlopen)
    provider = LLMProvider(
        api_key="secret",
        model_name="provider/model",
        base_url="https://provider.example/v1/",
        timeout_seconds=12,
        max_output_tokens=100,
        max_response_bytes=1_000,
    )

    result = provider.generate_json(
        system_prompt="Return JSON.",
        user_prompt="Summarize.",
        response_model=Result,
        max_output_tokens=500,
    )

    assert result == Result(summary="ok")


def test_llm_provider_tries_fallback_models(monkeypatch) -> None:
    import json
    from pydantic import BaseModel

    from app.services.llm_provider import LLMProvider

    class Result(BaseModel):
        summary: str

    class Response:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self, size):
            return self.data

    models = []

    def fake_urlopen(request, timeout):
        model = json.loads(request.data)["model"]
        models.append(model)
        if model == "first/model":
            return Response(b'{"choices":[{"message":{"content":""}}]}')
        return Response(b'{"choices":[{"message":{"content":"{\\"summary\\":\\"ok\\"}"}}]}')

    monkeypatch.setattr("app.services.llm_provider.urlopen", fake_urlopen)
    provider = LLMProvider(
        api_key="secret",
        model_name=["first/model", "second/model", "second/model"],
        base_url="https://provider.example/v1",
        timeout_seconds=12,
        max_output_tokens=100,
        max_response_bytes=1_000,
    )

    result = provider.generate_json(
        system_prompt="Return JSON.", user_prompt="Test.", response_model=Result
    )

    assert result == Result(summary="ok")
    assert models == ["first/model", "second/model"]


def test_llm_provider_rejects_oversized_or_invalid_schema_response(monkeypatch) -> None:
    import pytest
    from pydantic import BaseModel, ConfigDict

    from app.services.llm_provider import LLMProvider, LLMProviderError

    class Result(BaseModel):
        model_config = ConfigDict(extra="forbid")

        summary: str

    class Response:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self, size):
            return self.data

    provider = LLMProvider(
        api_key="secret",
        model_name="provider/model",
        base_url="https://provider.example/v1",
        timeout_seconds=12,
        max_output_tokens=100,
        max_response_bytes=20,
    )
    monkeypatch.setattr(
        "app.services.llm_provider.urlopen",
        lambda request, timeout: Response(b"x" * 21),
    )
    with pytest.raises(LLMProviderError, match="size limit"):
        provider.generate_json(
            system_prompt="Return JSON.", user_prompt="Test.", response_model=Result
        )


def test_llm_provider_handles_timeout_and_empty_response(monkeypatch) -> None:
    import pytest
    from pydantic import BaseModel

    from app.services.llm_provider import LLMProvider, LLMProviderError

    class Result(BaseModel):
        summary: str

    provider = LLMProvider(
        api_key="secret",
        model_name="provider/model",
        base_url="https://provider.example/v1",
        timeout_seconds=1,
        max_output_tokens=100,
        max_response_bytes=1_000,
    )

    def timeout(request, timeout):
        raise TimeoutError()

    monkeypatch.setattr("app.services.llm_provider.urlopen", timeout)
    with pytest.raises(LLMProviderError, match="timed out"):
        provider.generate_json(system_prompt="x", user_prompt="y", response_model=Result)

    class EmptyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self, size):
            return b""

    monkeypatch.setattr(
        "app.services.llm_provider.urlopen", lambda request, timeout: EmptyResponse()
    )
    with pytest.raises(LLMProviderError, match="invalid response"):
        provider.generate_json(system_prompt="x", user_prompt="y", response_model=Result)


def test_ai_estimate_validates_complete_response_and_respects_user_sources() -> None:
    from datetime import UTC, date, datetime

    from app.models.task import Task, TaskStatus, TaskValueSource
    from app.services.ai_estimation import AIEstimateResponse, validate_estimates

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    task = Task(
        id=1,
        daily_plan_id=1,
        text="Задача",
        status=TaskStatus.planned,
        first_planned_date=date.today(),
        priority=8,
        priority_source=TaskValueSource.user,
        effort=5,
        estimated_minutes=60,
        created_at=now,
        updated_at=now,
    )
    response = AIEstimateResponse.model_validate(
        {
            "estimates": [
                {
                    "task_id": 1,
                    "priority": 3,
                    "effort": 7,
                    "estimated_minutes": 90,
                    "priority_confidence": 0.8,
                    "effort_confidence": 0.7,
                    "duration_confidence": 0.6,
                    "explanation": "Нужна более реалистичная оценка.",
                    "missing_data": [],
                }
            ]
        }
    )

    estimate = validate_estimates([task], response)[0]

    assert estimate.applicable_changes == {"effort": 7, "estimated_minutes": 90}


def test_ai_estimation_splits_large_task_lists_into_small_requests() -> None:
    from datetime import UTC, date, datetime

    from app.models.task import Task, TaskStatus
    from app.services.ai_estimation import AIEstimationService, AIEstimateResponse

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    tasks = [
        Task(
            id=index,
            daily_plan_id=1,
            text=f"Задача {index}",
            status=TaskStatus.planned,
            first_planned_date=date.today(),
            created_at=now,
            updated_at=now,
        )
        for index in range(1, 5)
    ]

    class Provider:
        def __init__(self):
            self.calls = 0

        def generate_json(self, *, system_prompt, user_prompt, response_model, **kwargs):
            self.calls += 1
            assert "источником 'default' являются заглушками" in system_prompt
            assert "Не предлагай подзадачи" in system_prompt
            payload = __import__("json").loads(user_prompt.split("Задачи:\n", 1)[1])
            return AIEstimateResponse.model_validate(
                {
                    "estimates": [
                        {
                            "task_id": item["id"], "priority": 5, "effort": 5,
                            "estimated_minutes": 60, "priority_confidence": 0.5,
                            "effort_confidence": 0.5, "duration_confidence": 0.5,
                            "explanation": "Оценка.",
                        }
                        for item in payload
                    ]
                }
            )

    provider = Provider()
    estimates = AIEstimationService(provider).estimate(tasks)

    assert provider.calls == 2
    assert [estimate.task.id for estimate in estimates] == [1, 2, 3, 4]


def test_ai_estimation_retries_temporary_provider_errors(monkeypatch, tmp_path) -> None:
    from datetime import UTC, date, datetime

    from app.models.task import Task, TaskStatus
    from app.services.ai_estimation import AIEstimationService, AIEstimateResponse
    from app.services.llm_provider import LLMProviderError

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    task = Task(id=1, daily_plan_id=1, text="Задача", status=TaskStatus.planned,
                first_planned_date=date.today(), created_at=now, updated_at=now)

    class Provider:
        calls = 0

        def generate_json(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise LLMProviderError("LLM provider returned HTTP 429.")
            return AIEstimateResponse.model_validate({"estimates": [{
                "task_id": 1, "priority": 5, "effort": 5, "estimated_minutes": 60,
                "priority_confidence": 0.5, "effort_confidence": 0.5,
                "duration_confidence": 0.5, "explanation": "Оценка.",
            }]})

    monkeypatch.setattr("app.services.ai_estimation.time.sleep", lambda seconds: None)
    provider = Provider()
    assert len(
        AIEstimationService(provider, debug_log_path=tmp_path / "ai-errors.jsonl").estimate([task])
    ) == 1
    assert provider.calls == 2


def test_ai_estimation_writes_safe_debug_json_for_provider_error(tmp_path) -> None:
    from datetime import UTC, date, datetime
    import json

    import pytest

    from app.models.task import Task, TaskStatus
    from app.services.ai_estimation import AIEstimationService
    from app.services.llm_provider import LLMProviderError

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    task = Task(id=7, daily_plan_id=1, text="Секретное название", status=TaskStatus.planned,
                first_planned_date=date.today(), created_at=now, updated_at=now)

    class Provider:
        def generate_json(self, **kwargs):
            raise LLMProviderError("LLM provider returned HTTP 400.")

    log_path = tmp_path / "ai-errors.jsonl"
    with pytest.raises(LLMProviderError):
        AIEstimationService(Provider(), debug_log_path=log_path).estimate([task])

    record = json.loads(log_path.read_text().strip())
    assert record["task_ids"] == [7]
    assert record["error"] == "LLM provider returned HTTP 400."
    assert "Секретное название" not in log_path.read_text()


def test_ai_estimate_rejects_unknown_ids_and_out_of_range_values() -> None:
    from datetime import UTC, date, datetime

    import pytest
    from pydantic import ValidationError

    from app.models.task import Task, TaskStatus
    from app.services.ai_estimation import AIEstimateResponse, validate_estimates

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    task = Task(
        id=1,
        daily_plan_id=1,
        text="Задача",
        status=TaskStatus.planned,
        first_planned_date=date.today(),
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(ValidationError):
        AIEstimateResponse.model_validate({"estimates": []})
    with pytest.raises(ValidationError):
        AIEstimateResponse.model_validate(
            {"estimates": [{"task_id": 1, "priority": 11}]}
        )

    unknown = AIEstimateResponse.model_validate(
        {
            "estimates": [
                {
                    "task_id": 2,
                    "priority": 5,
                    "effort": 5,
                    "estimated_minutes": 60,
                    "priority_confidence": 0.5,
                    "effort_confidence": 0.5,
                    "duration_confidence": 0.5,
                    "explanation": "Оценка.",
                }
            ]
        }
    )
    with pytest.raises(ValueError, match="task ID"):
        validate_estimates([task], unknown)


def test_ai_estimate_draft_round_trip_preserves_proposals() -> None:
    from datetime import date, datetime

    from app.models.task import Task, TaskStatus
    from app.services.ai_estimation import (
        AIEstimateResponse,
        dump_estimates,
        load_draft_estimates,
        validate_estimates,
    )

    task = Task(
        id=41,
        daily_plan_id=7,
        text="Подготовить отчёт",
        status=TaskStatus.planned,
        first_planned_date=date(2026, 7, 14),
        estimated_minutes=60,
        created_at=datetime(2026, 7, 14),
        updated_at=datetime(2026, 7, 14),
    )
    response = AIEstimateResponse.model_validate(
        {"estimates": [{
            "task_id": 41,
            "priority": 7,
            "effort": 6,
            "estimated_minutes": 90,
            "priority_confidence": 0.8,
            "effort_confidence": 0.7,
            "duration_confidence": 0.6,
            "explanation": "Нужна подготовка данных.",
            "missing_data": [],
        }]}
    )

    stored = dump_estimates(validate_estimates([task], response))
    restored = load_draft_estimates([task], [proposal for _, proposal in stored])

    assert restored[0].task.id == 41
    assert restored[0].proposal.estimated_minutes == 90


def test_ai_estimate_draft_keyboard_offers_reopen_and_regenerate() -> None:
    from app.bot.keyboards import ai_estimate_draft_keyboard

    keyboard = ai_estimate_draft_keyboard()

    assert [button.callback_data for row in keyboard.inline_keyboard for button in row] == [
        "aiest:open",
        "aiest:new",
        "aiest:cancel",
    ]


def test_ai_estimate_overview_shows_only_pending_changes() -> None:
    from datetime import date, datetime

    from app.bot.handlers import _format_ai_estimate_overview
    from app.models.task import Task, TaskStatus
    from app.services.ai_estimation import AIEstimateResponse, validate_estimates

    task = Task(
        id=50,
        daily_plan_id=1,
        text="Подготовить отчёт",
        status=TaskStatus.planned,
        first_planned_date=date(2026, 7, 14),
        estimated_minutes=60,
        created_at=datetime(2026, 7, 14),
        updated_at=datetime(2026, 7, 14),
    )
    changed = AIEstimateResponse.model_validate(
        {"estimates": [{
            "task_id": 50,
            "priority": 5,
            "effort": 7,
            "estimated_minutes": 90,
            "priority_confidence": 0.5,
            "effort_confidence": 0.8,
            "duration_confidence": 0.8,
            "explanation": "Нужна подготовка.",
            "missing_data": [],
        }]}
    )
    unchanged = AIEstimateResponse.model_validate(
        {"estimates": [{
            "task_id": 50,
            "priority": 5,
            "effort": 5,
            "estimated_minutes": 60,
            "priority_confidence": 0.5,
            "effort_confidence": 0.5,
            "duration_confidence": 0.5,
            "explanation": "Без изменений.",
            "missing_data": [],
        }]}
    )

    overview = _format_ai_estimate_overview(validate_estimates([task], changed))
    assert "сложность 5 → 7" in overview[0]
    assert "длительность 60 → 90 мин" in overview[0]
    assert _format_ai_estimate_overview(validate_estimates([task], unchanged)) == [
        "🤖 Нерассмотренных AI-предложений не осталось."
    ]


def test_ai_estimate_drafts_migration_has_expiration_and_task_items() -> None:
    from pathlib import Path

    migration = Path("app/db/migrations/009_add_ai_estimate_drafts.sql").read_text()

    assert "ai_estimate_drafts" in migration
    assert "ai_estimate_draft_items" in migration
    assert "INTERVAL '24 hours'" in migration


def test_ai_estimate_item_decisions_migration_has_dismissed_state() -> None:
    from pathlib import Path

    migration = Path("app/db/migrations/010_add_ai_estimate_item_decisions.sql").read_text()

    assert "decision" in migration
    assert "dismissed" in migration


def test_ai_plan_rejects_incomplete_task_ids() -> None:
    from datetime import date, datetime

    import pytest

    from app.models.task import Task, TaskStatus
    from app.services.ai_planning import AIPlanResponse, validate_plan_proposal

    tasks = [
        Task(
            id=index,
            daily_plan_id=1,
            text=f"Задача {index}",
            status=TaskStatus.planned,
            first_planned_date=date(2026, 7, 15),
            created_at=datetime(2026, 7, 14),
            updated_at=datetime(2026, 7, 14),
        )
        for index in (1, 2)
    ]

    with pytest.raises(ValueError, match="неполный"):
        validate_plan_proposal(tasks, AIPlanResponse(ordered_task_ids=[1]))


def test_ai_plan_calculates_slots_with_fifteen_minute_buffer() -> None:
    from datetime import date, datetime

    from app.models.task import Task, TaskStatus
    from app.services.ai_planning import AIPlanProposal, calculate_schedule

    tasks = [
        Task(
            id=index,
            daily_plan_id=1,
            text=f"Задача {index}",
            status=TaskStatus.planned,
            first_planned_date=date(2026, 7, 15),
            estimated_minutes=duration,
            created_at=datetime(2026, 7, 14),
            updated_at=datetime(2026, 7, 14),
        )
        for index, duration in ((1, 30), (2, 60))
    ]
    schedule = calculate_schedule(
        AIPlanProposal(ordered_tasks=tasks, deferred_tasks=[]),
        plan_date=date(2026, 7, 15),
        timezone="Europe/Moscow",
        available_minutes=120,
        now=datetime(2026, 7, 14, 12),
    )

    assert [(slot.starts_at.hour, slot.starts_at.minute) for slot in schedule.slots] == [
        (8, 0),
        (8, 45),
    ]
    assert schedule.slots[0].buffer_after_minutes == 15
    assert schedule.slots[1].buffer_after_minutes == 0
    assert schedule.scheduled_minutes == 105


def test_ai_plan_defers_task_without_duration() -> None:
    from datetime import date, datetime

    from app.models.task import Task, TaskStatus
    from app.services.ai_planning import AIPlanProposal, calculate_schedule

    task = Task(
        id=1,
        daily_plan_id=1,
        text="Неизвестная длительность",
        status=TaskStatus.planned,
        first_planned_date=date(2026, 7, 15),
        estimated_minutes=None,
        created_at=datetime(2026, 7, 14),
        updated_at=datetime(2026, 7, 14),
    )
    schedule = calculate_schedule(
        AIPlanProposal(ordered_tasks=[task], deferred_tasks=[]),
        plan_date=date(2026, 7, 15),
        timezone="Europe/Moscow",
        available_minutes=120,
        now=datetime(2026, 7, 14, 12),
    )

    assert schedule.slots == []
    assert schedule.deferred_tasks[0][1] == "Не указана длительность задачи."


def test_ai_plan_retries_and_writes_safe_debug_json(monkeypatch, tmp_path) -> None:
    from datetime import date, datetime
    import json

    from app.models.task import Task, TaskStatus
    from app.services.ai_planning import AIPlanResponse, AIPlanningService
    from app.services.llm_provider import LLMProviderError

    task = Task(
        id=70,
        daily_plan_id=1,
        text="Секретное название задачи",
        status=TaskStatus.planned,
        first_planned_date=date(2026, 7, 15),
        created_at=datetime(2026, 7, 14),
        updated_at=datetime(2026, 7, 14),
    )

    class Provider:
        calls = 0

        def generate_json(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise LLMProviderError("LLM provider returned HTTP 429.")
            return AIPlanResponse(ordered_task_ids=[70])

    log_path = tmp_path / "ai-plan-errors.jsonl"
    monkeypatch.setattr("app.services.ai_planning.clock.sleep", lambda seconds: None)
    proposal = AIPlanningService(Provider(), debug_log_path=log_path).propose(
        [task], available_minutes=120
    )

    assert [item.id for item in proposal.ordered_tasks] == [70]
    record = json.loads(log_path.read_text().strip())
    assert record["task_ids"] == [70]
    assert record["error"] == "LLM provider returned HTTP 429."
    assert "Секретное название" not in log_path.read_text()


def test_daily_schedule_migration_creates_runs_and_slots() -> None:
    from pathlib import Path

    migration = Path("app/db/migrations/011_add_daily_schedule_runs.sql").read_text()

    assert "daily_schedule_runs" in migration
    assert "daily_schedule_slots" in migration
    assert "superseded" in migration
    assert "stale" in migration


def test_plan_date_starts_day_type_selection_for_new_plan(monkeypatch) -> None:
    import asyncio
    from datetime import date
    from types import SimpleNamespace

    from app.bot.handlers import DAY_TYPE, receive_plan_date

    class PlanningService:
        def get_plan_for_date(self, telegram_id, plan_date):
            assert plan_date == date.today()
            return None

    class Message:
        text = "today"

        async def reply_text(self, text, **kwargs):
            self.text_reply = text
            self.kwargs = kwargs

    monkeypatch.setattr(
        "app.bot.handlers._planning_service",
        lambda context: PlanningService(),
    )
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    context = SimpleNamespace(user_data={})

    result = asyncio.run(receive_plan_date(update, context))

    assert result == DAY_TYPE
    assert context.user_data["plan_date"] == date.today().isoformat()
    assert "Какой это будет день" in update.message.text_reply


def test_feasibility_time_choice_shows_default_button(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from app.bot.handlers import FEASIBILITY_TIME, receive_feasibility_date

    class TaskService:
        def get_available_minutes(self, telegram_id, plan_date):
            return 240

    class Message:
        text = "today"

        async def reply_text(self, text, **kwargs):
            self.text_reply = text
            self.kwargs = kwargs

    monkeypatch.setattr("app.bot.handlers._task_service", lambda context: TaskService())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    context = SimpleNamespace(user_data={})

    result = asyncio.run(receive_feasibility_date(update, context))

    assert result == FEASIBILITY_TIME
    assert "введите своё время" in update.message.text_reply
    keyboard = update.message.kwargs["reply_markup"]
    assert [[button.text for button in row] for row in keyboard.keyboard] == [
        ["По умолчанию"]
    ]


def test_move_task_indexes_accept_comma_separated_unique_numbers() -> None:
    from app.bot.handlers import _parse_task_indexes

    assert _parse_task_indexes("1, 2, 2, 6", maximum=6) == [1, 2, 6]


def test_move_task_indexes_reject_out_of_range_numbers() -> None:
    from app.bot.handlers import _parse_task_indexes

    assert _parse_task_indexes("1, 7", maximum=6) is None


def test_unschedule_task_moves_comma_separated_tasks_from_today(monkeypatch) -> None:
    import asyncio
    from datetime import UTC, date, datetime
    from types import SimpleNamespace

    from app.bot.handlers import unschedule_task
    from app.models.task import Task, TaskStatus

    tasks = [
        Task(
            id=index,
            daily_plan_id=1,
            text=f"Задача {index}",
            status=TaskStatus.planned,
            first_planned_date=date.today(),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        for index in (1, 2, 3)
    ]

    class Service:
        def get_visible_tasks_for_date(self, telegram_id, plan_date):
            assert telegram_id == 42
            assert plan_date == date.today()
            return tasks

        def move_tasks_to_backlog(self, task_ids, *, telegram_id):
            assert task_ids == [1, 2]
            assert telegram_id == 42
            return tasks[:2]

    class Message:
        text = ""
        reply = ""

        async def reply_text(self, value):
            self.reply = value

    monkeypatch.setattr("app.bot.handlers._task_service", lambda context: Service())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    result = asyncio.run(unschedule_task(update, SimpleNamespace(args=["1, 2"])))

    assert result == -1
    assert "перенесено: 2" in update.message.reply


def test_unschedule_task_uses_explicit_source_date(monkeypatch) -> None:
    import asyncio
    from datetime import UTC, date, datetime
    from types import SimpleNamespace

    from app.bot.handlers import unschedule_task
    from app.models.task import Task, TaskStatus

    task = Task(
        id=7,
        daily_plan_id=1,
        text="Задача",
        status=TaskStatus.planned,
        first_planned_date=date(2026, 7, 16),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    class Service:
        def get_visible_tasks_for_date(self, telegram_id, plan_date):
            assert plan_date == date(2026, 7, 16)
            return [task]

        def move_tasks_to_backlog(self, task_ids, *, telegram_id):
            assert task_ids == [7]
            return [task]

    class Message:
        text = ""
        reply = ""

        async def reply_text(self, value):
            self.reply = value

    monkeypatch.setattr("app.bot.handlers._task_service", lambda context: Service())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    asyncio.run(unschedule_task(update, SimpleNamespace(args=["2026-07-16", "1"])))

    assert "перенесено: 1" in update.message.reply


def test_unschedule_task_ignores_spaces_after_commas(monkeypatch) -> None:
    import asyncio
    from datetime import UTC, date, datetime
    from types import SimpleNamespace

    from app.bot.handlers import unschedule_task
    from app.models.task import Task, TaskStatus

    tasks = [
        Task(id=index, daily_plan_id=1, text=f"Задача {index}", status=TaskStatus.planned,
             first_planned_date=date(2026, 7, 16), created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
        for index in (1, 2, 3)
    ]

    class Service:
        def get_visible_tasks_for_date(self, telegram_id, plan_date):
            assert plan_date == date(2026, 7, 16)
            return tasks

        def move_tasks_to_backlog(self, task_ids, *, telegram_id):
            assert task_ids == [1, 2, 3]
            return tasks

    class Message:
        async def reply_text(self, value):
            self.reply = value

    monkeypatch.setattr("app.bot.handlers._task_service", lambda context: Service())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    asyncio.run(unschedule_task(update, SimpleNamespace(args=["2026-07-16", "1,", "2,", "3"])))

    assert "перенесено: 3" in update.message.reply


def test_quick_done_marks_multiple_tasks_and_ignores_spaces(monkeypatch) -> None:
    import asyncio
    from datetime import UTC, date, datetime
    from types import SimpleNamespace

    from app.bot.handlers import _quick_done
    from app.models.task import Task, TaskStatus

    tasks = [
        Task(id=index, daily_plan_id=1, text=f"Задача {index}", status=TaskStatus.planned,
             first_planned_date=date.today(), created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
        for index in (15, 16, 17)
    ]

    class Service:
        completed_ids: list[int] = []

        def get_visible_tasks_for_date(self, telegram_id, plan_date):
            assert plan_date == date.today()
            return tasks

        def mark_done(self, task_id, telegram_id):
            self.completed_ids.append(task_id)
            return next(task for task in tasks if task.id == task_id)

    class Message:
        async def reply_text(self, value):
            self.reply = value

    service = Service()
    monkeypatch.setattr("app.bot.handlers._task_service", lambda context: service)
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    asyncio.run(_quick_done(update, SimpleNamespace(args=["1,", " 2,", "3"])))

    assert service.completed_ids == [15, 16, 17]
    assert "Отмечено выполненными: 3" in update.message.reply


def test_task_defaults_keep_existing_tasks_compatible() -> None:
    from datetime import date, datetime

    from app.models.task import Task, TaskStatus

    task = Task(
        id=1,
        daily_plan_id=1,
        text="Подготовить план",
        status=TaskStatus.planned,
        first_planned_date=date.today(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    assert task.estimated_minutes is None
    assert task.due_at is None
    assert task.priority == 5
    assert task.effort == 5
    assert task.context is None


def test_task_line_parser_reads_inline_parameters() -> None:
    from app.services.task_input_parser import parse_task_lines

    task = parse_task_lines(
        [
            "Подготовить отчёт -длительность:2часа -время начала:10:00 "
            "-дедлайн:19:00 -важность:5 -сложность:8 контекст:звонок"
        ]
    )[0]

    assert task.text == "Подготовить отчёт"
    assert task.estimated_minutes == 120
    assert task.start_time is not None and task.start_time.isoformat() == "10:00:00"
    assert task.due_time is not None and task.due_time.isoformat() == "19:00:00"
    assert task.priority == 5
    assert task.effort == 8
    assert task.context == "звонок"


def test_task_line_parser_uses_one_hour_duration_by_default() -> None:
    from app.services.task_input_parser import parse_task_lines

    task = parse_task_lines(["Подготовить отчёт"])[0]

    assert task.estimated_minutes == 60


def test_default_duration_migration_sets_existing_tasks_to_one_hour() -> None:
    from pathlib import Path

    migration = Path("app/db/migrations/007_set_default_task_duration.sql").read_text()

    assert "UPDATE tasks" in migration
    assert "UPDATE unscheduled_tasks" in migration
    assert migration.count("estimated_minutes = 60") == 2


def test_task_line_parser_rejects_invalid_values() -> None:
    import pytest

    from app.services.task_input_parser import TaskInputError, parse_task_lines

    with pytest.raises(TaskInputError, match="от 1 до 10"):
        parse_task_lines(["Подготовить отчёт -важность:11"])


def test_task_line_parser_accepts_short_duration_formats() -> None:
    from app.services.task_input_parser import parse_task_lines

    tasks = parse_task_lines(
        [
            "Короткая задача -длительность:2 ч",
            "Ещё задача -длительность:30 м",
            "Длинная задача -длительность:1:30",
        ]
    )

    assert [task.estimated_minutes for task in tasks] == [120, 30, 90]


def test_neutral_task_without_signals_has_priority_50() -> None:
    from datetime import UTC, date, datetime

    from app.models.task import Task, TaskStatus
    from app.services.task_prioritization import assess_task

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    task = Task(
        id=1,
        daily_plan_id=1,
        text="Обычная задача",
        status=TaskStatus.planned,
        first_planned_date=date.today(),
        estimated_minutes=None,
        created_at=now,
        updated_at=now,
    )

    assessment = assess_task(task, now=now)

    assert assessment.score == 50
    assert assessment.breakdown.importance == 0
    assert assessment.breakdown.deadline == 0
    assert assessment.breakdown.postponements == 0
    assert assessment.breakdown.dependencies == 0


def test_importance_is_symmetric_around_five() -> None:
    from datetime import UTC, date, datetime

    from app.models.task import Task, TaskStatus
    from app.services.task_prioritization import assess_task

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)

    def score(importance: int) -> int:
        task = Task(
            id=importance,
            daily_plan_id=1,
            text="Задача",
            status=TaskStatus.planned,
            first_planned_date=date.today(),
            priority=importance,
            created_at=now,
            updated_at=now,
        )
        return assess_task(task, now=now).score

    assert score(1) == 34
    assert score(5) == 50
    assert score(8) == 62
    assert score(10) == 70


def test_deadline_is_counted_once_and_duration_does_not_change_priority() -> None:
    from datetime import UTC, date, datetime, timedelta

    from app.models.task import Task, TaskStatus
    from app.services.task_prioritization import assess_task

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    task = Task(
        id=1,
        daily_plan_id=1,
        text="Срочная задача",
        status=TaskStatus.planned,
        first_planned_date=date.today(),
        due_at=now + timedelta(hours=1),
        estimated_minutes=20,
        created_at=now,
        updated_at=now,
    )

    assessment = assess_task(task, now=now)

    assert assessment.breakdown.deadline == 30
    assert assessment.score == 80

    long_task = task.model_copy(update={"estimated_minutes": 480})
    assert assess_task(long_task, now=now).score == assessment.score


def test_deadline_and_postponement_modifiers_are_capped() -> None:
    from datetime import UTC, date, datetime, timedelta

    from app.models.task import Task, TaskStatus
    from app.services.task_prioritization import assess_task

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    overdue = Task(
        id=1,
        daily_plan_id=1,
        text="Просроченная задача",
        status=TaskStatus.planned,
        first_planned_date=date.today(),
        due_at=now - timedelta(days=1),
        postponement_count=10,
        created_at=now,
        updated_at=now,
    )

    assessment = assess_task(overdue, now=now)

    assert assessment.breakdown.deadline == 35
    assert assessment.breakdown.postponements == 8
    assert assessment.score == 93

    highest = overdue.model_copy(update={"priority": 10})
    assert assess_task(highest, now=now).score == 100


def test_priority_explanation_lists_scores_and_reasons() -> None:
    from datetime import UTC, date, datetime, timedelta

    from app.models.task import Task, TaskStatus
    from app.services.task_prioritization import assess_task, explain_priority_factors

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    task = Task(
        id=1,
        daily_plan_id=1,
        text="Срочная задача",
        status=TaskStatus.planned,
        first_planned_date=date.today(),
        due_at=now + timedelta(hours=1),
        estimated_minutes=30,
        priority=8,
        postponement_count=2,
        created_at=now,
        updated_at=now,
    )

    factors = explain_priority_factors(assess_task(task, now=now))

    assert factors == [
        ("Важность", 12, "важность 8/10"),
        ("Дедлайн", 30, "дедлайн в ближайшие 2 часа"),
        ("Переносы", 6, "переносов: 2"),
    ]


def test_long_telegram_message_is_split_within_limit() -> None:
    from app.bot.handlers import _split_telegram_message

    text = ("Строка аналитики\n" * 1_000).strip()

    chunks = _split_telegram_message(text)

    assert len(chunks) > 1
    assert all(len(chunk) <= 4_000 for chunk in chunks)
    assert "".join(chunks) == text


def test_only_elevated_planned_tasks_move_to_top() -> None:
    from datetime import UTC, date, datetime, timedelta

    from app.models.task import Task, TaskStatus
    from app.services.task_prioritization import order_tasks_by_priority

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    tasks = [
        Task(
            id=1,
            daily_plan_id=1,
            text="Обычная задача",
            status=TaskStatus.planned,
            first_planned_date=date.today(),
            created_at=now,
            updated_at=now,
        ),
        Task(
            id=2,
            daily_plan_id=1,
            text="Срочная задача",
            status=TaskStatus.planned,
            first_planned_date=date.today(),
            due_at=now + timedelta(hours=1),
            priority=8,
            created_at=now,
            updated_at=now,
        ),
    ]

    assessments = order_tasks_by_priority(tasks, now=now)

    assert [assessment.task.id for assessment in assessments] == [2, 1]
    assert assessments[0].emoji is not None
    assert assessments[1].emoji is None


def test_task_card_keyboard_excludes_cancelled_tasks() -> None:
    from datetime import UTC, date, datetime

    from app.bot.keyboards import task_details_keyboard
    from app.models.task import Task, TaskStatus

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    tasks = [
        Task(
            id=1,
            daily_plan_id=1,
            text="Активная задача",
            status=TaskStatus.planned,
            first_planned_date=date.today(),
            created_at=now,
            updated_at=now,
        ),
        Task(
            id=2,
            daily_plan_id=1,
            text="Отменённая задача",
            status=TaskStatus.cancelled,
            first_planned_date=date.today(),
            created_at=now,
            updated_at=now,
        ),
    ]

    keyboard = task_details_keyboard(tasks)

    assert len(keyboard.inline_keyboard) == 1
    assert keyboard.inline_keyboard[0][0].callback_data == "task:1"


def test_task_edit_parser_updates_parameters_and_title() -> None:
    from app.models.task import TaskStatus
    from app.services.task_input_parser import parse_task_update

    update = parse_task_update(
        "-название:Новый отчёт -важность:2 -сложность:8 -длительность:1:30 -статус:выполнена"
    )

    assert update.text == "Новый отчёт"
    assert update.priority == 2
    assert update.effort == 8
    assert update.estimated_minutes == 90
    assert update.status == TaskStatus.done


def test_task_edit_parser_rejects_unstructured_title_and_unknown_parameter() -> None:
    import pytest

    from app.services.task_input_parser import TaskInputError, parse_task_update

    with pytest.raises(TaskInputError, match="формате"):
        parse_task_update("Новое название -важность:2")
    with pytest.raises(TaskInputError, match="Неизвестный параметр"):
        parse_task_update("-неизвестно:1")


def test_feasibility_counts_only_planned_tasks_with_known_duration() -> None:
    from datetime import UTC, date, datetime

    from app.models.task import Task, TaskStatus
    from app.services.feasibility import analyze_plan_feasibility

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    tasks = [
        Task(
            id=1,
            daily_plan_id=1,
            text="Низкий приоритет",
            status=TaskStatus.planned,
            first_planned_date=date.today(),
            estimated_minutes=90,
            priority=2,
            created_at=now,
            updated_at=now,
        ),
        Task(
            id=2,
            daily_plan_id=1,
            text="Без оценки",
            status=TaskStatus.planned,
            first_planned_date=date.today(),
            created_at=now,
            updated_at=now,
        ),
        Task(
            id=3,
            daily_plan_id=1,
            text="Уже выполнена",
            status=TaskStatus.done,
            first_planned_date=date.today(),
            estimated_minutes=120,
            created_at=now,
            updated_at=now,
        ),
    ]

    result = analyze_plan_feasibility(tasks, available_minutes=60)

    assert result.scheduled_minutes == 90
    assert result.unknown_duration_count == 1
    assert result.remaining_minutes == -30
    assert [candidate.task.id for candidate in result.move_candidates] == [1]


def test_priority_groups_and_short_report_hide_zero_factors() -> None:
    from datetime import UTC, date, datetime, timedelta

    from app.models.task import Task, TaskStatus
    from app.services.feasibility import analyze_plan_feasibility
    from app.services.priority_reporting import (
        format_feasibility_report,
        group_priority_assessments,
    )

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    neutral = Task(
        id=1,
        daily_plan_id=1,
        text="Обычная",
        status=TaskStatus.planned,
        first_planned_date=date.today(),
        estimated_minutes=60,
        created_at=now,
        updated_at=now,
    )
    critical = neutral.model_copy(
        update={"id": 2, "text": "Срочная", "priority": 10, "due_at": now + timedelta(hours=1)}
    )

    groups = group_priority_assessments([neutral, critical], now=now)
    report = format_feasibility_report(
        date.today(),
        analyze_plan_feasibility([neutral, critical], available_minutes=180),
        now=now,
    )

    assert [item.task.id for item in groups[("🔴", "Критический приоритет")]] == [2]
    assert [item.task.id for item in groups[("⚪", "Обычный приоритет")]] == [1]
    assert "дедлайн не указан" not in report
    assert "задача не переносилась" not in report
    assert "Обычная — 50/100" in report


def test_short_report_limits_large_priority_group_to_five_tasks() -> None:
    from datetime import UTC, date, datetime

    from app.models.task import Task, TaskStatus
    from app.services.feasibility import analyze_plan_feasibility
    from app.services.priority_reporting import format_feasibility_report

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    tasks = [
        Task(
            id=index,
            daily_plan_id=1,
            text=f"Обычная задача {index}",
            status=TaskStatus.planned,
            first_planned_date=date.today(),
            estimated_minutes=60,
            created_at=now,
            updated_at=now,
        )
        for index in range(1, 7)
    ]

    report = format_feasibility_report(
        date.today(), analyze_plan_feasibility(tasks, available_minutes=600), now=now
    )

    assert "⚪ Обычный приоритет — 6 задач" in report
    assert "Обычная задача 5" in report
    assert "Обычная задача 6" not in report
    assert "…и ещё 1 задача." in report


def test_details_show_base_and_only_nonzero_modifiers() -> None:
    from datetime import UTC, date, datetime

    from app.models.task import Task, TaskStatus
    from app.services.priority_reporting import format_priority_details

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    task = Task(
        id=1,
        daily_plan_id=1,
        text="Нейтральная задача",
        status=TaskStatus.planned,
        first_planned_date=date.today(),
        created_at=now,
        updated_at=now,
    )

    details = format_priority_details(date.today(), [task], now=now)

    assert "Базовый приоритет: 50" in details
    assert "Итог: 50/100" in details
    assert "Дедлайн:" not in details
    assert "Переносы:" not in details


def test_details_recommend_review_after_three_postponements() -> None:
    from datetime import UTC, date, datetime

    from app.models.task import Task, TaskStatus
    from app.services.priority_reporting import format_priority_details

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    task = Task(
        id=1,
        daily_plan_id=1,
        text="Застрявшая задача",
        status=TaskStatus.planned,
        first_planned_date=date.today(),
        postponement_count=3,
        created_at=now,
        updated_at=now,
    )

    details = format_priority_details(date.today(), [task], now=now)

    assert "Задача переносилась уже 3 раза" in details
    assert "разбить задачу на подзадачи" in details


def test_move_recommendation_frees_overload_and_marks_equal_choices_ambiguous() -> None:
    from datetime import UTC, date, datetime

    from app.models.task import Task, TaskStatus
    from app.services.feasibility import analyze_plan_feasibility, recommend_moves

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    tasks = [
        Task(
            id=index,
            daily_plan_id=1,
            text=f"Обычная {index}",
            status=TaskStatus.planned,
            first_planned_date=date.today(),
            estimated_minutes=60,
            created_at=now,
            updated_at=now,
        )
        for index in range(1, 5)
    ]

    result = analyze_plan_feasibility(tasks, available_minutes=90)
    recommendation = recommend_moves(result)

    assert recommendation.freed_minutes >= 150
    assert recommendation.ambiguous is True
    assert recommendation.ambiguous_task_count == 4


def test_available_time_parser_accepts_clock_duration() -> None:
    from app.services.task_input_parser import parse_available_minutes

    assert parse_available_minutes("6:30") == 390


def test_day_capacity_defaults_depend_on_day_type() -> None:
    from app.services.day_capacity import default_available_minutes

    assert default_available_minutes("Рабочий день") == 4 * 60
    assert default_available_minutes("Выходной") == 14 * 60
    assert default_available_minutes("Больничный") == 8 * 60
    assert default_available_minutes("Смешанный") == 8 * 60


def test_today_capacity_is_capped_by_remaining_time_until_22(monkeypatch) -> None:
    from datetime import UTC, date, datetime

    from app.services.day_capacity import available_minutes_for_date

    plan_date = date(2026, 7, 14)
    assert available_minutes_for_date(
        14 * 60,
        plan_date,
        "Europe/Moscow",
        now=datetime(2026, 7, 14, 5, tzinfo=UTC),  # 08:00 Moscow
    ) == 14 * 60
    assert available_minutes_for_date(
        14 * 60,
        plan_date,
        "Europe/Moscow",
        now=datetime(2026, 7, 14, 17, tzinfo=UTC),  # 20:00 Moscow
    ) == 2 * 60
    assert available_minutes_for_date(
        14 * 60,
        plan_date,
        "Europe/Moscow",
        now=datetime(2026, 7, 14, 19, tzinfo=UTC),  # 22:00 Moscow
    ) == 0


def test_future_plan_capacity_is_not_reduced_by_current_time() -> None:
    from datetime import UTC, date, datetime

    from app.services.day_capacity import available_minutes_for_date

    assert available_minutes_for_date(
        14 * 60,
        date(2026, 7, 15),
        "Europe/Moscow",
        now=datetime(2026, 7, 14, 19, tzinfo=UTC),
    ) == 14 * 60


def test_feasibility_keyboard_has_all_overload_actions() -> None:
    from app.bot.keyboards import feasibility_move_keyboard

    keyboard = feasibility_move_keyboard()

    assert [row[0].callback_data for row in keyboard.inline_keyboard] == [
        "feasmove:default",
        "feasmove:select",
        "feasmove:skip",
    ]


def test_task_input_parser_accepts_priority_parameter_without_dash() -> None:
    from app.services.task_input_parser import parse_task_lines

    task = parse_task_lines(["Добавить команду идеи важность:5"])[0]

    assert task.text == "Добавить команду идеи"
    assert task.priority == 5


def test_schedule_keyboard_marks_ideas_and_unscheduled_tasks() -> None:
    from datetime import UTC, datetime

    from app.bot.keyboards import schedule_source_keyboard
    from app.models.idea import Idea
    from app.models.unscheduled_task import UnscheduledTask

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    keyboard = schedule_source_keyboard(
        [UnscheduledTask(id=1, user_id=1, text="Без даты", created_at=now, updated_at=now)],
        [Idea(id=2, user_id=1, text="Идея", created_at=now)],
    )

    assert [row[0].callback_data for row in keyboard.inline_keyboard] == [
        "schedule:task:1",
        "schedule:idea:2",
    ]


def test_quick_done_uses_the_number_shown_in_today(monkeypatch) -> None:
    import asyncio
    from datetime import UTC, date, datetime
    from types import SimpleNamespace

    from app.bot.handlers import _quick_done
    from app.models.task import Task, TaskStatus

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    done_task = Task(
        id=1,
        daily_plan_id=1,
        text="Уже выполнена",
        status=TaskStatus.done,
        first_planned_date=date.today(),
        created_at=now,
        updated_at=now,
    )
    planned_task = Task(
        id=2,
        daily_plan_id=1,
        text="Нужно завершить",
        status=TaskStatus.planned,
        first_planned_date=date.today(),
        created_at=now,
        updated_at=now,
    )

    class Service:
        def __init__(self) -> None:
            self.done_task_id: int | None = None

        def get_visible_tasks_for_date(self, telegram_id, plan_date):
            return [done_task, planned_task]

        def mark_done(self, task_id, telegram_id):
            self.done_task_id = task_id
            return planned_task

    class Message:
        async def reply_text(self, text):
            self.text = text

    service = Service()
    monkeypatch.setattr("app.bot.handlers._task_service", lambda context: service)
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    context = SimpleNamespace(args=["2"])

    asyncio.run(_quick_done(update, context))

    assert service.done_task_id == 2


def test_quick_move_accepts_a_future_source_date(monkeypatch) -> None:
    import asyncio
    from datetime import UTC, date, datetime
    from types import SimpleNamespace

    from app.bot.handlers import _quick_move_tasks
    from app.models.task import Task, TaskStatus

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    tasks = [
        Task(
            id=1,
            daily_plan_id=1,
            text="Будущая задача 1",
            status=TaskStatus.planned,
            first_planned_date=date(2026, 7, 16),
            created_at=now,
            updated_at=now,
        ),
        Task(
            id=2,
            daily_plan_id=1,
            text="Будущая задача 2",
            status=TaskStatus.planned,
            first_planned_date=date(2026, 7, 16),
            created_at=now,
            updated_at=now,
        ),
    ]

    class Service:
        def get_visible_tasks_for_date(self, telegram_id, plan_date):
            assert plan_date == date(2026, 7, 16)
            return tasks

        def move_tasks(self, task_ids, *, telegram_id, target_date):
            assert task_ids == [1, 2]
            assert target_date == date(2026, 7, 17)
            return tasks

    class Message:
        async def reply_text(self, text):
            self.text = text

    monkeypatch.setattr("app.bot.handlers._task_service", lambda context: Service())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    context = SimpleNamespace(args=["2026-07-16", "1,2", "2026-07-17"])

    asyncio.run(_quick_move_tasks(update, context))

    assert "Перенесено задач: 2" in update.message.text


def test_quick_task_edit_defaults_to_today(monkeypatch) -> None:
    import asyncio
    from datetime import UTC, date, datetime
    from types import SimpleNamespace

    from app.bot.handlers import _quick_task_edit
    from app.models.task import Task, TaskStatus
    from app.services.task_service import TaskDetails

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    task = Task(
        id=1,
        daily_plan_id=1,
        text="Будущая задача",
        status=TaskStatus.planned,
        first_planned_date=date.today(),
        created_at=now,
        updated_at=now,
    )

    class Service:
        def get_visible_tasks_for_date(self, telegram_id, plan_date):
            assert plan_date == date.today()
            return [task]

        def update_task(self, task_id, *, telegram_id, update):
            assert task_id == 1
            assert update.status == TaskStatus.done
            return TaskDetails(task=task, plan_date=date.today())

    class Message:
        async def reply_text(self, text):
            self.text = text

    monkeypatch.setattr("app.bot.handlers._task_service", lambda context: Service())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    context = SimpleNamespace(args=["1", "-статус:выполнена"])

    asyncio.run(_quick_task_edit(update, context))

    assert "Задача обновлена" in update.message.text


def test_quick_move_defaults_source_date_to_today(monkeypatch) -> None:
    import asyncio
    from datetime import UTC, date, datetime, timedelta
    from types import SimpleNamespace

    from app.bot.handlers import _quick_move_tasks
    from app.models.task import Task, TaskStatus

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    task = Task(
        id=1,
        daily_plan_id=1,
        text="Задача на сегодня",
        status=TaskStatus.planned,
        first_planned_date=date.today(),
        created_at=now,
        updated_at=now,
    )

    class Service:
        def get_visible_tasks_for_date(self, telegram_id, plan_date):
            assert plan_date == date.today()
            return [task]

        def move_tasks(self, task_ids, *, telegram_id, target_date):
            assert task_ids == [1]
            assert target_date == date.today() + timedelta(days=1)
            return [task]

    class Message:
        async def reply_text(self, text):
            self.text = text

    monkeypatch.setattr("app.bot.handlers._task_service", lambda context: Service())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    context = SimpleNamespace(args=["1", "tomorrow"])

    asyncio.run(_quick_move_tasks(update, context))

    assert "Перенесено задач: 1" in update.message.text


def test_quick_move_ignores_spaces_after_commas(monkeypatch) -> None:
    import asyncio
    from datetime import UTC, date, datetime, timedelta
    from types import SimpleNamespace

    from app.bot.handlers import _quick_move_tasks
    from app.models.task import Task, TaskStatus

    tasks = [
        Task(id=index, daily_plan_id=1, text=f"Задача {index}", status=TaskStatus.planned,
             first_planned_date=date.today(), created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
        for index in (1, 2, 3)
    ]

    class Service:
        def get_visible_tasks_for_date(self, telegram_id, plan_date):
            assert plan_date == date.today()
            return tasks

        def move_tasks(self, task_ids, *, telegram_id, target_date):
            assert task_ids == [1, 2, 3]
            assert target_date == date.today() + timedelta(days=1)
            return tasks

    class Message:
        async def reply_text(self, text):
            self.text = text

    monkeypatch.setattr("app.bot.handlers._task_service", lambda context: Service())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    asyncio.run(_quick_move_tasks(update, SimpleNamespace(args=["1,", "2,", "3", "tomorrow"])))

    assert "Перенесено задач: 3" in update.message.text


def test_schedule_task_assigns_an_unscheduled_task_to_a_date(monkeypatch) -> None:
    import asyncio
    from datetime import UTC, date, datetime
    from types import SimpleNamespace

    from app.bot.handlers import receive_schedule_date
    from app.models.task import Task, TaskStatus

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    scheduled_task = Task(
        id=10,
        daily_plan_id=5,
        text="Задача без даты",
        status=TaskStatus.planned,
        first_planned_date=date(2026, 7, 16),
        created_at=now,
        updated_at=now,
    )

    class CaptureService:
        def schedule_unscheduled_task(self, task_id, *, telegram_id, target_date):
            assert task_id == 7
            assert telegram_id == 42
            assert target_date == date(2026, 7, 16)
            return scheduled_task

    class Message:
        text = "2026-07-16"

        async def reply_text(self, text):
            self.text = text

    monkeypatch.setattr("app.bot.handlers._capture_service", lambda context: CaptureService())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    context = SimpleNamespace(
        user_data={"schedule_source_type": "task", "schedule_source_id": 7}
    )

    asyncio.run(receive_schedule_date(update, context))

    assert "Задача назначена на 2026-07-16" in update.message.text
    assert context.user_data == {}


def test_schedule_task_assigns_an_idea_to_a_date(monkeypatch) -> None:
    import asyncio
    from datetime import UTC, date, datetime
    from types import SimpleNamespace

    from app.bot.handlers import receive_schedule_date
    from app.models.task import Task, TaskStatus

    now = datetime(2026, 7, 14, 12, tzinfo=UTC)
    scheduled_task = Task(
        id=11,
        daily_plan_id=5,
        text="Идея стала задачей",
        status=TaskStatus.planned,
        first_planned_date=date(2026, 7, 17),
        created_at=now,
        updated_at=now,
    )

    class CaptureService:
        def schedule_idea(self, idea_id, *, telegram_id, target_date):
            assert idea_id == 3
            assert telegram_id == 42
            assert target_date == date(2026, 7, 17)
            return scheduled_task

    class Message:
        text = "2026-07-17"

        async def reply_text(self, text):
            self.text = text

    monkeypatch.setattr("app.bot.handlers._capture_service", lambda context: CaptureService())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=Message())
    context = SimpleNamespace(
        user_data={"schedule_source_type": "idea", "schedule_source_id": 3}
    )

    asyncio.run(receive_schedule_date(update, context))

    assert "Задача назначена на 2026-07-17" in update.message.text
    assert context.user_data == {}
