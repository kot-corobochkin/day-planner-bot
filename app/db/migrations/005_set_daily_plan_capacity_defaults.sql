UPDATE daily_plans
SET available_minutes = CASE day_type
    WHEN 'Рабочий день' THEN 240
    WHEN 'Выходной' THEN 840
    WHEN 'Больничный' THEN 480
    WHEN 'Смешанный' THEN 480
    WHEN 'Workday' THEN 240
    WHEN 'Weekend' THEN 840
    WHEN 'Sick day' THEN 480
    ELSE 480
END
WHERE available_minutes IS NULL;
