ALTER TABLE ai_estimate_draft_items
    ADD COLUMN IF NOT EXISTS decision TEXT NOT NULL DEFAULT 'pending';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ai_estimate_draft_items_decision_check'
    ) THEN
        ALTER TABLE ai_estimate_draft_items
            ADD CONSTRAINT ai_estimate_draft_items_decision_check
            CHECK (decision IN ('pending', 'applied', 'dismissed'));
    END IF;
END $$;
