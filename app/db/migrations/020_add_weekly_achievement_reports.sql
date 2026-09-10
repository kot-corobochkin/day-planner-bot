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
