CREATE TABLE IF NOT EXISTS planning_agent_checkpoints (
    id BIGSERIAL PRIMARY KEY,
    daily_plan_id BIGINT NOT NULL REFERENCES daily_plans(id) ON DELETE CASCADE,
    failed_step TEXT NOT NULL,
    context JSONB NOT NULL,
    error TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'consumed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    consumed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_planning_agent_checkpoints_pending
    ON planning_agent_checkpoints (daily_plan_id, created_at DESC)
    WHERE status = 'pending';
