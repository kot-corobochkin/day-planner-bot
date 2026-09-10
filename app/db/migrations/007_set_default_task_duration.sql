-- Gives existing tasks a usable duration for feasibility analysis.
UPDATE tasks
SET estimated_minutes = 60
WHERE estimated_minutes IS NULL;

UPDATE unscheduled_tasks
SET estimated_minutes = 60
WHERE estimated_minutes IS NULL;

ALTER TABLE tasks
    ALTER COLUMN estimated_minutes SET DEFAULT 60;

ALTER TABLE unscheduled_tasks
    ALTER COLUMN estimated_minutes SET DEFAULT 60;
