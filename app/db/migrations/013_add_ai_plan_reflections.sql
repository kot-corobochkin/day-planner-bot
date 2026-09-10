CREATE TABLE IF NOT EXISTS ai_plan_reflections (
    id BIGSERIAL PRIMARY KEY,
    daily_plan_id BIGINT NOT NULL REFERENCES daily_plans(id) ON DELETE CASCADE,
    original_task_ids JSONB NOT NULL,
    reflected_task_ids JSONB NOT NULL,
    is_acceptable BOOLEAN NOT NULL,
    observations JSONB NOT NULL,
    user_message TEXT NOT NULL,
    decision TEXT NOT NULL DEFAULT 'pending' CHECK (
        decision IN ('pending', 'reflected_applied', 'original_applied', 'dismissed')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ai_plan_reflections_plan_created
    ON ai_plan_reflections (daily_plan_id, created_at DESC);
