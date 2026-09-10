-- Keeps the data required for deterministic task prioritization.

ALTER TABLE tasks
    ADD COLUMN IF NOT EXISTS first_planned_date DATE,
    ADD COLUMN IF NOT EXISTS postponement_count INTEGER NOT NULL DEFAULT 0;

UPDATE tasks AS task
SET first_planned_date = plan.plan_date
FROM daily_plans AS plan
WHERE task.daily_plan_id = plan.id
  AND task.first_planned_date IS NULL;

ALTER TABLE tasks
    ALTER COLUMN first_planned_date SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'tasks_postponement_count_check'
    ) THEN
        ALTER TABLE tasks
            ADD CONSTRAINT tasks_postponement_count_check CHECK (postponement_count >= 0);
    END IF;
END $$;
