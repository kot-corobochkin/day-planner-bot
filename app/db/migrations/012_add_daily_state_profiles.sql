CREATE TABLE IF NOT EXISTS daily_state_profiles (
    daily_plan_id BIGINT PRIMARY KEY REFERENCES daily_plans(id) ON DELETE CASCADE,
    survey_mode TEXT NOT NULL CHECK (survey_mode IN ('short', 'long')),
    brain_energy SMALLINT NOT NULL CHECK (brain_energy BETWEEN 1 AND 10),
    concentration SMALLINT NOT NULL CHECK (concentration BETWEEN 1 AND 10),
    mental_fatigue SMALLINT NOT NULL CHECK (mental_fatigue BETWEEN 1 AND 10),
    physical_energy SMALLINT NOT NULL CHECK (physical_energy BETWEEN 1 AND 10),
    desired_day_mode TEXT NOT NULL,
    alternate_categories BOOLEAN,
    long_answers JSONB NOT NULL DEFAULT '{}'::jsonb,
    recommended_strategies TEXT[] NOT NULL,
    selected_strategy TEXT NOT NULL,
    strategy_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
