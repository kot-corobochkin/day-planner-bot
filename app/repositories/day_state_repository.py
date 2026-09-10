from psycopg import Connection
from psycopg.types.json import Jsonb

from app.models.day_state import DayStateProfile


class DayStateRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def upsert(self, *, daily_plan_id: int, survey_mode: str, brain_energy: int,
               concentration: int, mental_fatigue: int, physical_energy: int,
               desired_day_mode: str, alternate_categories: bool | None,
               long_answers: dict, recommended_strategies: list[str],
               selected_strategy: str, strategy_reason: str | None) -> DayStateProfile:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO daily_state_profiles (
                    daily_plan_id, survey_mode, brain_energy, concentration, mental_fatigue,
                    physical_energy, desired_day_mode, alternate_categories, long_answers,
                    recommended_strategies, selected_strategy, strategy_reason
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (daily_plan_id) DO UPDATE SET
                    survey_mode = EXCLUDED.survey_mode, brain_energy = EXCLUDED.brain_energy,
                    concentration = EXCLUDED.concentration, mental_fatigue = EXCLUDED.mental_fatigue,
                    physical_energy = EXCLUDED.physical_energy, desired_day_mode = EXCLUDED.desired_day_mode,
                    alternate_categories = EXCLUDED.alternate_categories, long_answers = EXCLUDED.long_answers,
                    recommended_strategies = EXCLUDED.recommended_strategies,
                    selected_strategy = EXCLUDED.selected_strategy, strategy_reason = EXCLUDED.strategy_reason,
                    updated_at = now()
                RETURNING daily_plan_id, survey_mode, brain_energy, concentration, mental_fatigue,
                    physical_energy, desired_day_mode, alternate_categories, long_answers,
                    recommended_strategies, selected_strategy, strategy_reason, created_at, updated_at
                """,
                (daily_plan_id, survey_mode, brain_energy, concentration, mental_fatigue,
                 physical_energy, desired_day_mode, alternate_categories, Jsonb(long_answers),
                 recommended_strategies, selected_strategy, strategy_reason),
            )
            row = cur.fetchone()
        assert row is not None
        return DayStateProfile.model_validate(row)

    def get(self, daily_plan_id: int) -> DayStateProfile | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """SELECT daily_plan_id, survey_mode, brain_energy, concentration,
                    mental_fatigue, physical_energy, desired_day_mode, alternate_categories,
                    long_answers, recommended_strategies, selected_strategy, strategy_reason,
                    created_at, updated_at FROM daily_state_profiles WHERE daily_plan_id = %s""",
                (daily_plan_id,),
            )
            row = cur.fetchone()
        return DayStateProfile.model_validate(row) if row else None
