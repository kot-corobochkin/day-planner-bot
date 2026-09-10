CREATE TABLE IF NOT EXISTS daily_schedule_runs (
    id BIGSERIAL PRIMARY KEY,
    daily_plan_id BIGINT NOT NULL REFERENCES daily_plans(id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'ai',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT daily_schedule_runs_source_check CHECK (source IN ('ai', 'manual')),
    CONSTRAINT daily_schedule_runs_status_check CHECK (
        status IN ('active', 'superseded', 'stale')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_schedule_runs_one_active
    ON daily_schedule_runs (daily_plan_id)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS daily_schedule_slots (
    id BIGSERIAL PRIMARY KEY,
    schedule_run_id BIGINT NOT NULL REFERENCES daily_schedule_runs(id) ON DELETE CASCADE,
    task_id BIGINT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    buffer_after_minutes SMALLINT NOT NULL DEFAULT 15,
    reason TEXT,
    CONSTRAINT daily_schedule_slots_position_check CHECK (position >= 1),
    CONSTRAINT daily_schedule_slots_time_check CHECK (ends_at > starts_at),
    CONSTRAINT daily_schedule_slots_buffer_check CHECK (buffer_after_minutes BETWEEN 0 AND 120),
    CONSTRAINT daily_schedule_slots_one_task_per_run UNIQUE (schedule_run_id, task_id),
    CONSTRAINT daily_schedule_slots_one_position_per_run UNIQUE (schedule_run_id, position)
);

CREATE INDEX IF NOT EXISTS idx_daily_schedule_slots_task ON daily_schedule_slots (task_id);
