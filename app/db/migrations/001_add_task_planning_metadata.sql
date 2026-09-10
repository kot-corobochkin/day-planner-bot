-- Adds optional data needed for task prioritization and feasibility analysis.
-- Safe to run once on an existing database created from the previous schema.

ALTER TABLE tasks
    ADD COLUMN IF NOT EXISTS estimated_minutes INTEGER,
    ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS priority SMALLINT NOT NULL DEFAULT 2,
    ADD COLUMN IF NOT EXISTS effort SMALLINT NOT NULL DEFAULT 2,
    ADD COLUMN IF NOT EXISTS context TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'tasks_estimated_minutes_check'
    ) THEN
        ALTER TABLE tasks
            ADD CONSTRAINT tasks_estimated_minutes_check CHECK (
                estimated_minutes IS NULL OR estimated_minutes > 0
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'tasks_priority_check'
    ) THEN
        ALTER TABLE tasks
            ADD CONSTRAINT tasks_priority_check CHECK (priority IN (1, 2, 3));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'tasks_effort_check'
    ) THEN
        ALTER TABLE tasks
            ADD CONSTRAINT tasks_effort_check CHECK (effort IN (1, 2, 3));
    END IF;
END $$;
