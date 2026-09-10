-- URLs such as https://example.com used to be migrated as category "https".
UPDATE tasks
SET category = NULL
WHERE LOWER(BTRIM(category)) IN ('http', 'https', 'ftp');

UPDATE tasks
SET category = NULL
WHERE BTRIM(category) ~* '(^|[[:space:](/-])(https?|ftp)$';
