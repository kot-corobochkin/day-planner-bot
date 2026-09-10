ALTER TABLE daily_plans
    ADD COLUMN IF NOT EXISTS available_minutes INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'daily_plans_available_minutes_check'
    ) THEN
        ALTER TABLE daily_plans
            ADD CONSTRAINT daily_plans_available_minutes_check CHECK (
                available_minutes IS NULL OR available_minutes BETWEEN 1 AND 1440
            );
    END IF;
END $$;
