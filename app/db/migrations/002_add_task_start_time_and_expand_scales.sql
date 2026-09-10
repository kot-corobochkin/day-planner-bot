-- Adds a scheduled start time and changes priority/effort from a 1-3 scale to 1-10.
-- Existing 2 values came from the old defaults, so they are normalized to 5 (medium).

ALTER TABLE tasks
    ADD COLUMN IF NOT EXISTS starts_at TIMESTAMPTZ;

ALTER TABLE tasks
    ALTER COLUMN priority SET DEFAULT 5,
    ALTER COLUMN effort SET DEFAULT 5;

ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_priority_check;
ALTER TABLE tasks
    ADD CONSTRAINT tasks_priority_check CHECK (priority BETWEEN 1 AND 10);

ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_effort_check;
ALTER TABLE tasks
    ADD CONSTRAINT tasks_effort_check CHECK (effort BETWEEN 1 AND 10);

UPDATE tasks SET priority = 5 WHERE priority = 2;
UPDATE tasks SET effort = 5 WHERE effort = 2;
