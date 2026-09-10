ALTER TABLE tasks
    ADD COLUMN IF NOT EXISTS priority_source TEXT NOT NULL DEFAULT 'default',
    ADD COLUMN IF NOT EXISTS effort_source TEXT NOT NULL DEFAULT 'default',
    ADD COLUMN IF NOT EXISTS duration_source TEXT NOT NULL DEFAULT 'default';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tasks_priority_source_check') THEN
        ALTER TABLE tasks ADD CONSTRAINT tasks_priority_source_check
            CHECK (priority_source IN ('default', 'user', 'ai_confirmed'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tasks_effort_source_check') THEN
        ALTER TABLE tasks ADD CONSTRAINT tasks_effort_source_check
            CHECK (effort_source IN ('default', 'user', 'ai_confirmed'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tasks_duration_source_check') THEN
        ALTER TABLE tasks ADD CONSTRAINT tasks_duration_source_check
            CHECK (duration_source IN ('default', 'user', 'ai_confirmed'));
    END IF;
END $$;
