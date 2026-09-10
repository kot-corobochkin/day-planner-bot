CREATE TABLE IF NOT EXISTS planning_agent_runs (
    id BIGSERIAL PRIMARY KEY,
    daily_plan_id BIGINT NOT NULL REFERENCES daily_plans(id) ON DELETE CASCADE,
    trace JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_planning_agent_runs_plan_created
    ON planning_agent_runs (daily_plan_id, created_at DESC);
