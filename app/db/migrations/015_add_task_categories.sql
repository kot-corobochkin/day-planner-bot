ALTER TABLE tasks ADD COLUMN IF NOT EXISTS category TEXT;

UPDATE tasks
SET category = NULLIF(BTRIM(SPLIT_PART(text, ':', 1)), '')
WHERE POSITION(':' IN text) > 0 AND category IS NULL;

CREATE INDEX IF NOT EXISTS idx_tasks_category
    ON tasks (LOWER(category))
    WHERE category IS NOT NULL;
