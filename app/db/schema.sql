CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL UNIQUE,
    timezone TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS daily_plans (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_date DATE NOT NULL,
    day_type TEXT NOT NULL,
    available_minutes INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT daily_plans_one_per_user_day UNIQUE (user_id, plan_date),
    CONSTRAINT daily_plans_available_minutes_check CHECK (
        available_minutes IS NULL OR available_minutes BETWEEN 1 AND 1440
    )
);

CREATE TABLE IF NOT EXISTS tasks (
    id BIGSERIAL PRIMARY KEY,
    daily_plan_id BIGINT NOT NULL REFERENCES daily_plans(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    first_planned_date DATE NOT NULL,
    postponement_count INTEGER NOT NULL DEFAULT 0,
    estimated_minutes INTEGER DEFAULT 60,
    starts_at TIMESTAMPTZ,
    due_at TIMESTAMPTZ,
    priority SMALLINT NOT NULL DEFAULT 5,
    effort SMALLINT NOT NULL DEFAULT 5,
    priority_source TEXT NOT NULL DEFAULT 'default',
    effort_source TEXT NOT NULL DEFAULT 'default',
    duration_source TEXT NOT NULL DEFAULT 'default',
    context TEXT,
    category TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT tasks_status_check CHECK (status IN ('planned', 'done', 'postponed', 'cancelled')),
    CONSTRAINT tasks_postponement_count_check CHECK (postponement_count >= 0),
    CONSTRAINT tasks_estimated_minutes_check CHECK (
        estimated_minutes IS NULL OR estimated_minutes > 0
    ),
    CONSTRAINT tasks_priority_check CHECK (priority BETWEEN 1 AND 10),
    CONSTRAINT tasks_effort_check CHECK (effort BETWEEN 1 AND 10)
    , CONSTRAINT tasks_priority_source_check CHECK (priority_source IN ('default', 'user', 'ai_confirmed'))
    , CONSTRAINT tasks_effort_source_check CHECK (effort_source IN ('default', 'user', 'ai_confirmed'))
    , CONSTRAINT tasks_duration_source_check CHECK (duration_source IN ('default', 'user', 'ai_confirmed'))
);

CREATE INDEX IF NOT EXISTS idx_daily_plans_user_date ON daily_plans (user_id, plan_date);
CREATE INDEX IF NOT EXISTS idx_tasks_daily_plan_id ON tasks (daily_plan_id);
CREATE INDEX IF NOT EXISTS idx_tasks_category ON tasks (LOWER(category)) WHERE category IS NOT NULL;

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
    estimated_minutes INTEGER DEFAULT 60,
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
    decision TEXT NOT NULL DEFAULT 'pending',
    PRIMARY KEY (draft_id, task_id)
    , CONSTRAINT ai_estimate_draft_items_decision_check CHECK (
        decision IN ('pending', 'applied', 'dismissed')
    )
);

CREATE INDEX IF NOT EXISTS idx_ai_estimate_draft_items_task
    ON ai_estimate_draft_items (task_id);

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

CREATE TABLE IF NOT EXISTS planning_agent_runs (
    id BIGSERIAL PRIMARY KEY,
    daily_plan_id BIGINT NOT NULL REFERENCES daily_plans(id) ON DELETE CASCADE,
    trace JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_planning_agent_runs_plan_created
    ON planning_agent_runs (daily_plan_id, created_at DESC);

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

CREATE TABLE IF NOT EXISTS plan_feedback (
    id BIGSERIAL PRIMARY KEY,
    daily_plan_id BIGINT NOT NULL REFERENCES daily_plans(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_plan_feedback_plan_created
    ON plan_feedback (daily_plan_id, created_at DESC);

CREATE TABLE IF NOT EXISTS weekly_achievement_reports (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    week_start DATE NOT NULL,
    week_end DATE NOT NULL,
    earned_achievements JSONB NOT NULL,
    goal_achievement_name TEXT,
    goal_achievement_description TEXT,
    goal_status TEXT NOT NULL DEFAULT 'none' CHECK (
        goal_status IN ('none', 'pending', 'awarded', 'expired')
    ),
    goal_awarded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT weekly_achievement_reports_one_per_week UNIQUE (user_id, week_start),
    CONSTRAINT weekly_achievement_reports_period_check CHECK (week_end >= week_start),
    CONSTRAINT weekly_achievement_reports_achievements_check CHECK (
        jsonb_typeof(earned_achievements) = 'array'
        AND jsonb_array_length(earned_achievements) BETWEEN 1 AND 2
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_weekly_achievement_reports_one_pending
    ON weekly_achievement_reports (user_id)
    WHERE goal_status = 'pending';

CREATE TABLE IF NOT EXISTS weekly_achievement_goal_tasks (
    id BIGSERIAL PRIMARY KEY,
    report_id BIGINT NOT NULL REFERENCES weekly_achievement_reports(id) ON DELETE CASCADE,
    task_id BIGINT REFERENCES tasks(id) ON DELETE SET NULL,
    task_text TEXT NOT NULL,
    position SMALLINT NOT NULL CHECK (position BETWEEN 1 AND 5),
    CONSTRAINT weekly_achievement_goal_tasks_one_position UNIQUE (report_id, position),
    CONSTRAINT weekly_achievement_goal_tasks_one_task UNIQUE (report_id, task_id)
);

CREATE INDEX IF NOT EXISTS idx_weekly_achievement_goal_tasks_task
    ON weekly_achievement_goal_tasks (task_id)
    WHERE task_id IS NOT NULL;
