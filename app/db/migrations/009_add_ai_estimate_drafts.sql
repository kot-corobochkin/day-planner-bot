CREATE TABLE IF NOT EXISTS ai_estimate_drafts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + INTERVAL '24 hours',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ai_estimate_drafts_status_check CHECK (
        status IN ('pending', 'applied', 'stale', 'superseded', 'expired')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_estimate_drafts_one_pending
    ON ai_estimate_drafts (user_id, plan_date)
    WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS ai_estimate_draft_items (
    draft_id BIGINT NOT NULL REFERENCES ai_estimate_drafts(id) ON DELETE CASCADE,
    task_id BIGINT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    proposal JSONB NOT NULL,
    PRIMARY KEY (draft_id, task_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_estimate_draft_items_task
    ON ai_estimate_draft_items (task_id);
