CREATE TABLE IF NOT EXISTS ideas (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS unscheduled_tasks (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    estimated_minutes INTEGER,
    priority SMALLINT NOT NULL DEFAULT 5,
    effort SMALLINT NOT NULL DEFAULT 5,
    context TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT unscheduled_tasks_estimated_minutes_check CHECK (
        estimated_minutes IS NULL OR estimated_minutes > 0
    ),
    CONSTRAINT unscheduled_tasks_priority_check CHECK (priority BETWEEN 1 AND 10),
    CONSTRAINT unscheduled_tasks_effort_check CHECK (effort BETWEEN 1 AND 10)
);

CREATE INDEX IF NOT EXISTS idx_ideas_user_created ON ideas (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_unscheduled_tasks_user_created ON unscheduled_tasks (user_id, created_at);
