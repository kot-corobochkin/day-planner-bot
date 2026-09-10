CREATE TABLE IF NOT EXISTS plan_feedback (
    id BIGSERIAL PRIMARY KEY,
    daily_plan_id BIGINT NOT NULL REFERENCES daily_plans(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_plan_feedback_plan_created
    ON plan_feedback (daily_plan_id, created_at DESC);
