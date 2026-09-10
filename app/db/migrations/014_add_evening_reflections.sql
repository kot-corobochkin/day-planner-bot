CREATE TABLE IF NOT EXISTS evening_reflections (
    id BIGSERIAL PRIMARY KEY,
    daily_plan_id BIGINT NOT NULL REFERENCES daily_plans(id) ON DELETE CASCADE,
    questions JSONB NOT NULL,
    answers JSONB NOT NULL DEFAULT '[]'::jsonb,
    source TEXT NOT NULL CHECK (source IN ('ai', 'fallback')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT evening_reflections_ten_questions CHECK (jsonb_array_length(questions) = 10),
    CONSTRAINT evening_reflections_max_ten_answers CHECK (jsonb_array_length(answers) <= 10)
);

CREATE INDEX IF NOT EXISTS idx_evening_reflections_plan_created
    ON evening_reflections (daily_plan_id, created_at DESC);
